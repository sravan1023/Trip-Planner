from __future__ import annotations

import re
from pathlib import Path

from config import TRAVEL_GUIDES_DIR
from rag.embedder import embed_texts
from rag.vector_store import add_documents


# Wikivoyage section -> canonical bucket used in metadata + filter UX.
_SECTION_ALIASES = {
    "see": "See", "do": "Do", "eat": "Eat", "drink": "Drink",
    "sleep": "Sleep", "buy": "Buy",
    "understand": "Understand", "history": "Understand", "climate": "Understand",
    "get in": "GetIn", "get out": "GetOut", "go next": "GetOut",
    "get around": "GetAround",
    "stay safe": "StaySafe", "respect": "StaySafe", "cope": "StaySafe",
    "connect": "Connect",
    "districts": "Districts", "regions": "Districts",
    "itineraries": "Itineraries",
}


def _canon_section(header: str) -> str:
    return _SECTION_ALIASES.get(header.strip().lower(), header.strip().title())


def _load_target_metadata() -> dict[str, dict]:
    """Build slug -> metadata dict from the scraper's authoritative target list.
    Falls back to an empty dict if the scraper module is missing."""
    try:
        from scripts.scrape_wikivoyage import ALL_TARGETS
    except Exception:
        return {}

    by_slug: dict[str, dict] = {}
    for t in ALL_TARGETS:
        # Districts inherit city/state/country from their parent city target.
        parent_meta: dict[str, str | None] = {}
        if t.parent:
            parent = next((p for p in ALL_TARGETS if p.slug == t.parent), None)
            if parent is not None:
                parent_meta = {
                    "city": parent.city,
                    "state": parent.state,
                    "country": parent.country,
                }

        # District name = the part of slug after the parent city slug.
        district = None
        if t.parent and t.slug.startswith(t.parent + "_"):
            district = t.slug[len(t.parent) + 1:].replace("_", " ").title()

        by_slug[t.slug] = {
            "slug": t.slug,
            "city": parent_meta.get("city") or (t.city or ""),
            "state": parent_meta.get("state") or (t.state or ""),
            "country": parent_meta.get("country") or (t.country or ""),
            "kind": t.kind,                    # city/park/district/itinerary
            "type": "itinerary" if t.kind == "itinerary" else "guide",
            "district": district or "",
        }
    return by_slug


_TARGET_META = _load_target_metadata()


# Original international destinations that pre-date the Wikivoyage scraper.
# Hard-coded so RAG metadata filtering still works for them.
_INTERNATIONAL_META = {
    "bali":         {"city": "Bali",         "country": "Indonesia"},
    "paris":        {"city": "Paris",        "country": "France"},
    "queenstown":   {"city": "Queenstown",   "country": "New Zealand"},
    "tokyo":        {"city": "Tokyo",        "country": "Japan"},
    "cape_town":    {"city": "Cape Town",    "country": "South Africa"},
    "machu_picchu": {"city": "Machu Picchu", "country": "Peru"},
    "santorini":    {"city": "Santorini",    "country": "Greece"},
    "reykjavik":    {"city": "Reykjavik",    "country": "Iceland"},
}


def _read_file(path: str) -> str:
    if path.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _strip_slug_comment(text: str) -> str:
    return re.sub(r"<!--\s*slug:[^>]*-->\s*", "", text, count=1)


def _pack(units: list[str], joiner: str, max_chars: int) -> list[str]:
    """Greedy bin-packing: keep units intact, concatenate with `joiner` while
    staying <= max_chars. Units larger than max_chars stay as one chunk so we
    never split mid-sentence."""
    chunks: list[str] = []
    buf = ""
    for u in units:
        if not u:
            continue
        if not buf:
            buf = u
        elif len(buf) + len(joiner) + len(u) <= max_chars:
            buf = f"{buf}{joiner}{u}"
        else:
            chunks.append(buf)
            buf = u
    if buf:
        chunks.append(buf)
    return chunks


def _split_paragraphs(text: str, max_chars: int) -> list[str]:
    """Split long text into chunks <= max_chars without breaking sentences.
    Tries paragraph boundaries (\\n\\n) first; for paragraphs that are still
    too large (e.g. long bullet lists separated by single \\n), falls through
    to single-newline boundaries."""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    out: list[str] = []
    for chunk in _pack(paragraphs, "\n\n", max_chars):
        if len(chunk) <= max_chars:
            out.append(chunk)
            continue
        # Oversize paragraph (often a bullet list) — re-pack on single newlines.
        lines = [ln.strip() for ln in chunk.split("\n") if ln.strip()]
        out.extend(_pack(lines, "\n", max_chars))
    return out


