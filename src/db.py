"""SQLite database layer for the watch price log."""

from __future__ import annotations

import math
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


def _ref_medians(rows, value, *, min_sellers: int = 5) -> dict:
    """Market price per reference: median of per-dealer medians, so one dealer
    re-posting the same typo can't outvote the market. Needs >= min_sellers."""
    import statistics
    from collections import defaultdict

    by = defaultdict(lambda: defaultdict(list))
    for row in rows:
        v = value(row)
        if v:
            by[row["ref"]][row["seller"]].append(v)
    return {
        ref: statistics.median(statistics.median(v) for v in sellers.values())
        for ref, sellers in by.items() if len(sellers) >= min_sellers
    }


def fix_currency_labels(conn: sqlite3.Connection) -> dict:
    """Fix HKD/USD mislabels using each reference's HKD market price.

    Some dealers write 'USDT 91,000' for a 126300 that trades at HKD 91k
    (HKD price, wrong label); others write 'HKD 445k' or '$455k' for a watch
    quoted in dollars. Read as labelled, these sit ~7.8x off the market. A
    USDT-only price that matches the HKD median (0.7–1.4x) is moved to HKD; an
    HKD-only price ~7.8x below it that matches once read as USD is moved to USD.
    The market price is the median of per-dealer medians (>= 5 dealers).
    """
    rows = conn.execute(
        "SELECT id, UPPER(reference) AS ref, seller, price_hkd AS h, price_usdt AS u, "
        "price_eur AS e FROM listings"
    ).fetchall()
    med = _ref_medians(rows, lambda r: r["h"] if r["h"] and not r["u"] else None)
    # References that trade in dollars: >= 5 dealers quote them explicitly in
    # USD/USDT at the same numbers the "HKD"/'$' listings show (5316/50P, RMs).
    # There the HKD median is really a dollar price, so a USDT quote matching
    # it is genuine USD — never relabel on these refs.
    # Dealers who habitually write "USDT" on HKD prices (Lily, Mina…): >= 20
    # USDT quotes, >= 40% of them sitting at the HKD market price.
    from collections import Counter
    looks_hkd, looks_usd = Counter(), Counter()
    for r in rows:
        m = med.get(r["ref"])
        if m and r["u"] and not r["h"]:
            if 0.7 <= r["u"] / m <= 1.4:
                looks_hkd[r["seller"]] += 1
            elif 0.7 <= r["u"] * 7.8 / m <= 1.4:
                looks_usd[r["seller"]] += 1
    mislabelers = {d for d in looks_hkd
                   if looks_hkd[d] + looks_usd[d] >= 20
                   and looks_hkd[d] / (looks_hkd[d] + looks_usd[d]) >= 0.4}
    usd_med = _ref_medians(rows, lambda r: r["u"] if r["u"] and not r["h"]
                           and r["seller"] not in mislabelers else None)
    dollar_refs = {ref for ref, m in med.items()
                   if ref in usd_med and 0.75 <= usd_med[ref] / m <= 1.33}
    to_hkd, to_usd = [], []
    for r in rows:
        id_, h, u, e = r["id"], r["h"], r["u"], r["e"]
        m = med.get(r["ref"])
        if not m or e or r["ref"] in dollar_refs:
            continue
        if u and not h and 0.7 <= u / m <= 1.4 and u * 7.8 / m > 3:
            to_hkd.append((u, id_))
        elif (h and not u and h / m < 0.2 and 0.75 <= h * 7.8 / m <= 1.33
              # ~1/10 of market could also be a dropped zero: take whichever
              # reading lands closer (the zero case is left to fix_price_scale)
              and abs(math.log(h * 7.8 / m)) < abs(math.log(h * 10 / m))):
            to_usd.append((h, id_))
    conn.executemany("UPDATE listings SET price_hkd=?, price_usdt=NULL, "
                     "confidence='ccy-fixed' WHERE id=?", to_hkd)
    conn.executemany("UPDATE listings SET price_usdt=?, price_hkd=NULL, "
                     "confidence='ccy-fixed' WHERE id=?", to_usd)
    conn.commit()
    return {"usdt_to_hkd": len(to_hkd), "hkd_to_usd": len(to_usd),
            "dollar_refs": dollar_refs, "mislabelers": mislabelers}


def fix_price_scale(conn: sqlite3.Connection) -> dict:
    """Correct decimal/scale slips using each reference's own market price.

    HK dealers write the same amount many ways ('HKD 9.5k' = 95k for a steel
    Rolex, 'HKD 2.069k' = 2.07M for a Patek, 'HKD 155,000' typed for 1.55M).
    Text alone can't tell which, but the other dealers' prices for that
    reference can: a listing ~10x / 100x / 1000x BELOW the reference median
    that lands within 0.6–1.6x of it once scaled up is a decimal slip and is
    rescaled. Prices above the median are never touched (gem-set/Tiffany
    variants share refs). Listings under HKD 5,000-equivalent, or 20x+ below
    the median with no decimal explanation, are removed: never a real offer.
    """
    usdt_hkd, eur_hkd = 7.8, 8.5
    rows = conn.execute(
        "SELECT id, UPPER(reference) AS ref, seller, price_hkd AS h, price_usdt AS u, "
        "price_eur AS e FROM listings"
    ).fetchall()

    def hkd_eq(r):
        return r["h"] or (r["u"] * usdt_hkd if r["u"] else None) or \
            (r["e"] * eur_hkd if r["e"] else None)

    med_by_ref = _ref_medians(rows, hkd_eq)
    fixes, drops, examples = [], [], []
    for r in rows:
        v = hkd_eq(r)
        if not v:
            continue
        h, u, e = r["h"], r["u"], r["e"]
        med = med_by_ref.get(r["ref"])
        # Only too-LOW prices are rescaled: a fake-cheap HK price becomes the
        # "cheapest same-spec" and hides real deals; a too-high one is ignored
        # by min() anyway and is often a genuine variant sharing the ref.
        if med and v / med < 0.25:
            for f in (10, 100, 1000):
                if 0.6 <= v * f / med <= 1.6:
                    fixes.append((h and round(h * f), u and round(u * f),
                                  e and round(e * f), r["id"]))
                    if len(examples) < 40:
                        examples.append((r["ref"], med, v, v * f))
                    v *= f
                    break
        if v < 5000 or (med and v / med < 0.05):
            drops.append((r["id"],))
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
