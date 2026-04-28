
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "data.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS destinations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT    NOT NULL UNIQUE,
    city         TEXT    NOT NULL,
    state        TEXT,                     -- 2-letter US code or NULL
    country      TEXT,
    kind         TEXT    NOT NULL,         -- city / park / district / itinerary
    travel_type  TEXT,                     -- city / beach / nature
    parent_slug  TEXT,                     -- parent city slug for districts
    description  TEXT,                     -- first ~300 chars of intro
    n_chunks     INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_destinations_city    ON destinations(city);
CREATE INDEX IF NOT EXISTS idx_destinations_state   ON destinations(state);
CREATE INDEX IF NOT EXISTS idx_destinations_country ON destinations(country);
CREATE INDEX IF NOT EXISTS idx_destinations_kind    ON destinations(kind);

CREATE TABLE IF NOT EXISTS listings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    destination_id  INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    category        TEXT    NOT NULL,      -- See / Do / Eat / Drink / Sleep / Buy
    name            TEXT    NOT NULL,
    address         TEXT,
    phone           TEXT,
    hours           TEXT,
    price           TEXT,
    description     TEXT,
    source_chunk_id TEXT,
    UNIQUE(destination_id, category, name)
);

CREATE INDEX IF NOT EXISTS idx_listings_destination ON listings(destination_id);
CREATE INDEX IF NOT EXISTS idx_listings_category    ON listings(category);
CREATE INDEX IF NOT EXISTS idx_listings_name        ON listings(name);
"""


@contextmanager
def connect(db_path: str | Path = DB_PATH):
    """Yield a sqlite3 connection with foreign keys + row factory enabled."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_schema(db_path: str | Path = DB_PATH) -> None:
    """Create tables if they don't exist. Safe to call repeatedly."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def reset(db_path: str | Path = DB_PATH) -> None:
    """Drop and recreate all tables — used by the build script."""
    with connect(db_path) as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS listings;
            DROP TABLE IF EXISTS destinations;
        """)
        conn.executescript(SCHEMA)


def upsert_destination(conn: sqlite3.Connection, row: dict) -> int:
    """Insert or update a destination by slug. Returns the destination id."""
    conn.execute(
        """
        INSERT INTO destinations
            (slug, city, state, country, kind, travel_type, parent_slug, description, n_chunks)
        VALUES
            (:slug, :city, :state, :country, :kind, :travel_type, :parent_slug, :description, :n_chunks)
        ON CONFLICT(slug) DO UPDATE SET
            city = excluded.city,
            state = excluded.state,
            country = excluded.country,
            kind = excluded.kind,
            travel_type = excluded.travel_type,
            parent_slug = excluded.parent_slug,
            description = excluded.description,
            n_chunks = excluded.n_chunks
        """,
        row,
    )
    cur = conn.execute("SELECT id FROM destinations WHERE slug = ?", (row["slug"],))
    return cur.fetchone()["id"]


def upsert_listing(conn: sqlite3.Connection, row: dict) -> None:
    """Insert a listing; ignore if (destination_id, category, name) already exists."""
    conn.execute(
        """
        INSERT OR IGNORE INTO listings
            (destination_id, category, name, address, phone, hours, price, description, source_chunk_id)
        VALUES
            (:destination_id, :category, :name, :address, :phone, :hours, :price, :description, :source_chunk_id)
        """,
        row,
    )


def stats(db_path: str | Path = DB_PATH) -> dict:
    with connect(db_path) as conn:
        d = conn.execute("SELECT COUNT(*) AS n FROM destinations").fetchone()["n"]
        l = conn.execute("SELECT COUNT(*) AS n FROM listings").fetchone()["n"]
        by_cat = {
            r["category"]: r["n"]
            for r in conn.execute(
                "SELECT category, COUNT(*) AS n FROM listings GROUP BY category ORDER BY n DESC"
            )
        }
        by_kind = {
            r["kind"]: r["n"]
            for r in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM destinations GROUP BY kind ORDER BY n DESC"
            )
        }
    return {"destinations": d, "listings": l,
            "destinations_by_kind": by_kind,
            "listings_by_category": by_cat}
