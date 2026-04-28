"""Fetch Wikivoyage city / district / park / itinerary pages and save
cleaned text to data/travel_guides/<kind>/<slug>.txt.

Idempotent: re-running overwrites .txt files. Skips files that already exist
unless --force is passed.

Polite: 1.0s delay between requests, identifies via User-Agent.
"""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import TRAVEL_GUIDES_DIR

API = "https://en.wikivoyage.org/w/api.php"
HEADERS = {"User-Agent": "TripPlanner-RAG/0.1 (educational project)"}
REQUEST_DELAY_SEC = 1.0

# Subdirectory layout — keeps data/travel_guides/ readable when browsing the repo.
KIND_DIRS = {
    "city":      "cities",
    "park":      "parks",
    "district":  "districts",
    "itinerary": "itineraries",
}


# ── Targets ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Target:
    page: str            # Wikivoyage page name
    slug: str            # filename stem
    city: str | None     # canonical city name for DB row (None = no DB row)
    state: str | None
    country: str | None
    travel_type: str | None
    kind: str            # "city" | "district" | "itinerary" | "park"
    parent: str | None = None  # parent city slug for districts


CA_CITIES = [
    Target("San_Francisco",         "san_francisco",         "San Francisco", "CA", "USA", "city",      "city"),
    Target("Oakland",               "oakland",               "Oakland",       "CA", "USA", "city",      "city"),
    Target("San_Jose_(California)", "san_jose",              "San Jose",      "CA", "USA", "city",      "city"),
    Target("Santa_Cruz_(California)", "santa_cruz",          "Santa Cruz",    "CA", "USA", "beach",     "city"),
    Target("Monterey_(California)", "monterey",              "Monterey",      "CA", "USA", "beach",     "city"),
    Target("Big_Sur",               "big_sur",               "Big Sur",       "CA", "USA", "nature",    "city"),
    Target("Los_Angeles",           "los_angeles",           "Los Angeles",   "CA", "USA", "city",      "city"),
    Target("Santa_Monica",          "santa_monica",          "Santa Monica",  "CA", "USA", "beach",     "city"),
    Target("San_Diego",             "san_diego",             "San Diego",     "CA", "USA", "beach",     "city"),
    Target("La_Jolla",              "la_jolla",              "La Jolla",      "CA", "USA", "beach",     "city"),
    Target("Palm_Springs",          "palm_springs",          "Palm Springs",  "CA", "USA", "city",      "city"),
    Target("Lake_Tahoe",            "lake_tahoe",            "Lake Tahoe",    "CA", "USA", "nature",    "city"),
]

CA_PARKS = [
    Target("Yosemite_National_Park",        "yosemite",         "Yosemite",         "CA", "USA", "nature", "park"),
    Target("Joshua_Tree_National_Park",     "joshua_tree",      "Joshua Tree",      "CA", "USA", "nature", "park"),
    Target("Death_Valley_National_Park",    "death_valley",     "Death Valley",     "CA", "USA", "nature", "park"),
    Target("Sequoia_National_Park",         "sequoia",          "Sequoia",          "CA", "USA", "nature", "park"),
    Target("Kings_Canyon_National_Park",    "kings_canyon",     "Kings Canyon",     "CA", "USA", "nature", "park"),
    Target("Redwood_National_Park",         "redwood",          "Redwood",          "CA", "USA", "nature", "park"),
    Target("Channel_Islands_National_Park", "channel_islands",  "Channel Islands",  "CA", "USA", "nature", "park"),
]

SF_DISTRICTS = [
    Target("San_Francisco/Mission",                         "san_francisco_mission",            None, None, None, None, "district", parent="san_francisco"),
    Target("San_Francisco/Castro-Noe_Valley",               "san_francisco_castro",             None, None, None, None, "district", parent="san_francisco"),
    Target("San_Francisco/Fisherman's_Wharf",               "san_francisco_fishermans_wharf",   None, None, None, None, "district", parent="san_francisco"),
    Target("San_Francisco/SoMa",                            "san_francisco_soma",               None, None, None, None, "district", parent="san_francisco"),
    Target("San_Francisco/Haight",                          "san_francisco_haight",             None, None, None, None, "district", parent="san_francisco"),
    Target("San_Francisco/Chinatown-North_Beach",           "san_francisco_chinatown",          None, None, None, None, "district", parent="san_francisco"),
    Target("San_Francisco/Golden_Gate",                     "san_francisco_golden_gate",        None, None, None, None, "district", parent="san_francisco"),
]

