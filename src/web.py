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


def _spec_sig(row) -> tuple:
    """Canonical spec signature — used to match same-watch listings across
    markets. STRICT — every field must match exactly:
      reference + year + month + condition + dial_details + metal + full_set

    Month is included so an N4 delivery isn't compared to an N6 delivery
    (different watches even though the ref is the same). NULL month matches
    only other NULL months.
    """
    return (
        str(row["reference"]).upper(),
        int(row["year_made"]) if pd.notna(row["year_made"]) else 0,
        int(row["month_made"]) if pd.notna(row["month_made"]) else 0,
        str(row["condition"] or ""),
        str(row["dial_details"] or ""),
        str(row["metal"] or ""),
        int(row["full_set"]) if pd.notna(row["full_set"]) else -1,
    )


def render_deal_finder(buy_market: str, ref_market: str) -> None:
    """Browse listings from `buy_market` with the cheapest same-spec price
    from `ref_market` attached to each row. Rank by delta so opportunities
    where you can buy cheaper than the reference market's floor float to
    the top — matches the user's real workflow.
    """
    key = f"deal_{buy_market}_{ref_market}"

    # --- Filters (mirror the HK tab, all applied to the BUY market) ---
    top1, top2 = st.columns([2, 1])
    with top1:
        ref = st.text_input(
            "Reference", "", placeholder="e.g. 5167, 26240OR, RM035",
            label_visibility="collapsed", key=f"{key}_ref",
        )
    with top2:
        sort_by = st.selectbox(
            "Sort",
            ["Best deal", "Delta $ ↓", "Buy price ↑", "Buy price ↓", "Newest"],
            label_visibility="collapsed", key=f"{key}_sort",
        )

    with st.expander("More filters", expanded=False):
        f1, f2 = st.columns(2)
        brands = load_distinct("brand", buy_market)
        brand = f1.selectbox("Brand", [""] + brands, key=f"{key}_brand")
        condition = f2.radio("Condition", ["any", "new", "used"],
                             horizontal=True, key=f"{key}_cond")

        f3, f4 = st.columns(2)
        color = f3.text_input("Color", "", placeholder="blue, salmon",
                              key=f"{key}_color")
        details = f4.text_input("Details", "", placeholder="diamond, roman",
                                key=f"{key}_details")

        f5, f6 = st.columns(2)
        full_set = f5.radio("Full set", ["any", "yes", "no"],
                            horizontal=True, key=f"{key}_fs")
        seller = f6.text_input("Seller", "", key=f"{key}_seller")

        year_min, year_max = st.slider("Year made", 1990, 2030, (2010, 2026),
                                       key=f"{key}_year")

    # --- Build BUY-market SQL (same filter shape as HK tab) ---
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

    sql = f"""
    SELECT posted_at, seller, seller_phone, brand, reference,
           dial_color, dial_details, metal, nickname,
           year_made, month_made, condition, full_set,
           price_hkd, price_usdt, price_eur, raw_line
    FROM listings
    WHERE {' AND '.join(where)}
    ORDER BY posted_at DESC
    LIMIT 2000
    """

    with sqlite3.connect(db_path(buy_market)) as conn:
        buy_df = pd.read_sql_query(sql, conn, params=params)

    if not len(buy_df):
        st.info(
            f"No {MARKET_LABEL[buy_market]} listings match those filters. "
            f"Widen the filters or try another reference."
        )
        return

    # Normalize buy-side price to USD with sanity floor
    buy_df["buy_usd"] = buy_df.apply(
        lambda r: row_to_usd(r["price_hkd"], r["price_usdt"], r["price_eur"]),
        axis=1,
    )
    buy_df = buy_df[
        buy_df["buy_usd"].notna()
        & (buy_df["buy_usd"] >= 1_000)
        & (buy_df["buy_usd"] <= 30_000_000)
    ].copy()

    if not len(buy_df):
        st.info("Filters matched rows but none had a parseable price.")
        return

    # --- Load REFERENCE market, aggregate by signature (MIN price per spec) ---
    # Only pull refs we actually need to reduce load.
    refs_needed = tuple(buy_df["reference"].dropna().unique())
    if not refs_needed:
        st.info("No matchable references in the buy-side selection.")
        return
    placeholders = ",".join("?" for _ in refs_needed)
    with sqlite3.connect(db_path(ref_market)) as conn:
        ref_df = pd.read_sql_query(
            f"""
            SELECT reference, year_made, month_made, condition, dial_details,
                   metal, full_set, price_hkd, price_usdt, price_eur,
                   raw_line, posted_at, seller, seller_phone
            FROM listings
            WHERE reference IN ({placeholders}) COLLATE NOCASE
            """,
            conn, params=list(refs_needed),
        )

    ref_df["ref_usd"] = ref_df.apply(
        lambda r: row_to_usd(r["price_hkd"], r["price_usdt"], r["price_eur"]),
        axis=1,
    )
    ref_df = ref_df[
        ref_df["ref_usd"].notna()
        & (ref_df["ref_usd"] >= 1_000)
        & (ref_df["ref_usd"] <= 30_000_000)
    ].copy()

    if not len(ref_df):
        st.info(
            f"{MARKET_LABEL[ref_market]} has no comparable listings for these refs."
        )
        return

    # Aggregate ref market by signature → min price + count + cheapest
    # listing's metadata (seller, phone, posted_at, raw_line).
    ref_df["_sig"] = ref_df.apply(_spec_sig, axis=1)
    agg = (
        ref_df.sort_values("ref_usd")
        .groupby("_sig")
        .agg(
            ref_min_usd=("ref_usd", "min"),
            ref_med_usd=("ref_usd", "median"),
            ref_n=("ref_usd", "size"),
            ref_raw=("raw_line", "first"),        # cheapest listing (sorted)
            ref_seller=("seller", "first"),
            ref_phone=("seller_phone", "first"),
            ref_posted=("posted_at", "first"),
        )
        .reset_index()
    )

    # Merge buy listings with ref-market signature aggregate (inner join —
    # rows with no comparable in ref market are dropped, since without a
    # comparison there's nothing to score).
    buy_df["_sig"] = buy_df.apply(_spec_sig, axis=1)
    merged = buy_df.merge(agg, on="_sig", how="inner")

    if not len(merged):
        st.info(
            f"Buy-side has {len(buy_df):,} listings but none have a matching "
            f"same-spec listing in {MARKET_LABEL[ref_market]}. "
            f"Try loosening filters or wait for more data."
        )
        return

    # --- Score & sort ---
    merged["delta_usd"] = merged["ref_min_usd"] - merged["buy_usd"]
    merged["delta_pct"] = merged["delta_usd"] / merged["buy_usd"] * 100

    if sort_by == "Best deal":
        merged = merged.sort_values("delta_pct", ascending=False)
    elif sort_by == "Delta $ ↓":
        merged = merged.sort_values("delta_usd", ascending=False)
    elif sort_by == "Buy price ↑":
        merged = merged.sort_values("buy_usd", ascending=True)
    elif sort_by == "Buy price ↓":
        merged = merged.sort_values("buy_usd", ascending=False)
    else:  # Newest
        merged = merged.sort_values("posted_at", ascending=False)

    # --- Display formatting ---
    def _fmt_ref(row):
        r = row["reference"]
        n = row["nickname"]
        return f"{r} ({n})" if isinstance(n, str) and n else r

    merged["Ref"] = merged.apply(_fmt_ref, axis=1)
    merged["Year"] = merged["year_made"].apply(fmt_year)
    merged["N"] = merged["month_made"].apply(fmt_month)
    merged["Cond"] = merged["condition"].fillna("").str.slice(0, 4)
    merged["Metal"] = merged["metal"].fillna("")
    merged["Dial"] = merged.apply(
        lambda r: fmt_dial(r["dial_color"], r["dial_details"]), axis=1,
    )
    merged["Buy $"] = merged["buy_usd"].apply(fmt_usd)
    ref_label = MARKET_SHORT[ref_market]
    buy_label = MARKET_SHORT[buy_market]
    merged[f"{ref_label} min $"] = merged["ref_min_usd"].apply(fmt_usd)
    merged[f"{ref_label} n"] = merged["ref_n"]
    merged["Delta $"] = merged["delta_usd"].apply(lambda x: fmt_usd(x) if x >= 0 else f"−{fmt_usd(-x)}")
    merged["Delta %"] = merged["delta_pct"].apply(lambda x: f"{x:+.1f}%")

    # Publication date + seller contact for BOTH sides so you can act quickly
    merged[f"{buy_label} date"] = merged["posted_at"].str.slice(0, 10)
    merged[f"{buy_label} seller"] = merged["seller"].fillna("")
    # Prefer explicit phone if we detected one; otherwise leave blank (the
    # seller column already shows the phone-as-name when that's all we have)
    merged[f"{buy_label} phone"] = merged["seller_phone"].fillna("")

    merged[f"{ref_label} date"] = merged["ref_posted"].str.slice(0, 10)
    merged[f"{ref_label} seller"] = merged["ref_seller"].fillna("")
    merged[f"{ref_label} phone"] = merged["ref_phone"].fillna("")

    merged["Buy raw"] = merged["raw_line"].fillna("")
    merged[f"{ref_label} raw"] = merged["ref_raw"].fillna("")

    # Summary metrics
    profitable = (merged["delta_pct"] > 0).sum()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Comparable", f"{len(merged):,}")
    m2.metric("Positive delta", f"{profitable:,}",
              f"{profitable/len(merged)*100:.0f}%" if len(merged) else "")
    if len(merged):
        m3.metric("Best delta %", f"{merged['delta_pct'].max():+.1f}%")
        m4.metric("Best delta $", fmt_usd(merged['delta_usd'].max()))

    display = merged[[
        "Ref", "Year", "N", "Cond", "Metal", "Dial",
        "Buy $", f"{ref_label} min $", f"{ref_label} n",
        "Delta $", "Delta %",
        # Contact info: date + seller + phone for both sides so you can
        # jump straight to WhatsApp
        f"{buy_label} date", f"{buy_label} seller", f"{buy_label} phone",
        f"{ref_label} date", f"{ref_label} seller", f"{ref_label} phone",
        "Buy raw", f"{ref_label} raw",
    ]]

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        height=min(700, 38 * (len(display) + 1) + 3),
        column_config={
            "Ref": st.column_config.TextColumn(width="small"),
            "Year": st.column_config.TextColumn(width="small"),
            "N": st.column_config.TextColumn(width="small"),
            "Cond": st.column_config.TextColumn(width="small"),
            "Metal": st.column_config.TextColumn(width="small"),
            "Dial": st.column_config.TextColumn(width="medium"),
            "Buy $": st.column_config.TextColumn(width="small",
                help=f"{MARKET_LABEL[buy_market]} listing price in USD"),
            f"{ref_label} min $": st.column_config.TextColumn(width="small",
                help=f"Cheapest same-spec {MARKET_LABEL[ref_market]} listing"),
            f"{ref_label} n": st.column_config.NumberColumn(width="small",
                help=f"# of same-spec listings in {MARKET_LABEL[ref_market]}"),
            "Delta $": st.column_config.TextColumn(width="small",
                help=f"{ref_label} min − Buy (positive = buy here, sell in {ref_label})"),
            "Delta %": st.column_config.TextColumn(width="small"),
            f"{buy_label} date": st.column_config.TextColumn(width="small",
                help="When the buy-side listing was posted"),
            f"{buy_label} seller": st.column_config.TextColumn(width="medium",
                help="Seller name (or phone if not in your contacts)"),
            f"{buy_label} phone": st.column_config.TextColumn(width="medium",
                help="Explicit phone (when seller isn't a saved contact)"),
            f"{ref_label} date": st.column_config.TextColumn(width="small"),
            f"{ref_label} seller": st.column_config.TextColumn(width="medium"),
            f"{ref_label} phone": st.column_config.TextColumn(width="medium"),
            "Buy raw": st.column_config.TextColumn(width="large",
                help=f"Original {MARKET_LABEL[buy_market]} dealer text"),
            f"{ref_label} raw": st.column_config.TextColumn(width="large",
                help=f"Cheapest {MARKET_LABEL[ref_market]} same-spec listing's text"),
        },
    )

    st.download_button(
        "Download comparison CSV",
        display.to_csv(index=False).encode("utf-8"),
        f"deals_{buy_market}_vs_{ref_market}.csv",
        "text/csv",
        key=f"{key}_dl",
    )


