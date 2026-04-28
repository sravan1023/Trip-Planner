"""Build the SQLite layer from the existing Chroma collection.

Walks every chunk, groups by `slug` to derive `destinations` rows, then
parses each chunk's text for the `• Name — address — phone — hours — price
— description` listing lines the Wikivoyage cleaner left behind. Each
listing becomes a row in `listings` with category = the chunk's `section`
metadata field.

Idempotent: drops and recreates the tables on every run, so a re-ingest
of Chroma can be followed by a fresh `build_sqlite.py` to keep the two
stores in sync.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import database                                              # noqa: E402
from rag.vector_store import get_collection                  # noqa: E402
from scripts.scrape_wikivoyage import ALL_TARGETS            # noqa: E402

# slug -> Target so we can pull travel_type / parent_slug from the canonical
# scraper definitions (they aren't on every chunk's metadata).
_TARGETS_BY_SLUG = {t.slug: t for t in ALL_TARGETS}


# Categories we treat as listings (the Wikivoyage section names that contain
# `{{see}}/{{do}}/{{eat}}/{{drink}}/{{sleep}}/{{buy}}` templates).
_LISTING_CATEGORIES = {"See", "Do", "Eat", "Drink", "Sleep", "Buy"}

_LISTING_LINE = re.compile(r"^\s*-?\s*•\s*(.+)$", re.M)
# The cleaner uses an em-dash with spaces around it as the field separator.
# We split into at most 6 fields: name, address, phone, hours, price, description.
_FIELD_SEP = re.compile(r"\s+—\s+")


def _parse_listing_line(line: str) -> dict | None:
    """Best-effort split of a flattened listing line into structured fields.
    Lines vary — some have only `name — description`, some have all six fields,
    some put hours where price should be. We assign greedily and leave the
    tail in `description`."""
    parts = _FIELD_SEP.split(line.strip())
    if not parts or not parts[0].strip():
        return None
    fields = ["name", "address", "phone", "hours", "price", "description"]
    out = {f: None for f in fields}
    out["name"] = parts[0].strip()
    # Anything after position 5 is concatenated into description so we don't
    # lose the tail when the line has more than 6 segments.
    for i, val in enumerate(parts[1:], start=1):
        if i < len(fields) - 1:
            out[fields[i]] = val.strip() or None
        else:
            tail = " — ".join(parts[i:]).strip()
            out["description"] = tail or None
            break
    # Heuristic cleanups for misclassified fields.
    if out.get("phone") and not re.search(r"[\d()+]", out["phone"]):
        # If "phone" has no digits, it's probably hours — shift down.
        out["description"] = (out.get("description") or out.get("price") or "")
        out["price"] = out.get("hours")
        out["hours"] = out.get("phone")
        out["phone"] = None
    if out.get("name") and len(out["name"]) > 200:
        return None  # Junk line that didn't actually start with •.
    return out


def _description_blurb(intro_text: str, max_chars: int = 300) -> str:
    """First substantive paragraph of an intro chunk, capped."""
    text = " ".join(intro_text.split())
    return text[:max_chars]


def main() -> None:
    print(f"resetting {database.DB_PATH}")
    database.reset()

    coll = get_collection()
    print(f"reading {coll.count()} chunks from Chroma…")
    data = coll.get(include=["documents", "metadatas"])
    ids       = data.get("ids", []) or []
    docs      = data.get("documents", []) or []
    metas     = data.get("metadatas", []) or []
    print(f"  got {len(ids)} chunks")

    # Group chunks by slug → derive one destination row per slug.
    by_slug: dict[str, list[tuple[str, str, dict]]] = {}
    for cid, doc, meta in zip(ids, docs, metas):
        slug = (meta or {}).get("slug")
        if not slug:
            continue
        by_slug.setdefault(slug, []).append((cid, doc, meta or {}))
    print(f"  -> {len(by_slug)} unique destinations")

    n_listings = 0
    with database.connect() as conn:
        for slug, chunks in by_slug.items():
            # Pick a canonical metadata snapshot (any chunk works; metadata is
            # constant per slug). Compute description from the Intro chunk
            # if we have one.
            sample_meta = chunks[0][2]
            intro_text = ""
            for cid, doc, meta in chunks:
                if meta.get("section") == "Intro":
                    intro_text = doc
                    break
            if not intro_text:
                intro_text = chunks[0][1]

            target = _TARGETS_BY_SLUG.get(slug)
            dest_id = database.upsert_destination(conn, {
                "slug":        slug,
                "city":        sample_meta.get("city") or slug.replace("_", " ").title(),
                "state":       sample_meta.get("state") or None,
                "country":     sample_meta.get("country") or None,
                "kind":        sample_meta.get("kind") or "city",
                "travel_type": (target.travel_type if target else None) or sample_meta.get("kind") or None,
                "parent_slug": (target.parent if target else None),
                "description": _description_blurb(intro_text),
                "n_chunks":    len(chunks),
            })

            # Parse every chunk's listings.
            for cid, doc, meta in chunks:
                section = meta.get("section") or ""
                if section not in _LISTING_CATEGORIES:
                    continue
                for m in _LISTING_LINE.finditer(doc):
                    parsed = _parse_listing_line(m.group(1))
                    if not parsed or not parsed.get("name"):
                        continue
                    database.upsert_listing(conn, {
                        "destination_id":   dest_id,
                        "category":         section,
                        "name":             parsed["name"],
                        "address":          parsed.get("address"),
                        "phone":            parsed.get("phone"),
                        "hours":            parsed.get("hours"),
                        "price":            parsed.get("price"),
                        "description":      parsed.get("description"),
                        "source_chunk_id":  cid,
                    })
                    n_listings += 1

    print()
    print("done.")
    s = database.stats()
    print(f"  destinations: {s['destinations']}  (by kind: {s['destinations_by_kind']})")
    print(f"  listings:     {s['listings']}      (by category: {s['listings_by_category']})")


if __name__ == "__main__":
    main()