LA_DISTRICTS = [
    Target("Los_Angeles/Hollywood",     "los_angeles_hollywood",  None, None, None, None, "district", parent="los_angeles"),
    Target("Los_Angeles/Downtown",      "los_angeles_downtown",   None, None, None, None, "district", parent="los_angeles"),
    Target("Venice_Beach",              "los_angeles_venice",     None, None, None, None, "district", parent="los_angeles"),
    Target("Pasadena",                  "los_angeles_pasadena",   None, None, None, None, "district", parent="los_angeles"),
]

SD_DISTRICTS = [
    Target("San_Diego/Downtown",   "san_diego_downtown",  None, None, None, None, "district", parent="san_diego"),
    Target("Coronado_(California)", "san_diego_coronado",  None, None, None, None, "district", parent="san_diego"),
]

NEIGHBOR = [
    Target("Las_Vegas",                  "las_vegas",       "Las Vegas",     "NV", "USA", "city",      "city"),
    Target("Reno",                       "reno",            "Reno",          "NV", "USA", "city",      "city"),
    Target("Phoenix",                    "phoenix",         "Phoenix",       "AZ", "USA", "city",      "city"),
    Target("Sedona",                     "sedona",          "Sedona",        "AZ", "USA", "nature",    "city"),
    Target("Grand_Canyon_National_Park", "grand_canyon",    "Grand Canyon",  "AZ", "USA", "nature",    "park"),
    Target("Portland_(Oregon)",          "portland",        "Portland",      "OR", "USA", "city",      "city"),
    Target("Seattle",                    "seattle",         "Seattle",       "WA", "USA", "city",      "city"),
    Target("Anchorage",                  "anchorage",       "Anchorage",     "AK", "USA", "city",      "city"),
    Target("Denali_National_Park",       "denali",          "Denali",        "AK", "USA", "nature",    "park"),
    Target("Salt_Lake_City",             "salt_lake_city",  "Salt Lake City","UT", "USA", "city",      "city"),
]

ITINERARIES = [
    Target("Pacific_Coast_Highway",   "pacific_coast_highway",   None, None, None, None, "itinerary"),
    Target("U.S._Route_66",           "route_66",                None, None, None, None, "itinerary"),
    Target("Grand_Circle",            "grand_circle",            None, None, None, None, "itinerary"),
    Target("Pacific_Northwest",       "pacific_northwest",       None, None, None, None, "itinerary"),
    Target("Sierra_Nevada",           "sierra_nevada",           None, None, None, None, "itinerary"),
    Target("Lincoln_Highway",         "lincoln_highway",         None, None, None, None, "itinerary"),
    Target("California_desert_camping","california_desert_camping",None,None,None,None, "itinerary"),
]

# Popular US cities outside the West Coast that show up in user prompts.
US_CITIES = [
    Target("New_York_City",     "new_york_city",  "New York City", "NY", "USA", "city",  "city"),
    Target("Chicago",           "chicago",        "Chicago",       "IL", "USA", "city",  "city"),
    Target("Boston",            "boston",         "Boston",        "MA", "USA", "city",  "city"),
    Target("Washington,_D.C.",  "washington_dc",  "Washington",    "DC", "USA", "city",  "city"),
    Target("Miami",             "miami",          "Miami",         "FL", "USA", "beach", "city"),
    Target("New_Orleans",       "new_orleans",    "New Orleans",   "LA", "USA", "city",  "city"),
    Target("Honolulu",          "honolulu",       "Honolulu",      "HI", "USA", "beach", "city"),
    Target("Hawaii",            "hawaii",         "Hawaii",        "HI", "USA", "beach", "city"),
]

# Popular international destinations that come up in travel queries.
INTL_CITIES = [
    # Original 8 international destinations — replacing the old 30-line stubs
    # with real Wikivoyage content.
    Target("Bali",             "bali",         "Bali",         None, "Indonesia",   "beach",   "city"),
    Target("Paris",            "paris",        "Paris",        None, "France",      "city",    "city"),
    Target("Queenstown",       "queenstown",   "Queenstown",   None, "New Zealand", "nature",  "city"),
    Target("Tokyo",            "tokyo",        "Tokyo",        None, "Japan",       "city",    "city"),
    Target("Cape_Town",        "cape_town",    "Cape Town",    None, "South Africa","city",    "city"),
    Target("Machu_Picchu",     "machu_picchu", "Machu Picchu", None, "Peru",        "nature",  "city"),
    Target("Santorini",        "santorini",    "Santorini",    None, "Greece",      "beach",   "city"),
    Target("Reykjavík",        "reykjavik",    "Reykjavik",    None, "Iceland",     "city",    "city"),
    # New additions
    Target("London",     "london",     "London",     None, "United Kingdom", "city", "city"),
    Target("Barcelona",  "barcelona",  "Barcelona",  None, "Spain",          "city", "city"),
    Target("Madrid",     "madrid",     "Madrid",     None, "Spain",          "city", "city"),
    Target("Rome",       "rome",       "Rome",       None, "Italy",          "city", "city"),
    Target("Amsterdam",  "amsterdam",  "Amsterdam",  None, "Netherlands",    "city", "city"),
    Target("Berlin",     "berlin",     "Berlin",     None, "Germany",        "city", "city"),
    Target("Prague",     "prague",     "Prague",     None, "Czech Republic", "city", "city"),
    Target("Dubai",      "dubai",      "Dubai",      None, "UAE",            "city", "city"),
    Target("Singapore",  "singapore",  "Singapore",  None, "Singapore",      "city", "city"),
    Target("Bangkok",    "bangkok",    "Bangkok",    None, "Thailand",       "city", "city"),
    Target("Sydney",     "sydney",     "Sydney",     None, "Australia",      "city", "city"),
    Target("Hong_Kong",  "hong_kong",  "Hong Kong",  None, "China",          "city", "city"),
]

