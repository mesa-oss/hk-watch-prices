"""SQLite database layer for the watch price log."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from parser import Listing


SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    posted_at TEXT NOT NULL,
    seller TEXT,
    brand TEXT,
    reference TEXT NOT NULL,
    dial_color TEXT,
    year_made INTEGER,
    month_made INTEGER,
    condition TEXT,
    price_hkd INTEGER,
    price_usdt INTEGER,
    full_set INTEGER,
    raw_line TEXT NOT NULL,
    raw_message TEXT,
    source_file TEXT,
    confidence TEXT,
    clean_line TEXT,
    dial_details TEXT,
    UNIQUE(posted_at, seller, raw_line)
);

CREATE INDEX IF NOT EXISTS idx_listings_reference ON listings(reference);
CREATE INDEX IF NOT EXISTS idx_listings_brand ON listings(brand);
CREATE INDEX IF NOT EXISTS idx_listings_posted_at ON listings(posted_at);
CREATE INDEX IF NOT EXISTS idx_listings_year ON listings(year_made);
CREATE INDEX IF NOT EXISTS idx_listings_condition ON listings(condition);

CREATE TABLE IF NOT EXISTS exports_loaded (
    source_file TEXT PRIMARY KEY,
    loaded_at TEXT NOT NULL,
    listing_count INTEGER NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert_listings(conn: sqlite3.Connection, listings: Iterable[Listing]) -> int:
    """Insert listings, skipping duplicates by (posted_at, seller, raw_line). Returns # inserted."""
    sql = """
    INSERT OR IGNORE INTO listings (
        posted_at, seller, brand, reference, dial_color, year_made, month_made,
        condition, price_hkd, price_usdt, full_set, raw_line, raw_message,
        source_file, confidence, clean_line, dial_details
    ) VALUES (
        :posted_at, :seller, :brand, :reference, :dial_color, :year_made, :month_made,
        :condition, :price_hkd, :price_usdt, :full_set, :raw_line, :raw_message,
        :source_file, :confidence, :clean_line, :dial_details
    )
    """
    rows = [asdict(l) for l in listings]
    # SQLite stores bool as int
    for r in rows:
        if r["full_set"] is not None:
            r["full_set"] = 1 if r["full_set"] else 0
    before = conn.total_changes
    conn.executemany(sql, rows)
    conn.commit()
    return conn.total_changes - before


def mark_export_loaded(conn: sqlite3.Connection, source_file: str, count: int) -> None:
    from datetime import datetime
    conn.execute(
        "INSERT OR REPLACE INTO exports_loaded (source_file, loaded_at, listing_count) VALUES (?, ?, ?)",
        (source_file, datetime.now().isoformat(), count),
    )
    conn.commit()


def is_export_loaded(conn: sqlite3.Connection, source_file: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM exports_loaded WHERE source_file = ?", (source_file,)
    )
    return cur.fetchone() is not None


def stats(conn: sqlite3.Connection) -> dict:
    cur = conn.execute("SELECT COUNT(*) FROM listings")
    total = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(DISTINCT reference) FROM listings")
    refs = cur.fetchone()[0]
    cur = conn.execute("SELECT brand, COUNT(*) c FROM listings GROUP BY brand ORDER BY c DESC")
    by_brand = [(r["brand"] or "(unknown)", r["c"]) for r in cur.fetchall()]
    cur = conn.execute("SELECT MIN(posted_at), MAX(posted_at) FROM listings")
    min_d, max_d = cur.fetchone()
    return {
        "total_listings": total,
        "unique_references": refs,
        "by_brand": by_brand,
        "date_range": (min_d, max_d),
    }