# Header lines `==Section==` or `===Subsection===` (any depth).
_HEADER_RE = re.compile(r"^\s*(=+)\s*([^=].*?[^=]|.)\s*\1\s*$", re.M)


def _section_chunks(text: str, max_chars: int = 800) -> list[tuple[str, str]]:
    """Yield (section_name, chunk_text) for a full guide. Splits at top-level
    `==Section==` boundaries; re-splits sections > max_chars on paragraph
    boundaries. Subsections are kept inside their parent section's chunk(s).
    Pre-header intro becomes section 'Intro'."""
    text = _strip_slug_comment(text)

    # Find all top-level (== ==, exactly two `=`) boundaries. Anything deeper
    # is treated as content of the enclosing section.
    boundaries: list[tuple[int, int, str]] = []  # (start, end, section_name)
    for m in re.finditer(r"^==\s*([^=].*?[^=]|.)\s*==\s*$", text, flags=re.M):
        boundaries.append((m.start(), m.end(), _canon_section(m.group(1))))

    sections: list[tuple[str, str]] = []
    if not boundaries or boundaries[0][0] > 0:
        intro = text[:boundaries[0][0]].strip() if boundaries else text.strip()
        if intro:
            sections.append(("Intro", intro))

    for i, (_, header_end, name) in enumerate(boundaries):
        body_start = header_end
        body_end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            sections.append((name, body))

    out: list[tuple[str, str]] = []
    for name, body in sections:
        if len(body) <= max_chars:
            out.append((name, body))
        else:
            for piece in _split_paragraphs(body, max_chars=max_chars):
                out.append((name, piece))
    return out


def _meta_for_slug(slug: str, kind: str) -> dict:
    """Resolve metadata for a given file. Falls back to the international
    lookup (Bali/Paris/...) and finally to slug-derived defaults."""
    base = _TARGET_META.get(slug)
    if base:
        return dict(base)
    intl = _INTERNATIONAL_META.get(slug)
    if intl:
        return {
            "slug": slug,
            "city": intl["city"],
            "state": "",
            "country": intl["country"],
            "kind": kind,
            "type": "itinerary" if kind == "itineraries" else "guide",
            "district": "",
        }
    return {
        "slug": slug,
        "city": slug.replace("_", " ").title(),
        "state": "",
        "country": "",
        "kind": kind,
        "type": "itinerary" if kind == "itineraries" else "guide",
        "district": "",
    }


def _fallback_chunks(text: str) -> list[str]:
    """Old fixed-window splitter; used when section-aware pass yields nothing."""
    chunk_size, overlap = 500, 50
    chunks, start = [], 0
    while start < len(text):
        chunk = text[start:start + chunk_size].strip()
        if len(chunk) >= 100:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def ingest_guides() -> int:
    guide_dir = Path(TRAVEL_GUIDES_DIR)
    if not guide_dir.exists():
        return 0

    ids, docs, metas = [], [], []

    for filepath in guide_dir.rglob("*"):
        if not filepath.is_file():
            continue
        if filepath.suffix.lower() not in (".txt", ".pdf"):
            continue

        raw = _read_file(str(filepath))
        # Parent directory name (cities/parks/districts/itineraries) is the
        # `kind` for this file.
        kind = filepath.parent.name if filepath.parent != guide_dir else "other"
        slug = filepath.stem
        base_meta = _meta_for_slug(slug, kind)

        chunks = _section_chunks(raw)
        if not chunks:
            chunks = [("Intro", c) for c in _fallback_chunks(_strip_slug_comment(raw))]

        for i, (section, chunk) in enumerate(chunks):
            if len(chunk) < 100:
                continue
            meta = {
                **base_meta,
                "section": section,
                "source": f"{kind}/{filepath.name}#{section}:{i}",
            }
            # Chroma forbids None values in metadata — coerce to empty string.
            meta = {k: ("" if v is None else v) for k, v in meta.items()}
            ids.append(f"guide_{slug}_{i}")
            docs.append(chunk)
            metas.append(meta)

    if not docs:
        return 0

    embeddings = embed_texts(docs)
    add_documents(ids=ids, documents=docs, embeddings=embeddings, metadatas=metas)
    return len(docs)


def run_full_ingest() -> dict:
    guide_count = ingest_guides()
    return {"guide_docs": guide_count, "total": guide_count}
