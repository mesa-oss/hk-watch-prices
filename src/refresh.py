"""Load WhatsApp export(s) into the SQLite database.

Two markets are supported: HK (default, existing behavior) and EU (Reuven
group). Each has its own DB file and its own exports directory.

Usage:
    python src/refresh.py                        # HK: parse all exports/*.txt
    python src/refresh.py --market eu            # EU: parse all exports/eu/*.txt
    python src/refresh.py path/to/file           # parse one specific file (into HK)
    python src/refresh.py --market eu path/…     # parse one file into EU db
    python src/refresh.py --force                # reparse exports already loaded
    python src/refresh.py --llm                  # run LLM fallback on unparsed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from parser import parse_export
from db import (
    connect, insert_listings, mark_export_loaded, is_export_loaded,
    dedup_repeated_listings, vacuum, stats,
)
from paths import db_path, exports_dir, MARKETS, USD_MARKETS


def load_export(conn, path: Path, *, force: bool, use_llm: bool,
                dollar_is_usd: bool = False) -> int:
    if not force and is_export_loaded(conn, path.name):
        print(f"  · {path.name}: already loaded (use --force to reparse)")
        return 0

    result = parse_export(path, dollar_is_usd=dollar_is_usd)
    print(f"  · {path.name}: parsed {len(result.listings)} listings, "
          f"{len(result.unparsed)} unparsed candidates")

    if use_llm and result.unparsed:
        try:
            from llm_extract import extract_with_llm
            extra = extract_with_llm(result.unparsed, source_file=path.name)
            print(f"  · {path.name}: LLM added {len(extra)} listings")
            result.listings.extend(extra)
        except Exception as e:
            print(f"  · {path.name}: LLM fallback skipped ({e})")

    inserted = insert_listings(conn, result.listings)
    mark_export_loaded(conn, path.name, inserted)
    print(f"  · {path.name}: inserted {inserted} new rows (deduped against existing)")
    return inserted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", type=Path, help="Specific export file(s) to load")
    ap.add_argument("--market", choices=MARKETS, default="hk",
                    help="Which market DB to load into (default: hk)")
    ap.add_argument("--force", action="store_true", help="Reload exports already marked as loaded")
    ap.add_argument("--llm", action="store_true", help="Use Claude API to recover unparsed lines")
    args = ap.parse_args()

    db_file = db_path(args.market)
    exports = exports_dir(args.market)

    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_file)

    if args.paths:
        files = args.paths
    else:
        files = sorted(exports.glob("*.txt"))
        if not files:
            print(f"No .txt files found in {exports}")
            sys.exit(1)

    dollar_is_usd = args.market in USD_MARKETS
    print(f"Market:   {args.market.upper()}")
    print(f"Database: {db_file}")
    print(f"Loading {len(files)} file(s)... ($ = {'USD' if dollar_is_usd else 'HKD'})")
    total = 0
    for f in files:
        total += load_export(conn, f, force=args.force, use_llm=args.llm,
                             dollar_is_usd=dollar_is_usd)

    print()
    print(f"Done. Inserted {total} new rows total.")

    # Collapse repeated listings — dealers cross-post identical stock lines
    # every few hours. We keep the latest row per (seller + structured
    # listing fields) tuple.
    before, after = dedup_repeated_listings(conn)
    if before != after:
        print(f"Dedup removed {before - after:,} repeated listings ({before:,} → {after:,}).")
    # Reclaim space from deleted rows — otherwise the .db file keeps
    # growing on every refresh even though row count goes down.
    vacuum(conn)
    print()
    s = stats(conn)
    print(f"DB now has {s['total_listings']} listings, "
          f"{s['unique_references']} unique references")
    print(f"Date range: {s['date_range'][0]} → {s['date_range'][1]}")
    print("By brand:")
    for brand, c in s["by_brand"][:15]:
        print(f"  {brand:30s} {c:>6}")


if __name__ == "__main__":
    main()
