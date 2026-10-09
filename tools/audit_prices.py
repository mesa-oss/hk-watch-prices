"""Price sanity audit for a market DB.

  python3 tools/audit_prices.py data/watches.db

1. Lines quoting both HKD and USDT: the ratio must be ~7.8. Anything far
   off means one side was mis-read (decimal/thousands confusion).
2. Per-reference outliers: each listing vs the median HKD-equivalent price
   of the same reference (refs with >= 5 listings); flags >3x or <1/3.
"""
import sqlite3
import statistics
import sys
from collections import defaultdict

USDT_HKD = 7.8
EUR_HKD = 8.5


def hkd_equiv(h, u, e):
    if h:
        return h
    if u:
        return u * USDT_HKD
    if e:
        return e * EUR_HKD
    return None


def main(path: str) -> None:
    conn = sqlite3.connect(path)
    n = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    print(f"{path}: {n:,} listings")

    both = conn.execute(
        "SELECT price_hkd, price_usdt, raw_line FROM listings "
        "WHERE price_hkd IS NOT NULL AND price_usdt IS NOT NULL"
    ).fetchall()
    bad = [(h, u, l) for h, u, l in both if not 6.0 <= h / u <= 9.5]
    print(f"\n[1] HKD+USDT on same line: {len(both):,}  ratio outside 6.0–9.5: {len(bad):,}")
    for h, u, l in bad[:25]:
        print(f"    hkd={h:>10,} usdt={u:>9,} ratio={h / u:6.2f} | {l[:110]}")

    rows = conn.execute(
        "SELECT reference, price_hkd, price_usdt, price_eur, raw_line FROM listings"
    ).fetchall()
    by_ref = defaultdict(list)
    for ref, h, u, e, line in rows:
        v = hkd_equiv(h, u, e)
        if v:
            by_ref[(ref or "").upper()].append((v, h, u, e, line))
    flagged = []
    checked = 0
    for ref, items in by_ref.items():
        if len(items) < 5:
            continue
        checked += len(items)
        med = statistics.median(v for v, *_ in items)
        for v, h, u, e, line in items:
            if v > 3 * med or v < med / 3:
                flagged.append((v / med, ref, med, h, u, e, line))
    flagged.sort(key=lambda x: -max(x[0], 1 / x[0]))
    print(f"\n[2] Per-ref outliers: {len(flagged):,} of {checked:,} listings "
          f"({100 * len(flagged) / max(checked, 1):.2f}%) are >3x or <1/3 of their ref median")
    for r, ref, med, h, u, e, line in flagged[:40]:
        print(f"    x{r:7.2f} {ref:<14} median {med:>12,.0f} | hkd={h} usdt={u} eur={e} | {line[:90]}")


if __name__ == "__main__":
    main(sys.argv[1])
