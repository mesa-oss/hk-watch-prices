"""Export the listings table to CSV.

Usage:
    python src/export_csv.py                       # all listings → data/listings.csv
    python src/export_csv.py --out my.csv
    python src/export_csv.py --brand "Patek Philippe" --year 2022
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from db import connect

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "watches.db"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "listings.csv"


COLUMNS = [
    "posted_at", "seller", "brand", "reference", "dial_color",
    "year_made", "month_made", "condition", "full_set",
    "price_hkd", "price_usdt", "raw_line", "source_file",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--brand", help="Filter by brand (partial match)")
    ap.add_argument("--ref", help="Filter by reference (partial match)")
    ap.add_argument("--year", type=int)
    ap.add_argument("--condition", choices=["new", "used"])
    ap.add_argument("--since", help="YYYY-MM-DD")
    args = ap.parse_args()

    conn = connect(DB_PATH)

    where = []
    params: list = []
    if args.brand:
        where.append("brand LIKE ?")
        params.append(f"%{args.brand}%")
    if args.ref:
        where.append("reference LIKE ? COLLATE NOCASE")
        params.append(f"%{args.ref}%")
    if args.year is not None:
        where.append("year_made = ?")
        params.append(args.year)
    if args.condition:
        where.append("condition = ?")
        params.append(args.condition)
    if args.since:
        where.append("posted_at >= ?")
        params.append(args.since)

    sql = f"SELECT {', '.join(COLUMNS)} FROM listings"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY posted_at DESC, brand, reference"

    cur = conn.execute(sql, params)
    rows = cur.fetchall()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for r in rows:
            writer.writerow([r[c] for c in COLUMNS])

    print(f"Wrote {len(rows)} rows → {args.out}")


if __name__ == "__main__":
    main()