def render_top_deals() -> None:
    """Streamlined view for the user's main workflow: buy in Europe
    (Reuven + WDG combined), sell in HK. Only positive-delta listings are
    shown, sorted best-first. This is the tab she'll live in day-to-day.
    """
    # Which European sources are available? 'eu' = Reuven, 'wdg' = WDG.
    eu_sources = [m for m in ("eu", "wdg") if m in MARKETS_AVAILABLE]
    if "hk" not in MARKETS_AVAILABLE or not eu_sources:
        st.warning(
            "Top Deals needs both HK and at least one EU database loaded. "
            f"Currently have: {', '.join(MARKETS_AVAILABLE)}"
        )
        return

    st.markdown(
        "**Best EU → HK deals right now.** Only listings where the EU buy "
        "price is at or below the cheapest same-spec HK listing. Sorted by "
        "delta % — biggest opportunity at the top."
    )

    # --- Filters (same shape as Deal Finder, no market pickers) ---
    top1, top2, top3 = st.columns([2, 1, 1])
    with top1:
        ref = st.text_input(
            "Reference", "", placeholder="e.g. 5167, 26240OR, RM035",
            label_visibility="collapsed", key="td_ref",
        )
    with top2:
        min_delta_pct = st.selectbox(
            "Min delta",
            ["Any positive", "≥ 5%", "≥ 10%", "≥ 20%"],
            label_visibility="collapsed", key="td_mindelta",
        )
    with top3:
        source_pick = st.selectbox(
            "EU source",
            ["Both"] + [MARKET_LABEL[m] for m in eu_sources],
            label_visibility="collapsed", key="td_source",
        )

    with st.expander("More filters", expanded=False):
        f1, f2 = st.columns(2)
        # Union of brands across all EU sources so the picker is complete
        brand_set: set[str] = set()
        for m in eu_sources:
            brand_set.update(load_distinct("brand", m))
        brand = f1.selectbox("Brand", [""] + sorted(brand_set), key="td_brand")
        condition = f2.radio("Condition", ["any", "new", "used"],
                             horizontal=True, key="td_cond")

        f3, f4 = st.columns(2)
        color = f3.text_input("Color", "", placeholder="blue, salmon",
                              key="td_color")
        details = f4.text_input("Details", "", placeholder="diamond, roman",
                                key="td_details")

        f5, f6 = st.columns(2)
        full_set = f5.radio("Full set", ["any", "yes", "no"],
                            horizontal=True, key="td_fs")
        seller = f6.text_input("Seller", "", key="td_seller")

        year_min, year_max = st.slider("Year made", 1990, 2030, (2010, 2026),
                                       key="td_year")

    # --- Which sources to load ---
    load_sources = eu_sources
    if source_pick != "Both":
        # User picked a single source
        load_sources = [m for m in eu_sources if MARKET_LABEL[m] == source_pick]

    # --- Build the shared WHERE clause (applied to each EU source) ---
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

    # --- Load buy-side from every selected EU source, tag with source ---
    buy_parts = []
    for m in load_sources:
        sql = f"""
        SELECT posted_at, seller, seller_phone, brand, reference,
               dial_color, dial_details, metal, nickname,
               year_made, month_made, condition, full_set,
               price_hkd, price_usdt, price_eur, raw_line
        FROM listings
        WHERE {' AND '.join(where)}
        ORDER BY posted_at DESC
        LIMIT 2000
        """
        with sqlite3.connect(db_path(m)) as conn:
            df_m = pd.read_sql_query(sql, conn, params=params)
        df_m["source"] = m
        buy_parts.append(df_m)
    buy_df = pd.concat(buy_parts, ignore_index=True) if buy_parts else pd.DataFrame()

    if not len(buy_df):
        st.info("No EU listings match those filters.")
        return

    buy_df["buy_usd"] = buy_df.apply(
        lambda r: row_to_usd(r["price_hkd"], r["price_usdt"], r["price_eur"]),
        axis=1,
    )
    buy_df = buy_df[
        buy_df["buy_usd"].notna()
        & (buy_df["buy_usd"] >= 1_000)
        & (buy_df["buy_usd"] <= 30_000_000)
    ].copy()

    if not len(buy_df):
        st.info("EU listings found but none had a parseable price.")
        return

    # --- Load HK reference side (only refs we actually need) ---
    refs_needed = tuple(buy_df["reference"].dropna().unique())
    placeholders = ",".join("?" for _ in refs_needed)
    with sqlite3.connect(db_path("hk")) as conn:
        hk_df = pd.read_sql_query(
            f"""
            SELECT reference, year_made, month_made, condition, dial_details,
                   metal, full_set, price_hkd, price_usdt, price_eur,
                   raw_line, posted_at, seller, seller_phone
            FROM listings
            WHERE reference IN ({placeholders}) COLLATE NOCASE
            """,
            conn, params=list(refs_needed),
        )
    hk_df["hk_usd"] = hk_df.apply(
        lambda r: row_to_usd(r["price_hkd"], r["price_usdt"], r["price_eur"]),
        axis=1,
    )
    hk_df = hk_df[
        hk_df["hk_usd"].notna()
        & (hk_df["hk_usd"] >= 1_000)
        & (hk_df["hk_usd"] <= 30_000_000)
    ].copy()
    if not len(hk_df):
        st.info("None of these EU refs are present in HK yet — no comparison possible.")
        return

    hk_df["_sig"] = hk_df.apply(_spec_sig, axis=1)
    agg = (
        hk_df.sort_values("hk_usd").groupby("_sig")
        .agg(hk_min_usd=("hk_usd", "min"),
             hk_n=("hk_usd", "size"),
             hk_raw=("raw_line", "first"),
             hk_seller=("seller", "first"),
             hk_phone=("seller_phone", "first"),
             hk_posted=("posted_at", "first"))
        .reset_index()
    )

    buy_df["_sig"] = buy_df.apply(_spec_sig, axis=1)
    merged = buy_df.merge(agg, on="_sig", how="inner")

    # Compute delta and KEEP ONLY POSITIVE deltas (user's rule: EU ≤ HK)
    merged["delta_usd"] = merged["hk_min_usd"] - merged["buy_usd"]
    merged["delta_pct"] = merged["delta_usd"] / merged["buy_usd"] * 100
    merged = merged[merged["delta_pct"] >= 0].copy()

    # Sanity cap: deltas over ~60% are almost always parser errors on one
    # side. Real cross-market arbitrage in the watch market is 3-25%,
    # occasionally to 40% for a genuinely underpriced listing. Anything
    # higher is a mis-captured price (usually the EU side missing a digit).
    merged = merged[merged["delta_pct"] <= 60.0].copy()

    # Apply min-delta filter
    threshold = {"Any positive": 0.0, "≥ 5%": 5.0, "≥ 10%": 10.0, "≥ 20%": 20.0}[min_delta_pct]
    merged = merged[merged["delta_pct"] >= threshold]

    if not len(merged):
        st.info(
            f"No EU listings currently priced at or below HK's cheapest same-spec "
            f"(with min delta {min_delta_pct}). Loosen filters or wait for new data."
        )
        return

    merged = merged.sort_values("delta_pct", ascending=False)

    # --- Display ---
    def _fmt_ref(row):
        r = row["reference"]
        n = row["nickname"]
        return f"{r} ({n})" if isinstance(n, str) and n else r

    merged["Ref"] = merged.apply(_fmt_ref, axis=1)
    merged["Year"] = merged["year_made"].apply(fmt_year)
    merged["N"] = merged["month_made"].apply(fmt_month)
    merged["Cond"] = merged["condition"].fillna("").str.slice(0, 4)
    merged["Metal"] = merged["metal"].fillna("")
    merged["Dial"] = merged.apply(
        lambda r: fmt_dial(r["dial_color"], r["dial_details"]), axis=1,
    )
    merged["Src"] = merged["source"].map({m: MARKET_SHORT[m] for m in eu_sources})
    merged["EU $"] = merged["buy_usd"].apply(fmt_usd)
    merged["HK min $"] = merged["hk_min_usd"].apply(fmt_usd)
    merged["HK n"] = merged["hk_n"]
    merged["Delta $"] = merged["delta_usd"].apply(fmt_usd)
    merged["Delta %"] = merged["delta_pct"].apply(lambda x: f"+{x:.1f}%")
    merged["EU date"] = merged["posted_at"].str.slice(0, 10)
    merged["EU seller"] = merged["seller"].fillna("")
    merged["EU phone"] = merged["seller_phone"].fillna("")
    merged["HK date"] = merged["hk_posted"].str.slice(0, 10)
    merged["HK seller"] = merged["hk_seller"].fillna("")
    merged["HK phone"] = merged["hk_phone"].fillna("")
    merged["EU raw"] = merged["raw_line"].fillna("")
    merged["HK raw"] = merged["hk_raw"].fillna("")

    # Summary metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🔥 Deals", f"{len(merged):,}")
    m2.metric("Best %", f"+{merged['delta_pct'].max():.1f}%")
    m3.metric("Best $", fmt_usd(merged['delta_usd'].max()))
    m4.metric("Total spread $", fmt_usd(merged['delta_usd'].sum()))

    display = merged[[
        "Src", "Ref", "Year", "N", "Cond", "Metal", "Dial",
        "EU $", "HK min $", "HK n", "Delta $", "Delta %",
        "EU date", "EU seller", "EU phone",
        "HK date", "HK seller", "HK phone",
        "EU raw", "HK raw",
    ]]

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        height=min(700, 38 * (len(display) + 1) + 3),
        column_config={
            "Src": st.column_config.TextColumn(width="small",
                help="Which EU group the listing came from"),
            "Ref": st.column_config.TextColumn(width="small"),
            "Year": st.column_config.TextColumn(width="small"),
            "N": st.column_config.TextColumn(width="small"),
            "Cond": st.column_config.TextColumn(width="small"),
            "Metal": st.column_config.TextColumn(width="small"),
            "Dial": st.column_config.TextColumn(width="medium"),
            "EU $": st.column_config.TextColumn(width="small"),
            "HK min $": st.column_config.TextColumn(width="small"),
            "HK n": st.column_config.NumberColumn(width="small"),
            "Delta $": st.column_config.TextColumn(width="small"),
            "Delta %": st.column_config.TextColumn(width="small"),
            "EU date": st.column_config.TextColumn(width="small"),
            "EU seller": st.column_config.TextColumn(width="medium"),
            "EU phone": st.column_config.TextColumn(width="medium"),
            "HK date": st.column_config.TextColumn(width="small"),
            "HK seller": st.column_config.TextColumn(width="medium"),
            "HK phone": st.column_config.TextColumn(width="medium"),
            "EU raw": st.column_config.TextColumn(width="large"),
            "HK raw": st.column_config.TextColumn(width="large"),
        },
    )

    st.download_button(
        "Download deals CSV",
        display.to_csv(index=False).encode("utf-8"),
        "top_deals_eu_to_hk.csv",
        "text/csv",
        key="td_dl",
    )


