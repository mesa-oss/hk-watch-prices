"""Query the watch price database from the CLI.

Examples:
    python src/query.py --ref 5167R
    python src/query.py --ref 5167 --condition new
    python src/query.py --brand "Patek Philippe" --year 2022
    python src/query.py --ref 26240OR --color blue --since 2026-05-01
    python src/query.py --stats                          # overall counts
    python src/query.py --top 20                         # most-listed refs
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

from db import connect, stats

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "watches.db"


def fmt_price(hkd: int | None, usdt: int | None) -> str:
    parts = []
    if hkd:
        parts.append(f"HKD {hkd:>10,}")
    if usdt:
        parts.append(f"USDT {usdt:>8,}")
    return " | ".join(parts) if parts else "—"


def main():
    ap = argparse.ArgumentParser(description="Query watch prices")
    ap.add_argument("--ref", help="Reference number (partial match, case insensitive)")
    ap.add_argument("--brand", help="Brand name (partial match)")
    ap.add_argument("--color", help="Dial color (partial match)")
    ap.add_argument("--year", type=int, help="Year made")
    ap.add_argument("--year-min", type=int, help="Minimum year made")
    ap.add_argument("--year-max", type=int, help="Maximum year made")
    ap.add_argument("--condition", choices=["new", "used"], help="Condition")
    ap.add_argument("--full-set", choices=["yes", "no"], help="Filter by full-set status")
    ap.add_argument("--seller", help="Seller name (partial)")
    ap.add_argument("--since", help="Posted on/after YYYY-MM-DD")
    ap.add_argument("--until", help="Posted on/before YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=50, help="Max rows to show")
    ap.add_argument("--all-columns", action="store_true", help="Show every column")
    ap.add_argument("--summary", action="store_true",
                    help="Show min/median/max price for the matching rows")
    ap.add_argument("--stats", action="store_true", help="Show overall DB stats")
    ap.add_argument("--top", type=int, help="Show the N most-listed references")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}. Run `python src/refresh.py` first.")
        sys.exit(1)

    conn = connect(DB_PATH)

    if args.stats:
        s = stats(conn)
        print(f"Listings:           {s['total_listings']:>8}")
        print(f"Unique references:  {s['unique_references']:>8}")
        print(f"Date range:         {s['date_range'][0]}  →  {s['date_range'][1]}")
        print("By brand:")
        for brand, c in s["by_brand"]:
            print(f"  {brand:30s} {c:>6}")
        return

    if args.top:
        cur = conn.execute(
            "SELECT reference, brand, COUNT(*) c FROM listings "
            "GROUP BY reference, brand ORDER BY c DESC LIMIT ?",
            (args.top,),
        )
        for r in cur.fetchall():
            print(f"  {r['c']:>4}× {r['reference']:25s} ({r['brand'] or '?'})")
        return

    where = []
    params: list = []
    if args.ref:
        where.append("reference LIKE ? COLLATE NOCASE")
        params.append(f"%{args.ref}%")
    if args.brand:
        where.append("brand LIKE ?")
        params.append(f"%{args.brand}%")
    if args.color:
        where.append("dial_color LIKE ? COLLATE NOCASE")
        params.append(f"%{args.color}%")
    if args.year is not None:
        where.append("year_made = ?")
        params.append(args.year)
    if args.year_min is not None:
        where.append("year_made >= ?")
        params.append(args.year_min)
    if args.year_max is not None:
        where.append("year_made <= ?")
        params.append(args.year_max)
    if args.condition:
        where.append("condition = ?")
        params.append(args.condition)
    if args.full_set:
        where.append("full_set = ?")
        params.append(1 if args.full_set == "yes" else 0)
    if args.seller:
        where.append("seller LIKE ? COLLATE NOCASE")
        params.append(f"%{args.seller}%")
    if args.since:
        where.append("posted_at >= ?")
        params.append(args.since)
    if args.until:
        where.append("posted_at <= ? || 'T23:59:59'")
        params.append(args.until)

    sql = "SELECT * FROM listings"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY posted_at DESC"
    if not args.summary:
        sql += f" LIMIT {args.limit}"

    cur = conn.execute(sql, params)
    rows = cur.fetchall()

    if args.summary:
        hkds = [r["price_hkd"] for r in rows if r["price_hkd"]]
        usdts = [r["price_usdt"] for r in rows if r["price_usdt"]]
        print(f"Matched {len(rows)} listings")
        if hkds:
            print(f"  HKD : min {min(hkds):>10,}  "
                  f"median {int(statistics.median(hkds)):>10,}  "
                  f"max {max(hkds):>10,}  "
                  f"(n={len(hkds)})")
        if usdts:
            print(f"  USDT: min {min(usdts):>10,}  "
                  f"median {int(statistics.median(usdts)):>10,}  "
                  f"max {max(usdts):>10,}  "
                  f"(n={len(usdts)})")
        return

    if not rows:
        print("No matches.")
        return

    # Compact tabular output
    print(f"{'Posted':<19} {'Ref':<20} {'Cond':<5} {'Yr':<5} {'Color':<10} "
          f"{'Price':<32} {'Seller':<20}")
    print("-" * 120)
    for r in rows:
        cond = (r["condition"] or "")[:5]
        yr = str(r["year_made"]) if r["year_made"] else ""
        if r["month_made"]:
            yr = f"{yr}/{r['month_made']:02d}"
        color = (r["dial_color"] or "")[:10]
        seller = (r["seller"] or "")[:20]
        print(f"{r['posted_at'][:19]:<19} {r['reference']:<20} {cond:<5} "
              f"{yr:<5} {color:<10} {fmt_price(r['price_hkd'], r['price_usdt']):<32} {seller:<20}")
    print(f"\n({len(rows)} row{'s' if len(rows) != 1 else ''})")


if __name__ == "__main__":
    main()
