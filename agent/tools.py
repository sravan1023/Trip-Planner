import datetime as _dt

import requests
from bs4 import BeautifulSoup

from config import RAG_TOP_K


_HTTP_HEADERS = {"User-Agent": "TripPlanner-VA/0.2 (educational project)"}


# ── Live data tools ───────────────────────────────────────────────────────────

def get_weather(city: str) -> dict:
    """Live current conditions + 3-day forecast from wttr.in.
    Each forecast day is labelled `today` / `tomorrow` / `day_after_tomorrow`
    so the LLM can answer date-relative questions without doing math."""
    try:
        url = f"https://wttr.in/{city}?format=j1"
        resp = requests.get(url, timeout=10, headers=_HTTP_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        current = data["current_condition"][0]
        forecast_days = data.get("weather", [])[:3]
        labels = ["today", "tomorrow", "day_after_tomorrow"]
        forecast = []
        for label, day in zip(labels, forecast_days):
            # `hourly[4]` is the noon slot (~12:00) — most representative for
            # "what's it like during the day".
            noon = day["hourly"][4]
            forecast.append({
                "label": label,
                "date": day["date"],
                "max_c": day["maxtempC"],
                "min_c": day["mintempC"],
                "max_f": day["maxtempF"],
                "min_f": day["mintempF"],
                "description": noon["weatherDesc"][0]["value"],
                "chance_of_rain_pct": noon.get("chanceofrain", "?"),
                "wind_kmph": noon.get("windspeedKmph", "?"),
            })
        return {
            "city": city,
            "fetched_at_utc": _dt.datetime.utcnow().isoformat(timespec="minutes") + "Z",
            "source": "wttr.in (live)",
            "current": {
                "temp_c": current["temp_C"],
                "temp_f": current["temp_F"],
                "feels_like_c": current["FeelsLikeC"],
                "description": current["weatherDesc"][0]["value"],
                "humidity_pct": current["humidity"],
                "wind_kmph": current["windspeedKmph"],
            },
            "forecast": forecast,
        }
    except Exception as e:
        return {"city": city, "error": f"{type(e).__name__}: {e}"}


# ── UK Foreign Office advisory + entry-requirements (live JSON) ───────────────

# The gov.uk Foreign Travel Advice API is a clean JSON feed with per-country
# Summary / Warnings / Safety / Entry-requirements sections. Updated daily.
# https://content-api.publishing.service.gov.uk/foreign-travel-advice
_GOVUK_API = "https://www.gov.uk/api/content/foreign-travel-advice"


def _govuk_country_slug(country: str) -> str:
    s = country.strip().lower()
    # Common normalizations the gov.uk slugs use.
    s = s.replace(",", "").replace(".", "").replace("'", "")
    s = s.replace("&", "and").replace("/", "-")
    return "-".join(s.split())


def _html_to_text(html: str, max_chars: int = 1800) -> str:
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    text = " ".join(text.split())
    if len(text) > max_chars:
        text = text[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return text


def _fetch_govuk_advice(country: str) -> dict | None:
    slug = _govuk_country_slug(country)
    url = f"{_GOVUK_API}/{slug}"
    resp = requests.get(url, timeout=10, headers=_HTTP_HEADERS)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


# Sections we surface from a country's advisory page, in priority order. Not
# every country has every section — Mexico has no "Summary"; Spain has no
# "Regional risks". We pick the first 3 that are present and non-empty.
_ADVISORY_SECTIONS_PRIORITY = (
    "Summary",
    "Warnings and insurance",
    "Safety and security",
    "Regional risks",
    "Terrorism",
    "Entry requirements",
    "Health",
)


def get_travel_advisory(country: str) -> dict:
    """Live travel advisory from the UK Foreign Office (gov.uk). Returns the
    most relevant sections (priority: Summary, Warnings, Safety) — whichever
    are present for that country."""
    try:
        data = _fetch_govuk_advice(country)
        if data is None:
            return {
                "country": country,
                "error": (
                    f"No UK Foreign Office advisory page found for '{country}'. "
                    "Check the spelling or try a different country name."
                ),
            }
        parts = (data.get("details") or {}).get("parts", []) or []
        sections = {p.get("title", ""): p.get("body", "") for p in parts}

        chosen: list[dict] = []
        for title in _ADVISORY_SECTIONS_PRIORITY:
            body = sections.get(title)
            if not body:
                continue
            text = _html_to_text(body, max_chars=1500)
            if text:
                chosen.append({"section": title, "text": text})
            if len(chosen) >= 3:
                break

        return {
            "country": country,
            "source": "UK Foreign, Commonwealth & Development Office",
            "url": "https://www.gov.uk" + (data.get("base_path") or ""),
            "last_updated": data.get("public_updated_at") or data.get("updated_at"),
            "available_sections": list(sections.keys()),
            "advisory": chosen,
            "note": (
                "These advisories are written for UK travelers. Most safety/security "
                "guidance is broadly applicable, but check your own government's "
                "travel advisory for citizenship-specific guidance."
            ),
        }
    except Exception as e:
        return {"country": country, "error": f"{type(e).__name__}: {e}"}


def get_visa_info(nationality: str, destination_country: str) -> dict:
    """Live entry-requirement info from the UK Foreign Office for the
    destination country. Includes a clear note that the rules are written
    from the UK government's perspective and the user should verify with
    their own embassy / the destination's consulate."""
    try:
        data = _fetch_govuk_advice(destination_country)
        if data is None:
            return {
                "nationality": nationality,
                "destination": destination_country,
                "error": (
                    f"No UK Foreign Office page found for '{destination_country}'. "
                    "Check the spelling or use the official destination embassy site."
                ),
            }
        parts = (data.get("details") or {}).get("parts", []) or []
        entry_html = ""
        entry_title = ""
        for p in parts:
            title = p.get("title", "")
            if "entry" in title.lower() and "requirement" in title.lower():
                entry_html = p.get("body", "")
                entry_title = title
                break
        return {
            "nationality": nationality,
            "destination": destination_country,
            "source": "UK Foreign, Commonwealth & Development Office",
            "url": "https://www.gov.uk" + (data.get("base_path") or ""),
            "last_updated": data.get("public_updated_at") or data.get("updated_at"),
            "section_title": entry_title,
            "entry_requirements": _html_to_text(entry_html, max_chars=2500),
            "important_note": (
                f"These rules are written from the UK government's perspective. "
                f"As a {nationality} traveler, your specific visa-on-arrival, "
                "ESTA/eTA, transit, and length-of-stay requirements may differ. "
                "Always verify with your country's embassy or the destination's "
                "consulate before booking."
            ),
        }
    except Exception as e:
        return {
            "nationality": nationality,
            "destination": destination_country,
            "error": f"{type(e).__name__}: {e}",
        }


# ── Structured SQLite queries ─────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def search_destinations(
    country: str | None = None,
    state: str | None = None,
    kind: str | None = None,
    travel_type: str | None = None,
    name_contains: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Structured lookup over the `destinations` table. Use for queries like
    'cities in Spain', 'beach destinations', 'national parks in California'.
    Returns rows with: slug, city, state, country, kind, travel_type, description, n_chunks."""
    import database
    where: list[str] = []
    args: list = []
    if country:
        where.append("LOWER(country) = LOWER(?)"); args.append(country)
    if state:
        where.append("state = ?"); args.append(state)
    if kind:
        where.append("kind = ?"); args.append(kind)
    if travel_type:
        where.append("travel_type = ?"); args.append(travel_type)
    if name_contains:
        where.append("LOWER(city) LIKE ?"); args.append(f"%{name_contains.lower()}%")

    sql = "SELECT * FROM destinations"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY n_chunks DESC LIMIT ?"
    args.append(int(limit))

    with database.connect() as conn:
        return [_row_to_dict(r) for r in conn.execute(sql, args)]


def search_listings(
    city: str | None = None,
    country: str | None = None,
    category: str | None = None,
    name_contains: str | None = None,
    limit: int = 15,
) -> list[dict]:
    """Structured lookup over the `listings` table — individual See/Do/Eat/
    Drink/Sleep/Buy entries extracted from the chunks. Use for queries like
    'restaurants in San Francisco', 'hotels in Tokyo', 'museums in London'.
    Returns rows with: name, category, address, phone, hours, price, description, city."""
    import database
    where: list[str] = []
    args: list = []
    if city:
        where.append("LOWER(d.city) = LOWER(?)"); args.append(city)
    if country:
        where.append("LOWER(d.country) = LOWER(?)"); args.append(country)
    if category:
        where.append("l.category = ?"); args.append(category)
    if name_contains:
        where.append("LOWER(l.name) LIKE ?"); args.append(f"%{name_contains.lower()}%")

    sql = (
        "SELECT l.name, l.category, l.address, l.phone, l.hours, l.price, "
        "       l.description, d.city, d.country "
        "FROM listings l JOIN destinations d ON l.destination_id = d.id"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " LIMIT ?"
    args.append(int(limit))

    with database.connect() as conn:
        return [_row_to_dict(r) for r in conn.execute(sql, args)]


# ── RAG semantic search ───────────────────────────────────────────────────────

def semantic_search(
    query: str,
    top_k: int = RAG_TOP_K,
    city: str | None = None,
    state: str | None = None,
    country: str | None = None,
    kind: str | None = None,
    section: str | None = None,
    type: str | None = None,
) -> list[dict]:
    from rag.embedder import embed_texts
    from rag.vector_store import query_similar
    where: dict[str, str] = {}
    if city:
        where["city"] = city
    if state:
        where["state"] = state
    if country:
        where["country"] = country
    if kind:
        where["kind"] = kind
    if section:
        where["section"] = section
    if type:
        where["type"] = type
    query_vec = embed_texts([query])[0]
    return query_similar(
        query_vec,
        query_text=query,
        top_k=top_k,
        where=where or None,
    )


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOLS: dict = {
    "search_destinations": {
        "fn": search_destinations,
        "description": (
            "STRUCTURED SQL lookup over the `destinations` table. Use for "
            "list-style queries with hard filters: 'cities in Spain', "
            "'national parks in California', 'beach destinations', etc. "
            "Filters: `country` (e.g. 'USA', 'Spain'), `state` (2-letter US "
            "code), `kind` ('city'|'park'|'district'|'itinerary'), "
            "`travel_type` ('city'|'beach'|'nature'), `name_contains` (substring of city name), "
            "`limit` (default 20). Returns slug, city, state, country, kind, "
            "travel_type, description. "
            "Pick this tool when the user wants a LIST of destinations matching "
            "structured criteria; pick `semantic_search` for free-text questions."
        ),
    },
    "search_listings": {
        "fn": search_listings,
        "description": (
            "STRUCTURED SQL lookup over the `listings` table — individual "
            "See/Do/Eat/Drink/Sleep/Buy entries extracted from Wikivoyage. "
            "Use for queries like 'restaurants in San Francisco', "
            "'hotels in Tokyo', 'museums in London', 'bars in the Mission'. "
            "Filters: `city` (e.g. 'San Francisco'), `country`, `category` "
            "(one of 'See','Do','Eat','Drink','Sleep','Buy'), `name_contains` "
            "(substring of listing name), `limit` (default 15). Returns name, "
            "address, phone, hours, price, description, city, country. "
            "Pick this tool when the user wants specific, named places (with "
            "address / hours / price); pick `semantic_search` for narrative "
            "context about a city or area."
        ),
    },
    "semantic_search": {
        "fn": semantic_search,
        "description": (
            "Search the travel knowledge base for relevant context about destinations, "
            "hotels, restaurants, attractions, districts, and itineraries. This is the primary "
            "tool — use it for any question about a place, what to do/see/eat there, where to "
            "stay, or how to plan a trip. "
            "Optional filter kwargs narrow the search: "
            "`city` (e.g. 'San Francisco'), `state` (2-letter US code, e.g. 'CA'), "
            "`country` (e.g. 'USA'), "
            "`kind` ('city'|'park'|'district'|'itinerary') to restrict the destination type, "
            "`section` (one of 'See', 'Do', 'Eat', 'Drink', 'Sleep', 'Buy', 'Understand', "
            "'GetIn', 'GetAround', 'StaySafe', 'Connect', 'Districts'), "
            "and `type` ('guide' for cities/parks/districts, 'itinerary' for road trips). "
            "Always include filters when the user names a specific place or asks about a "
            "specific category — e.g. semantic_search(query='best ramen', city='San Francisco', section='Eat'). "
            "For park-wide recommendations across multiple parks, prefer `kind='park'` over a broad state-only query."
        ),
    },
    "get_weather": {
        "fn": get_weather,
        "description": (
            "LIVE: Get current weather and a 3-day forecast for a city. Days are "
            "labelled 'today', 'tomorrow', 'day_after_tomorrow' so you can answer "
            "date-relative questions ('what's the weather tomorrow') directly. "
            "Use whenever the user asks about weather, climate-right-now, or "
            "what to pack for a near-term trip."
        ),
    },
    "get_visa_info": {
        "fn": get_visa_info,
        "description": (
            "LIVE: Returns the destination country's entry-requirements section "
            "from the UK Foreign Office (updated daily). Pass the user's "
            "`nationality` (e.g. 'US', 'India', 'UK') and the destination "
            "`destination_country` (e.g. 'Japan', 'Spain'). The response is "
            "anchored on UK rules — surface its `important_note` so the user "
            "verifies with their own embassy."
        ),
    },
    "get_travel_advisory": {
        "fn": get_travel_advisory,
        "description": (
            "LIVE: Returns the UK Foreign Office travel advisory for a country "
            "(updated daily) — Summary, Warnings & insurance, Safety & security. "
            "Use when the user asks about safety, warnings, advisories, 'is X "
            "safe right now', or unrest in a destination."
        ),
    },
}

TOOL_DESCRIPTIONS: str = "\n".join(
    f"- {name}: {info['description']}" for name, info in TOOLS.items()
)
