"""Streamlit web UI for the watch price databases.

Two tabs:
  📋 Prices          — browse a single market's listings (filter + sort)
  🔀 Compare markets — same watch across HK / EU / Europe / etc. in USD

Mobile-first: filters and sort live at the top of each tab, big touch
targets, no hidden sidebar.

Run with:
    streamlit run src/web.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Ensure src/ is importable when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import db_path  # noqa: E402

st.set_page_config(
    page_title="Watch Prices",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Trim default vertical padding; make form controls phone-friendly.
st.markdown(
    """
    <style>
      div.block-container { padding-top: 1rem; padding-bottom: 1rem; }
      div[data-baseweb="select"] > div, .stTextInput input,
      .stSelectbox > div, .stRadio > div, button[kind="secondary"] {
        min-height: 42px;
      }
      [data-testid="stMetricValue"] { font-size: 1.1rem; }
      [data-testid="stMetricLabel"] { font-size: 0.75rem; }
      div[role="radiogroup"] label { font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----- Market discovery -----
MARKETS_AVAILABLE = [m for m in ("hk", "eu", "wdg") if db_path(m).exists()]
if not MARKETS_AVAILABLE:
    st.error("No databases found. Run `python src/refresh.py` first.")
    st.stop()

MARKET_LABEL = {"hk": "🇭🇰 HK", "eu": "🇪🇺 EU (Reuven)", "wdg": "🇪🇺 WDG"}
# Short code used in Compare-tab column headers ("HK n", "EU min $", ...)
MARKET_SHORT = {"hk": "HK", "eu": "EU", "wdg": "WDG"}


# ----- Currency conversion (fixed rates; approximate) -----
# HKD → USD: ÷7.8       EUR → USD: ×1.08       USDT → USD: 1:1
FX_TO_USD = {"hkd": 1 / 7.8, "eur": 1.08, "usdt": 1.0}


def row_to_usd(price_hkd, price_usdt, price_eur) -> float | None:
    """Return the row's price converted to USD. Preference:
    HKD > EUR > USDT (arbitrary, but keeps the same currency's history
    consistent for comparison over time)."""
    if pd.notna(price_hkd):
        return float(price_hkd) * FX_TO_USD["hkd"]
    if pd.notna(price_eur):
        return float(price_eur) * FX_TO_USD["eur"]
    if pd.notna(price_usdt):
        return float(price_usdt) * FX_TO_USD["usdt"]
    return None


# ----- Formatting helpers (used by both tabs) -----
def fmt_year(y) -> str:
    return str(int(y)) if pd.notna(y) else ""


def fmt_month(m) -> str:
    return f"N{int(m)}" if pd.notna(m) else ""


def fmt_price(hkd, usdt, eur=None) -> str:
    """Pretty-print in whichever native currency the seller used."""
    if pd.notna(eur):
        v = float(eur)
        return f"{v/1_000_000:.2f}M €" if v >= 1_000_000 else f"{int(v/1_000):,}k €"
    if pd.notna(hkd):
        v = float(hkd)
        return f"{v/1_000_000:.2f}M" if v >= 1_000_000 else f"{int(v/1_000):,}k"
    if pd.notna(usdt):
        u = float(usdt)
        return f"{u/1_000_000:.2f}M ₮" if u >= 1_000_000 else f"{int(u/1_000):,}k ₮"
    return ""


def fmt_usd(x) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    if x >= 1_000_000:
        return f"${x/1_000_000:.2f}M"
    return f"${int(x/1_000):,}k"


def fmt_dial(color, details) -> str:
    parts = []
    if pd.notna(color) and color:
        parts.append(str(color))
    if pd.notna(details) and details:
        parts.append(str(details))
    return " · ".join(parts)


st.title("Watch Prices")


# ----- Cached DB helpers (shared across all market tabs) -----
@st.cache_data(ttl=60)
def load_distinct(col: str, market: str) -> list[str]:
    with sqlite3.connect(db_path(market)) as c:
        rows = c.execute(
            f"SELECT DISTINCT {col} FROM listings "
            f"WHERE {col} IS NOT NULL ORDER BY {col}"
        ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=60)
def overall_stats(market: str):
    with sqlite3.connect(db_path(market)) as c:
        total = c.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        refs = c.execute("SELECT COUNT(DISTINCT reference) FROM listings").fetchone()[0]
        min_d, max_d = c.execute(
            "SELECT MIN(posted_at), MAX(posted_at) FROM listings"
        ).fetchone()
    return total, refs, min_d, max_d


def render_market_view(market: str) -> None:
    """Render the full filter + table UX for one market. Called once per tab.

    Uses market-suffixed widget keys so filter state is independent between
    tabs — typing '5167' in HK doesn't affect what's shown in the EU tab.
    """
    total, n_refs, min_d, max_d = overall_stats(market)
    st.caption(
        f"{MARKET_LABEL.get(market, market.upper())} · {total:,} listings · "
        f"{n_refs:,} refs · {min_d[:10]} → {max_d[:10]}"
    )

    # Filters
    top1, top2 = st.columns([2, 1])
    with top1:
        ref = st.text_input(
            "Reference", "", placeholder="e.g. 5167, 26240OR, RM035",
            label_visibility="collapsed", key=f"ref_{market}",
        )
    with top2:
        sort_by = st.selectbox(
            "Sort",
            ["Newest", "Price ↑", "Price ↓", "Year ↓"],
            label_visibility="collapsed", key=f"sort_{market}",
        )

    with st.expander("More filters", expanded=False):
        f1, f2 = st.columns(2)
        brands = load_distinct("brand", market)
        brand = f1.selectbox("Brand", [""] + brands, key=f"brand_{market}")
        condition = f2.radio("Condition", ["any", "new", "used"],
                             horizontal=True, key=f"cond_{market}")

        f3, f4 = st.columns(2)
        color = f3.text_input("Color", "", placeholder="blue, salmon, ice blue",
                              key=f"color_{market}")
        details = f4.text_input("Details", "", placeholder="diamond, roman, pavé",
                                key=f"details_{market}")

        f5, f6 = st.columns(2)
        full_set = f5.radio("Full set", ["any", "yes", "no"],
                            horizontal=True, key=f"fs_{market}")
        seller = f6.text_input("Seller", "", key=f"seller_{market}")

        year_min, year_max = st.slider("Year made", 1990, 2030, (2010, 2026),
                                       key=f"year_{market}")

    # Build SQL
    where = ["1=1"]
    params: list = []
    if ref:
        where.append(
            "(reference LIKE ? COLLATE NOCASE "
            "OR nickname LIKE ? COLLATE NOCASE "
            "OR raw_line LIKE ? COLLATE NOCASE)"
        )
        needle = f"%{ref}%"
        params.extend([needle, needle, needle])
    if brand:
        where.append("brand = ?")
        params.append(brand)
    if color:
        where.append(
            "(dial_color LIKE ? COLLATE NOCASE "
            "OR dial_details LIKE ? COLLATE NOCASE "
            "OR raw_line LIKE ? COLLATE NOCASE)"
        )
        needle = f"%{color}%"
        params.extend([needle, needle, needle])
    if details:
        where.append(
            "(dial_details LIKE ? COLLATE NOCASE OR raw_line LIKE ? COLLATE NOCASE)"
        )
        needle = f"%{details}%"
        params.extend([needle, needle])
    where.append("(year_made IS NULL OR year_made BETWEEN ? AND ?)")
    params.extend([year_min, year_max])
    if condition != "any":
        where.append("condition = ?")
        params.append(condition)
    if full_set != "any":
        where.append("full_set = ?")
        params.append(1 if full_set == "yes" else 0)
    if seller:
        where.append("seller LIKE ? COLLATE NOCASE")
        params.append(f"%{seller}%")

    order_clause = {
        "Newest": "posted_at DESC",
        "Price ↑": "COALESCE(price_hkd, price_usdt*7.8, price_eur*8.4) ASC NULLS LAST",
        "Price ↓": "COALESCE(price_hkd, price_usdt*7.8, price_eur*8.4) DESC NULLS LAST",
        "Year ↓": "year_made DESC NULLS LAST, posted_at DESC",
    }[sort_by]

    sql = f"""
    SELECT posted_at, seller, seller_phone, brand, reference,
           dial_color, dial_details, metal, nickname,
           year_made, month_made, condition, full_set,
           price_hkd, price_usdt, price_eur, clean_line, raw_line
    FROM listings
    WHERE {' AND '.join(where)}
    ORDER BY {order_clause}
    LIMIT 1000
    """

    with sqlite3.connect(db_path(market)) as conn:
        df = pd.read_sql_query(sql, conn, params=params)

    if not len(df):
        st.info("No matches. Try a different reference or open 'More filters' to widen.")
        return

    def _fmt_ref(row):
        r = row["reference"]
        n = row["nickname"]
        return f"{r} ({n})" if isinstance(n, str) and n else r

    df["Ref"] = df.apply(_fmt_ref, axis=1)
    df["Year"] = df["year_made"].apply(fmt_year)
    df["N"] = df["month_made"].apply(fmt_month)
    df["Metal"] = df["metal"].fillna("")
    df["Dial"] = df.apply(lambda r: fmt_dial(r["dial_color"], r["dial_details"]), axis=1)
    df["Description"] = df["raw_line"].fillna("")
    df["Price"] = df.apply(
        lambda r: fmt_price(r["price_hkd"], r["price_usdt"], r.get("price_eur")),
        axis=1,
    )

    hkd = df["price_hkd"].dropna()
    if len(hkd):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Matches", f"{len(df):,}")
        m2.metric("Median", f"{int(hkd.median()/1000):,}k")
        m3.metric("Low", f"{int(hkd.min()/1000):,}k")
        m4.metric("High", f"{int(hkd.max()/1000):,}k")
    else:
        st.caption(f"{len(df):,} matches · prices in HKD")

    compact = df[["Ref", "Year", "N", "Metal", "Dial", "Description", "Price"]]
    st.dataframe(
        compact,
        width="stretch",
        hide_index=True,
        height=min(620, 38 * (len(compact) + 1) + 3),
        column_config={
            "Ref": st.column_config.TextColumn(width="small"),
            "Year": st.column_config.TextColumn(width="small"),
            "N": st.column_config.TextColumn(width="small", help="Newly-delivered month"),
            "Metal": st.column_config.TextColumn(width="small",
                help="Case metal decoded from Rolex 6th digit"),
            "Dial": st.column_config.TextColumn(width="medium"),
            "Description": st.column_config.TextColumn(width="large"),
            "Price": st.column_config.TextColumn(width="small"),
        },
    )

    with st.expander("Show full row (brand, seller, phone, date, raw line)"):
        df["Date"] = df["posted_at"].str.slice(0, 10)
        df["Time"] = df["posted_at"].str.slice(11, 16)
        full = df[[
            "Date", "Time", "reference", "nickname", "brand", "Year", "N",
            "metal", "dial_color", "dial_details", "condition", "full_set",
            "price_hkd", "price_usdt", "price_eur",
            "seller", "seller_phone", "raw_line",
        ]]
        st.dataframe(full, width="stretch", hide_index=True)
        st.download_button(
            "Download CSV",
            full.to_csv(index=False).encode("utf-8"),
            f"listings_{market}.csv",
            "text/csv",
            key=f"dl_{market}",
        )


# ----- Top-level tabs: one per market + Compare -----
tab_titles = [MARKET_LABEL[m] for m in MARKETS_AVAILABLE] + ["🔀 Compare"]
tabs = st.tabs(tab_titles)

for i, m in enumerate(MARKETS_AVAILABLE):
    with tabs[i]:
        render_market_view(m)

tab_compare = tabs[-1]

# ==========================================================================
# TAB 2 — Compare markets (same watch across HK / EU / Europe in USD)
# ==========================================================================
with tab_compare:
    st.markdown(
        "Enter a reference and see the same watch **across every market**. "
        "Prices are all normalized to **USD** (HKD ÷ 7.8, EUR × 1.08, USDT 1:1). "
        "Rows are grouped by exact spec (year + condition + dial details + "
        "metal + full-set) so you're only comparing apples-to-apples."
    )

    cmp_ref = st.text_input(
        "Reference", "",
        placeholder="e.g. 5167R, 126500, 26240OR",
        key="cmp_ref",
    )

    if cmp_ref:
        # Pull matching rows from every available market DB, tag with market,
        # combine.
        all_rows = []
        for m in MARKETS_AVAILABLE:
            with sqlite3.connect(db_path(m)) as c:
                mdf = pd.read_sql_query(
                    """
                    SELECT reference, brand, year_made, month_made,
                           condition, dial_details, metal, full_set,
                           price_hkd, price_usdt, price_eur,
                           posted_at, seller, raw_line
                    FROM listings
                    WHERE reference LIKE ? COLLATE NOCASE
                       OR raw_line LIKE ? COLLATE NOCASE
                    """,
                    c, params=[f"%{cmp_ref}%", f"%{cmp_ref}%"],
                )
            mdf["market"] = m
            all_rows.append(mdf)

        combined = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()

        if combined.empty:
            st.info(f"No matches for '{cmp_ref}' in any market.")
        else:
            # Normalize to USD; drop rows without any price
            combined["usd"] = combined.apply(
                lambda r: row_to_usd(r["price_hkd"], r["price_usdt"], r["price_eur"]),
                axis=1,
            )
            # Sanity floor: sub-$1k USD prices for these brands are almost
            # always parser errors (a partial digit run mis-tagged as price).
            # Also cap absurdly high — any single listing over $30M is noise.
            combined = combined[
                combined["usd"].notna()
                & (combined["usd"] >= 1_000)
                & (combined["usd"] <= 30_000_000)
            ].copy()

            if combined.empty:
                st.info("Rows found but none had a parseable price.")
            else:
                # Build the spec signature. We keep exact year, condition,
                # dial_details, metal, full_set — the user chose strict match.
                # NULLs are normalized to '' so 'no dial detail' groups together.
                def sig(row):
                    return (
                        str(row["reference"]).upper(),
                        int(row["year_made"]) if pd.notna(row["year_made"]) else 0,
                        str(row["condition"] or ""),
                        str(row["dial_details"] or ""),
                        str(row["metal"] or ""),
                        int(row["full_set"]) if pd.notna(row["full_set"]) else -1,
                    )
                combined["_sig"] = combined.apply(sig, axis=1)

                # Aggregate: for each signature, one row per market with
                # count/min/med/max USD + one sample raw_line (the cheapest).
                spec_rows = []
                for sig_tuple, g in combined.groupby("_sig"):
                    ref, year, cond, details_str, metal, fs = sig_tuple
                    year_disp = str(year) if year else ""
                    fs_disp = "fullset" if fs == 1 else ("naked" if fs == 0 else "")

                    row_out = {
                        "Ref": ref,
                        "Year": year_disp,
                        "Cond": cond,
                        "Dial": details_str,
                        "Metal": metal,
                        "Full set": fs_disp,
                    }

                    per_market = {}
                    for m in MARKETS_AVAILABLE:
                        mg = g[g["market"] == m]
                        if len(mg):
                            usds = mg["usd"].dropna()
                            per_market[m] = {
                                "count": len(mg),
                                "min": float(usds.min()),
                                "med": float(usds.median()),
                                "max": float(usds.max()),
                                # Sample raw line — take the cheapest one so
                                # the user can eyeball what drove the min.
                                "raw": mg.sort_values("usd").iloc[0]["raw_line"],
                            }
                        else:
                            per_market[m] = None

                    # Only keep signatures present in ≥2 markets (that's the
                    # whole point of the compare view). Toggle below to relax.
                    if sum(1 for v in per_market.values() if v) < 2:
                        continue

                    # Populate per-market columns (min/med/max USD + count)
                    for m in MARKETS_AVAILABLE:
                        label = MARKET_SHORT[m]
                        pm = per_market[m]
                        if pm:
                            row_out[f"{label} n"] = pm["count"]
                            row_out[f"{label} min $"] = fmt_usd(pm["min"])
                            row_out[f"{label} med $"] = fmt_usd(pm["med"])
                            row_out[f"{label} max $"] = fmt_usd(pm["max"])
                        else:
                            row_out[f"{label} n"] = 0
                            row_out[f"{label} min $"] = ""
                            row_out[f"{label} med $"] = ""
                            row_out[f"{label} max $"] = ""

                    # Spread: (best sell price − cheapest buy price) as % of buy.
                    market_medians = {
                        m: per_market[m]["med"] for m in MARKETS_AVAILABLE if per_market[m]
                    }
                    market_mins = {
                        m: per_market[m]["min"] for m in MARKETS_AVAILABLE if per_market[m]
                    }
                    if len(market_mins) >= 2:
                        cheapest = min(market_mins.values())
                        priciest_median = max(market_medians.values())
                        spread_pct = (priciest_median - cheapest) / cheapest * 100
                        row_out["Spread %"] = f"{spread_pct:+.1f}%"
                        row_out["_spread_sort"] = spread_pct
                    else:
                        row_out["Spread %"] = ""
                        row_out["_spread_sort"] = 0

                    # Raw sample columns at the end (per user request)
                    for m in MARKETS_AVAILABLE:
                        label = MARKET_LABEL[m].split()[-1].strip("()")
                        pm = per_market[m]
                        row_out[f"{label} raw"] = pm["raw"] if pm else ""

                    spec_rows.append(row_out)

                if not spec_rows:
                    st.info(
                        f"Found '{cmp_ref}' but no spec matched in ≥2 markets. "
                        f"Try a broader reference or check if the other markets "
                        f"have that watch at all."
                    )
                else:
                    out_df = pd.DataFrame(spec_rows).sort_values(
                        "_spread_sort", ascending=False
                    ).drop(columns=["_spread_sort"])

                    st.caption(
                        f"{len(out_df)} spec variant(s) present in ≥2 markets · "
                        f"sorted by spread (biggest arbitrage first)"
                    )

                    st.dataframe(
                        out_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Ref": st.column_config.TextColumn(width="small"),
                            "Year": st.column_config.TextColumn(width="small"),
                            "Cond": st.column_config.TextColumn(width="small"),
                            "Dial": st.column_config.TextColumn(width="medium"),
                            "Metal": st.column_config.TextColumn(width="small"),
                            "Full set": st.column_config.TextColumn(width="small"),
                            "Spread %": st.column_config.TextColumn(
                                width="small",
                                help="(priciest market median − cheapest market min) / cheapest min",
                            ),
                            **{
                                f"{MARKET_SHORT[m]} raw": st.column_config.TextColumn(width="large",
                                    help="Cheapest listing's original text — verify against source")
                                for m in MARKETS_AVAILABLE
                            },
                        },
                    )

                    st.download_button(
                        "Download comparison CSV",
                        out_df.to_csv(index=False).encode("utf-8"),
                        f"compare_{cmp_ref.replace('/', '-')}.csv",
                        "text/csv",
                    )
    else:
        st.caption("Enter a reference above to compare across markets.")