# ----- Top-level tabs: 🔥 Top Deals FIRST, then per-market, then Deal Finder -----
tab_titles = ["🔥 Top Deals"] + [MARKET_LABEL[m] for m in MARKETS_AVAILABLE] + ["🔀 Deal Finder"]
tabs = st.tabs(tab_titles)

with tabs[0]:
    render_top_deals()

for i, m in enumerate(MARKETS_AVAILABLE):
    with tabs[i + 1]:
        render_market_view(m)

# ==========================================================================
# LAST TAB — Deal Finder (buy-side listings + reference-market cheapest)
# ==========================================================================
with tabs[-1]:
    st.markdown(
        "**Browse listings from one market with the cheapest same-spec price "
        "from another market attached.** Delta = reference-market cheapest "
        "minus this listing's price, both in USD (HKD ÷ 7.8, EUR × 1.08). "
        "Positive delta = you'd buy on the left, sell on the right."
    )

    dm1, dm2 = st.columns(2)
    with dm1:
        buy_market = st.selectbox(
            "🛒 Browse (buy here)",
            MARKETS_AVAILABLE,
            index=(MARKETS_AVAILABLE.index("eu") if "eu" in MARKETS_AVAILABLE else 0),
            format_func=lambda m: MARKET_LABEL[m],
            key="deal_buy_market",
        )
    with dm2:
        ref_options = [m for m in MARKETS_AVAILABLE if m != buy_market]
        ref_market = st.selectbox(
            "🏷️ Reference market (sell here)",
            ref_options,
            index=(ref_options.index("hk") if "hk" in ref_options else 0),
            format_func=lambda m: MARKET_LABEL[m],
            key="deal_ref_market",
        )

    render_deal_finder(buy_market, ref_market)