ALL_TARGETS = (
    CA_CITIES + CA_PARKS + SF_DISTRICTS + LA_DISTRICTS + SD_DISTRICTS
    + NEIGHBOR + ITINERARIES + US_CITIES + INTL_CITIES
)


# ── Wikitext fetching + cleaning ───────────────────────────────────────────────

def fetch_wikitext(page: str) -> str | None:
    params = {
        "action": "parse",
        "page": page,
        "prop": "wikitext",
        "format": "json",
        "formatversion": 2,
        "redirects": 1,
    }
    try:
        r = requests.get(API, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            print(f"  [api error] {page}: {data['error'].get('info', '?')}")
            return None
        return data["parse"]["wikitext"]
    except Exception as exc:
        print(f"  [fetch error] {page}: {exc}")
        return None


# Listing template fields we care about, in display order.
_LISTING_FIELDS = ["name", "address", "directions", "phone", "hours", "price", "content"]
_LISTING_TEMPLATE_NAMES = ("see", "do", "eat", "drink", "sleep", "buy", "listing")


def _split_top_level_pipes(body: str) -> list[str]:
    """Split a template body on `|` separators that aren't inside [[...]] or {{...}}."""
    parts: list[str] = []
    buf: list[str] = []
    sq = cu = 0
    i = 0
    while i < len(body):
        ch = body[i]
        nxt = body[i + 1] if i + 1 < len(body) else ""
        if ch == "[" and nxt == "[":
            sq += 1
            buf.extend([ch, nxt]); i += 2; continue
        if ch == "]" and nxt == "]":
            sq = max(0, sq - 1)
            buf.extend([ch, nxt]); i += 2; continue
        if ch == "{" and nxt == "{":
            cu += 1
            buf.extend([ch, nxt]); i += 2; continue
        if ch == "}" and nxt == "}":
            cu = max(0, cu - 1)
            buf.extend([ch, nxt]); i += 2; continue
        if ch == "|" and sq == 0 and cu == 0:
            parts.append("".join(buf)); buf = []; i += 1; continue
        buf.append(ch); i += 1
    if buf:
        parts.append("".join(buf))
    return parts


def _flatten_listing(template_body: str) -> str:
    """Turn `name=... | address=... | content=...` into one tidy line."""
    fields: dict[str, str] = {}
    parts = _split_top_level_pipes(template_body)
    for part in parts:
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        fields[k.strip().lower()] = v.strip()

    name = fields.get("name", "").strip()
    if not name:
        return ""
    bits: list[str] = [name]
    for field in ["address", "directions", "phone", "hours", "price"]:
        v = fields.get(field, "")
        if v:
            bits.append(v)
    content = fields.get("content", "")
    if content:
        bits.append(content)
    line = " — ".join(b for b in bits if b)
    return line


def _strip_links(text: str) -> str:
    # [[File:...]] and [[Image:...]] → drop entirely (often span several lines)
    text = re.sub(r"\[\[(?:File|Image):[^\[\]]*?(?:\[\[[^\]]*\]\][^\[\]]*?)*\]\]", "", text, flags=re.I)
    # [[Page|label]] → label
    text = re.sub(r"\[\[(?:[^\[\]|]*\|)?([^\[\]|]+)\]\]", r"\1", text)
    # [http://url label] → label
    text = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\]", "", text)
    return text


