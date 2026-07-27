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
from paths import db_path, MARKETS

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data"


COLUMNS = [
    "posted_at", "seller", "brand", "reference", "dial_color",
    "year_made", "month_made", "year_label", "condition", "full_set",
    "price_hkd", "price_usdt", "clean_line", "raw_line", "source_file",
]


def _format_year_label(year, month):
    if month and year:
        return f"N{month}/{str(year)[-2:]}"
    if year:
        return str(year)
    if month:
        return f"N{month}"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=MARKETS, default="hk",
                    help="Which market to export (default: hk)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output CSV path (default: data/listings_<market>.csv)")
    ap.add_argument("--brand", help="Filter by brand (partial match)")
    ap.add_argument("--ref", help="Filter by reference (partial match)")
    ap.add_argument("--year", type=int)
    ap.add_argument("--condition", choices=["new", "used"])
    ap.add_argument("--since", help="YYYY-MM-DD")
    args = ap.parse_args()

    if args.out is None:
        # HK stays at data/listings.csv (backward compat with existing xlsx flow);
        # EU writes to data/listings_eu.csv.
        args.out = (DEFAULT_OUT_DIR / "listings.csv") if args.market == "hk" \
                   else (DEFAULT_OUT_DIR / f"listings_{args.market}.csv")

    conn = connect(db_path(args.market))

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

    # Note: year_label is computed in Python below, not stored in DB
    db_cols = [c for c in COLUMNS if c != "year_label"]
    sql = f"SELECT {', '.join(db_cols)} FROM listings"
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
            row = []
            for c in COLUMNS:
                if c == "year_label":
                    row.append(_format_year_label(r["year_made"], r["month_made"]))
                else:
                    row.append(r[c])
            writer.writerow(row)

    print(f"Wrote {len(rows)} rows → {args.out}")


if __name__ == "__main__":
    main()
