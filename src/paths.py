"""Central resolver for market-specific DB and export paths.

Two markets are supported: 'hk' (Hong Kong dealer group — the original) and
'eu' (Reuven European dealer group). Each has its own SQLite file and its
own exports subdirectory so the two datasets never mix.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MARKETS = ("hk", "eu", "wdg", "usmoda")

# Markets whose native currency is USD (they use $ = USD, not HKD).
# The parser routes '$' and bare 'k'/'m' amounts to price_usdt (USD-equivalent)
# for these markets instead of the default HKD.
# WDG is European but its dealers write '$' meaning USD, not HKD — same as
# US Moda. HK is the only market where '$' actually means HKD.
USD_MARKETS = {"usmoda", "wdg"}


_UNPACKED_ELSEWHERE: dict[str, Path] = {}


def db_path(market: str) -> Path:
    market = market.lower()
    if market in _UNPACKED_ELSEWHERE:
        return _UNPACKED_ELSEWHERE[market]
    if market == "hk":
        return ROOT / "data" / "watches.db"
    if market == "eu":
        return ROOT / "data" / "watches_eu.db"
    if market == "wdg":
        return ROOT / "data" / "watches_wdg.db"
    if market == "usmoda":
        return ROOT / "data" / "watches_usmoda.db"
    raise ValueError(f"Unknown market {market!r}. Valid: {MARKETS}")


def packed_path(market: str) -> Path:
    """xz-compressed copy of the DB that gets committed. The HK DB is far
    over GitHub's 100 MB file limit uncompressed; the raw .db is gitignored."""
    return db_path(market).with_suffix(".db.xz")


def ensure_unpacked(market: str) -> Path:
    """Decompress the committed .db.xz when the local .db is missing or older
    (fresh Streamlit Cloud checkout, or a newer commit was pulled)."""
    import lzma
    import os
    import shutil
    import tempfile

    db, packed = db_path(market), packed_path(market)
    if packed.exists() and (not db.exists() or db.stat().st_mtime < packed.stat().st_mtime):
        try:
            fd, tmp = tempfile.mkstemp(dir=db.parent, suffix=".unpacking")
        except OSError:  # read-only checkout: unpack into the temp dir instead
            db = Path(tempfile.gettempdir()) / db.name
            _UNPACKED_ELSEWHERE[market.lower()] = db
            if db.exists() and db.stat().st_mtime >= packed.stat().st_mtime:
                return db
            fd, tmp = tempfile.mkstemp(dir=db.parent, suffix=".unpacking")
        with os.fdopen(fd, "wb") as out, lzma.open(packed, "rb") as src:
            shutil.copyfileobj(src, out, length=1 << 20)
        os.replace(tmp, db)
    return db


def pack(market: str) -> Path:
    """Write the committed .db.xz from the local .db."""
    import lzma
    import os
    import shutil

    db, packed = db_path(market), packed_path(market)
    tmp = packed.with_suffix(".xz.tmp")
    with db.open("rb") as src, lzma.open(tmp, "wb", preset=6) as out:
        shutil.copyfileobj(src, out, length=1 << 20)
    os.replace(tmp, packed)
    os.utime(db)  # keep the working .db newer than its packed copy
    return packed


def exports_dir(market: str) -> Path:
    market = market.lower()
    if market == "hk":
        return ROOT / "exports"
    if market == "eu":
        return ROOT / "exports" / "eu"
    if market == "wdg":
        return ROOT / "exports" / "wdg"
    if market == "usmoda":
        return ROOT / "exports" / "usmoda"
    raise ValueError(f"Unknown market {market!r}. Valid: {MARKETS}")