def clean_wikitext(wt: str, slug: str) -> str:
    """Strip wikitext to readable paragraphs, preserving section headers and
    flattening listing templates into single lines."""
    # Drop HTML comments.
    wt = re.sub(r"<!--.*?-->", "", wt, flags=re.S)
    # Drop ref/gallery/mapframe/mapshape/regionlist tags & templates wholesale.
    wt = re.sub(r"<ref[^>]*>.*?</ref>", "", wt, flags=re.S | re.I)
    wt = re.sub(r"<ref[^>]*/>", "", wt, flags=re.I)
    wt = re.sub(r"<gallery>.*?</gallery>", "", wt, flags=re.S | re.I)

    # Replace listing templates first (before generic template stripping).
    def _listing_sub(m: re.Match) -> str:
        tpl = m.group(1).lower()
        body = m.group(2)
        line = _flatten_listing(body)
        return f"\n• {line}\n" if line else ""

    pattern = re.compile(
        r"\{\{\s*(" + "|".join(_LISTING_TEMPLATE_NAMES) + r")\b\s*\|(.+?)\}\}",
        flags=re.S | re.I,
    )
    # Run repeatedly to handle templates whose body contains nested {{ }}.
    for _ in range(5):
        new = pattern.sub(_listing_sub, wt)
        if new == wt:
            break
        wt = new

    # Strip remaining {{...}} templates (including multi-level nesting).
    for _ in range(8):
        new = re.sub(r"\{\{[^{}]*\}\}", "", wt)
        if new == wt:
            break
        wt = new

    # Convert wiki links.
    wt = _strip_links(wt)

    # Drop tables wholesale (rare in Wikivoyage city pages, noisy when present).
    wt = re.sub(r"\{\|.*?\|\}", "", wt, flags=re.S)

    # Bold/italic markers.
    wt = re.sub(r"'''(.*?)'''", r"\1", wt)
    wt = re.sub(r"''(.*?)''", r"\1", wt)

    # Bullet/number list prefixes — collapse to plain '- '.
    wt = re.sub(r"^[*#]+\s*", "- ", wt, flags=re.M)
    # Indents.
    wt = re.sub(r"^:+\s*", "", wt, flags=re.M)

    # Collapse triple+ blank lines.
    wt = re.sub(r"\n{3,}", "\n\n", wt)

    # Add slug header so the ingester can recover the slug from the file.
    return f"<!-- slug: {slug} -->\n" + wt.strip() + "\n"


def extract_understand_blurb(cleaned: str, max_chars: int = 300) -> str:
    """Pull the first real prose paragraph for the description column.
    Skips slug comments, headers (== or ===), bullet lines, and blank lines.
    """
    for raw_paragraph in cleaned.split("\n\n"):
        # Strip slug HTML comment and other comments.
        paragraph = re.sub(r"<!--.*?-->", "", raw_paragraph, flags=re.S).strip()
        if not paragraph:
            continue
        # Skip pure-header paragraphs (`==Title==` / `===Sub===`).
        if re.fullmatch(r"=+[^=].*?=+", paragraph):
            continue
        # Skip if it starts with a header line (multi-line block led by header).
        first = paragraph.splitlines()[0].strip()
        if first.startswith("==") or first.startswith("__"):
            continue
        # Skip listing/bullet-only paragraphs.
        if all(line.lstrip().startswith(("-", "•")) for line in paragraph.splitlines() if line.strip()):
            continue
        blurb = re.sub(r"\s+", " ", paragraph)
        if len(blurb) >= 60:
            return blurb[:max_chars]
    return ""


# ── Main ───────────────────────────────────────────────────────────────────────

def target_path(target: Target) -> Path:
    subdir = KIND_DIRS[target.kind]
    return Path(TRAVEL_GUIDES_DIR) / subdir / f"{target.slug}.txt"


def run(force: bool = False) -> None:
    base = Path(TRAVEL_GUIDES_DIR)
    base.mkdir(parents=True, exist_ok=True)
    for sub in KIND_DIRS.values():
        (base / sub).mkdir(parents=True, exist_ok=True)

    ok = skipped = fail = 0
    for i, t in enumerate(ALL_TARGETS, 1):
        out_path = target_path(t)
        if out_path.exists() and not force:
            print(f"[{i}/{len(ALL_TARGETS)}] {t.page}  -> skip (exists)")
            skipped += 1
            continue
        print(f"[{i}/{len(ALL_TARGETS)}] {t.page}")
        wt = fetch_wikitext(t.page)
        if wt is None:
            fail += 1
            time.sleep(REQUEST_DELAY_SEC)
            continue
        cleaned = clean_wikitext(wt, slug=t.slug)
        out_path.write_text(cleaned, encoding="utf-8")
        ok += 1
        print(f"   wrote {out_path.relative_to(base)} ({out_path.stat().st_size/1024:.1f} KB)")
        time.sleep(REQUEST_DELAY_SEC)

    print()
    print(f"Done. fetched={ok}  skipped={skipped}  failed={fail}.  Tree: {base}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="Re-fetch even if .txt exists")
    args = p.parse_args()
    run(force=args.force)
