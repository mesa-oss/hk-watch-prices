"""One-off: repair HK prices in place, then load new exports in parallel.

Steps (all on --db, a copy of data/watches.db):
  1. Re-price every existing row from its own raw_line with the current
     parser. Rows keep their id/date/seller; only prices change. Rows whose
     line no longer yields any price (e.g. '18k gold' read as HKD 18,000)
     are removed and listed in the report.
  2. Blank raw_message (unused, half the file size).
  3. Parse the given export files in a process pool, insert each as it
     finishes (INSERT OR IGNORE on posted_at+seller+raw_line), dedup after
     each so the table never balloons.

Usage:
  python3 tools/rebuild_hk.py --db /tmp/work.db --report /tmp/report.txt FILE...
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from parser import extract_price, parse_export  # noqa: E402
from db import (connect, insert_listings, mark_export_loaded,  # noqa: E402
                dedup_repeated_listings, fix_price_scale)


def repair(conn, report) -> None:
    rows = conn.execute(
        "SELECT id, reference, raw_line, price_hkd, price_usdt, price_eur FROM listings"
    ).fetchall()
    updates, deletes = [], []
    for r in rows:
        line = r["raw_line"]
        if r["reference"]:
            line = re.sub(re.escape(r["reference"]), " " * len(r["reference"]), line, flags=re.I)
        h, u, e, _ = extract_price(line)
        old = (r["price_hkd"], r["price_usdt"], r["price_eur"])
        if (h, u, e) == old:
            continue
        if h is None and u is None and e is None:
            deletes.append((r["id"], old, r["raw_line"]))
        else:
            updates.append((h, u, e, r["id"], old, r["raw_line"]))
    conn.executemany(
        "UPDATE listings SET price_hkd=?, price_usdt=?, price_eur=? WHERE id=?",
        [(h, u, e, i) for h, u, e, i, _, _ in updates],
    )
    conn.executemany("DELETE FROM listings WHERE id=?", [(i,) for i, _, _ in deletes])
    conn.commit()
    report.write(f"REPAIR: {len(rows)} rows checked, {len(updates)} re-priced, "
                 f"{len(deletes)} removed (no valid price)\n")
    report.write("\n-- re-priced (old hkd/usdt/eur -> new) --\n")
    for h, u, e, _i, old, line in updates:
        report.write(f"{old} -> {(h, u, e)} | {line[:150]}\n")
    report.write("\n-- removed --\n")
    for _i, old, line in deletes:
        report.write(f"{old} | {line[:150]}\n")
    print(f"repair: {len(updates)} re-priced, {len(deletes)} removed", flush=True)


def _parse(path: str):
    res = parse_export(Path(path))
    return path, res.listings, len(res.unparsed)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--skip-repair", action="store_true")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args()

    conn = connect(args.db)
    with args.report.open("w") as report:
        if not args.skip_repair:
            repair(conn, report)
            conn.execute("UPDATE listings SET raw_message='' WHERE raw_message != ''")
            conn.commit()

        t0 = time.time()
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(_parse, f) for f in args.files]
            for fut in as_completed(futs):
                path, listings, n_unparsed = fut.result()
                inserted = insert_listings(conn, listings)
                mark_export_loaded(conn, Path(path).name, inserted)
                before, after = dedup_repeated_listings(conn)
                msg = (f"{Path(path).name}: {len(listings)} parsed, {n_unparsed} unparsed, "
                       f"{inserted} inserted, dedup {before}->{after}  "
                       f"[{(time.time() - t0) / 60:.1f} min]")
                print(msg, flush=True)
                report.write(msg + "\n")
                report.flush()
        fx = fix_price_scale(conn)
        before, after = dedup_repeated_listings(conn)
        msg = (f"SCALE FIX: {fx['rescaled']} rescaled, {fx['removed']} removed (<HKD 5k); "
               f"dedup {before}->{after}")
        print(msg, flush=True)
        report.write("\n" + msg + "\n")
        for ref, med, v, nv in fx["examples"]:
            report.write(f"  {ref:<16} median {med:>12,.0f}  {v:>14,.0f} -> {nv:>12,.0f}\n")
    conn.execute("VACUUM")
    conn.close()


if __name__ == "__main__":
    main()
