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
USD_MARKETS = {"usmoda"}


def db_path(market: str) -> Path:
    market = market.lower()
    if market == "hk":
        return ROOT / "data" / "watches.db"
    if market == "eu":
        return ROOT / "data" / "watches_eu.db"
    if market == "wdg":
        return ROOT / "data" / "watches_wdg.db"
    if market == "usmoda":
        return ROOT / "data" / "watches_usmoda.db"
    raise ValueError(f"Unknown market {market!r}. Valid: {MARKETS}")


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
