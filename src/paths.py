"""Central resolver for market-specific DB and export paths.

Two markets are supported: 'hk' (Hong Kong dealer group — the original) and
'eu' (Reuven European dealer group). Each has its own SQLite file and its
own exports subdirectory so the two datasets never mix.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MARKETS = ("hk", "eu")


def db_path(market: str) -> Path:
    market = market.lower()
    if market == "hk":
        # Original file — kept at data/watches.db so existing Streamlit
        # deployment doesn't need a file move.
        return ROOT / "data" / "watches.db"
    if market == "eu":
        return ROOT / "data" / "watches_eu.db"
    raise ValueError(f"Unknown market {market!r}. Valid: {MARKETS}")


def exports_dir(market: str) -> Path:
    market = market.lower()
    if market == "hk":
        return ROOT / "exports"
    if market == "eu":
        return ROOT / "exports" / "eu"
    raise ValueError(f"Unknown market {market!r}. Valid: {MARKETS}")
