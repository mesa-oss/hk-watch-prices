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
    metal TEXT,
    nickname TEXT,
    price_eur INTEGER,
    seller_phone TEXT,
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
        source_file, confidence, clean_line, dial_details, metal, nickname,
        price_eur, seller_phone
    ) VALUES (
        :posted_at, :seller, :brand, :reference, :dial_color, :year_made, :month_made,
        :condition, :price_hkd, :price_usdt, :full_set, :raw_line, :raw_message,
        :source_file, :confidence, :clean_line, :dial_details, :metal, :nickname,
        :price_eur, :seller_phone
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


def vacuum(conn: sqlite3.Connection) -> None:
    """Reclaim space freed by DELETEs. SQLite doesn't shrink the file
    automatically; after a dedup pass the file can carry ~70% empty pages.
    Required before committing the .db to a Git repo with a size limit.
    """
    conn.execute("VACUUM")
    conn.commit()


def dedup_repeated_listings(conn: sqlite3.Connection) -> tuple[int, int]:
    """Collapse identical listings re-posted by the same seller.

    Dealers (e.g. Lisa Watch) re-post the same stock list every few hours.
    When the seller, reference, dial color, dial details, year, month,
    condition, full-set flag, and all prices match, only the row with the
    latest posted_at is kept (the same post can arrive from several groups
    or exports, so insertion order says nothing about recency).

    Returns (rows_before, rows_after).
    """
    before = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    conn.execute(
        """
        DELETE FROM listings
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY
                        seller,
                        COALESCE(reference, ''),
                        COALESCE(dial_color, ''),
                        COALESCE(dial_details, ''),
                        COALESCE(year_made, 0),
                        COALESCE(month_made, 0),
                        COALESCE(condition, ''),
                        COALESCE(full_set, -1),
                        COALESCE(price_hkd, 0),
                        COALESCE(price_usdt, 0),
                        COALESCE(price_eur, 0)
                    ORDER BY posted_at DESC, id DESC
                ) AS rn
                FROM listings
            ) WHERE rn > 1
        )
        """
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    return before, after


def fix_currency_labels(conn: sqlite3.Connection, *, min_peers: int = 5) -> dict:
    """Fix HKD/USD mislabels using each reference's HKD market price.

    Some dealers write 'USDT 91,000' for a 126300 that trades at HKD 91k
    (HKD price, wrong label); others write 'HKD 445k' or '$455k' for a watch
    quoted in dollars. Read as labelled, these sit ~7.8x off the market. A
    USDT-only price that matches the HKD median (0.7–1.4x) is moved to HKD; an
    HKD-only price ~7.8x below it that matches once read as USD is moved to USD.
    """
    import statistics
    from collections import defaultdict

    hkd_by_ref = defaultdict(list)
    rows = conn.execute(
        "SELECT id, UPPER(reference), price_hkd, price_usdt, price_eur FROM listings"
    ).fetchall()
    for _id, ref, h, u, e in rows:
        if h and not u:
            hkd_by_ref[ref].append(h)
    med = {r: statistics.median(v) for r, v in hkd_by_ref.items() if len(v) >= min_peers}
    to_hkd, to_usd = [], []
    for id_, ref, h, u, e in rows:
        m = med.get(ref)
        if not m or e:
            continue
        if u and not h and 0.7 <= u / m <= 1.4 and u * 7.8 / m > 3:
            to_hkd.append((u, id_))
        elif h and not u and h / m < 0.2 and 0.75 <= h * 7.8 / m <= 1.33:
            to_usd.append((h, id_))
    conn.executemany("UPDATE listings SET price_hkd=?, price_usdt=NULL, "
                     "confidence='ccy-fixed' WHERE id=?", to_hkd)
    conn.executemany("UPDATE listings SET price_usdt=?, price_hkd=NULL, "
                     "confidence='ccy-fixed' WHERE id=?", to_usd)
    conn.commit()
    return {"usdt_to_hkd": len(to_hkd), "hkd_to_usd": len(to_usd)}


def fix_price_scale(conn: sqlite3.Connection, *, min_peers: int = 5) -> dict:
    """Correct decimal/scale slips using each reference's own market price.

    HK dealers write the same amount many ways ('HKD 9.5k' = 95k for a steel
    Rolex, 'HKD 2.069k' = 2.07M for a Patek, 'HKD 155,000' typed for 1.55M).
    Text alone can't tell which, but the other listings of that reference can:
    a listing ~10x / 100x / 1000x BELOW its reference median that lands within
    0.6–1.6x of it once scaled up is a decimal slip and is rescaled. Prices
    above the median are never touched (gem-set/Tiffany variants share refs). Listings under HKD 5,000-equivalent that can't be
    rescaled are removed: no watch in these groups trades that low.
    """
    import statistics
    from collections import defaultdict

    usdt_hkd, eur_hkd = 7.8, 8.5
    by_ref = defaultdict(list)
    for id_, ref, h, u, e in conn.execute(
        "SELECT id, UPPER(reference), price_hkd, price_usdt, price_eur FROM listings"
    ):
        v = h or (u * usdt_hkd if u else None) or (e * eur_hkd if e else None)
        if v:
            by_ref[ref].append((id_, v, h, u, e))

    fixes, drops, examples = [], [], []
    for ref, items in by_ref.items():
        med = statistics.median(v for _, v, *_ in items) if len(items) >= min_peers else None
        for id_, v, h, u, e in items:
            # Only too-LOW prices are rescaled. A fake-cheap HK price becomes
            # the "cheapest same-spec" and hides real deals; a too-high one is
            # ignored by min() anyway, and is often a genuine gem-set/Tiffany
            # variant sharing the base reference — so those stay untouched.
            if med and v / med < 0.25:
                for k in (1, 2, 3):
                    f = 10 ** k
                    if 0.6 <= v * f / med <= 1.6:
                        fixes.append((h and round(h * f), u and round(u * f),
                                      e and round(e * f), id_))
                        if len(examples) < 40:
                            examples.append((ref, med, v, v * f))
                        v *= f
                        break
            if v < 5000 or (med and v / med < 0.05):
                # under HKD 5k, or 20x+ below its reference with no decimal
                # explanation ('hkd 8k' for a 418k 5205R): never a real offer
                drops.append((id_,))
    conn.executemany(
        "UPDATE listings SET price_hkd=?, price_usdt=?, price_eur=?, "
        "confidence='scale-fixed' WHERE id=?", fixes)
    conn.executemany("DELETE FROM listings WHERE id=?", drops)
    conn.commit()
    return {"rescaled": len(fixes), "removed": len(drops), "examples": examples}


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
