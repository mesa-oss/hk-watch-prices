"""Streamlit web UI for browsing the watch price database.

Mobile-first: filters and sort live at the top of the page (not in a hidden
sidebar) with big touch targets. The table is a compact 5-column view; full
row details are available via an expander.

Run with:
    streamlit run src/web.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "watches.db"

st.set_page_config(
    page_title="HK Watch Prices",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Trim default vertical padding; make form controls phone-friendly.
st.markdown(
    """
    <style>
      div.block-container { padding-top: 1rem; padding-bottom: 1rem; }
      /* Larger touch targets for selects / inputs */
      div[data-baseweb="select"] > div, .stTextInput input,
      .stSelectbox > div, .stRadio > div, button[kind="secondary"] {
        min-height: 42px;
      }
      /* Tight metric cards */
      [data-testid="stMetricValue"] { font-size: 1.1rem; }
      [data-testid="stMetricLabel"] { font-size: 0.75rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("HK Watch Prices")

if not DB_PATH.exists():
    st.error(f"Database not found at {DB_PATH}. Run `python src/refresh.py` first.")
    st.stop()

conn = sqlite3.connect(DB_PATH)


@st.cache_data(ttl=60)
def load_distinct(col: str) -> list[str]:
    rows = conn.execute(
        f"SELECT DISTINCT {col} FROM listings WHERE {col} IS NOT NULL ORDER BY {col}"
    ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=60)
def overall_stats():
    total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    refs = conn.execute("SELECT COUNT(DISTINCT reference) FROM listings").fetchone()[0]
    min_d, max_d = conn.execute(
        "SELECT MIN(posted_at), MAX(posted_at) FROM listings"
    ).fetchone()
    return total, refs, min_d, max_d


total, n_refs, min_d, max_d = overall_stats()
st.caption(
    f"{total:,} listings · {n_refs:,} refs · "
    f"{min_d[:10]} → {max_d[:10]}"
)

# ----- TOP FILTER BAR (always visible) -----
# Two main filters always on screen: reference search + sort. Big inputs.
top1, top2 = st.columns([2, 1])
with top1:
    ref = st.text_input(
        "Reference", "", placeholder="e.g. 5167, 26240OR, RM035",
        label_visibility="collapsed",
    )
with top2:
    sort_by = st.selectbox(
        "Sort",
        ["Newest", "Price ↑", "Price ↓", "Year ↓"],
        label_visibility="collapsed",
    )

# Secondary filters in an always-open expander so they're 1 tap from view
# but don't dominate the screen.
with st.expander("More filters", expanded=False):
    f1, f2 = st.columns(2)
    brands = load_distinct("brand")
    brand = f1.selectbox("Brand", [""] + brands)
    condition = f2.radio("Condition", ["any", "new", "used"], horizontal=True)

    f3, f4 = st.columns(2)
    color = f3.text_input("Color", "", placeholder="blue, salmon, ice blue")
    details = f4.text_input("Details", "", placeholder="diamond, roman, pavé")

    f5, f6 = st.columns(2)
    full_set = f5.radio("Full set", ["any", "yes", "no"], horizontal=True)
    seller = f6.text_input("Seller", "")

    year_min, year_max = st.slider("Year made", 1990, 2030, (2010, 2026))

# ----- Build SQL -----
where = ["1=1"]
params: list = []
if ref:
    where.append("reference LIKE ? COLLATE NOCASE")
    params.append(f"%{ref}%")
if brand:
    where.append("brand = ?")
    params.append(brand)
if color:
    # Broad search: color filter matches dial_color OR dial_details OR the
    # original raw description. Typing 'grey' will surface any row
    # mentioning grey anywhere, not just rows tagged dial_color='grey'.
    where.append(
        "(dial_color LIKE ? COLLATE NOCASE "
        "OR dial_details LIKE ? COLLATE NOCASE "
        "OR raw_line LIKE ? COLLATE NOCASE)"
    )
    needle = f"%{color}%"
    params.extend([needle, needle, needle])
if details:
    # Same broadening so 'diamond' / 'roman' / 'panda' matches wherever the
    # word appears in the original line.
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
    "Price ↑": "COALESCE(price_hkd, price_usdt*8) ASC NULLS LAST",
    "Price ↓": "COALESCE(price_hkd, price_usdt*8) DESC NULLS LAST",
    "Year ↓": "year_made DESC NULLS LAST, posted_at DESC",
}[sort_by]

sql = f"""
SELECT posted_at, seller, brand, reference, dial_color, dial_details,
       year_made, month_made, condition, full_set,
       price_hkd, price_usdt, clean_line, raw_line
FROM listings
WHERE {' AND '.join(where)}
ORDER BY {order_clause}
LIMIT 1000
"""

df = pd.read_sql_query(sql, conn, params=params)

# ----- Formatting helpers -----
def fmt_year(y) -> str:
    """Full 4-digit year ('2026'), or empty."""
    return str(int(y)) if pd.notna(y) else ""


def fmt_month(m) -> str:
    """Dealer month notation: 'N5', 'N12', or empty."""
    return f"N{int(m)}" if pd.notna(m) else ""


def fmt_price(hkd, usdt) -> str:
    """One price column. HKD is the default. ₮ suffix only when seller listed
    crypto only (no HKD)."""
    val = hkd if pd.notna(hkd) else None
    if val is not None:
        v = float(val)
        if v >= 1_000_000:
            return f"{v/1_000_000:.2f}M"
        return f"{int(v/1_000):,}k"
    if pd.notna(usdt):
        u = float(usdt)
        if u >= 1_000_000:
            return f"{u/1_000_000:.2f}M ₮"
        return f"{int(u/1_000):,}k ₮"
    return ""


def fmt_dial(color, details) -> str:
    """Color + details combined, e.g. 'Black · Diamond' or 'Salmon · Pavé, Roman'."""
    parts = []
    if pd.notna(color) and color:
        parts.append(str(color))
    if pd.notna(details) and details:
        parts.append(str(details))
    return " · ".join(parts)


# ----- Compact mobile table -----
if len(df):
    df["Ref"] = df["reference"]
    df["Year"] = df["year_made"].apply(fmt_year)
    df["N"] = df["month_made"].apply(fmt_month)
    df["Dial"] = df.apply(lambda r: fmt_dial(r["dial_color"], r["dial_details"]), axis=1)
    # Description = the FULL original dealer line (raw_line), with nothing
    # stripped or normalized. The user wants every detail visible — panda
    # dial, tropical patina, bracelet vs leather, edition numbers, stickers,
    # diamond placement, etc. — even if it means some emoji clutter.
    df["Description"] = df["raw_line"].fillna("")
    df["Price"] = df.apply(lambda r: fmt_price(r["price_hkd"], r["price_usdt"]), axis=1)

    # Compact metrics in a single row
    hkd = df["price_hkd"].dropna()
    if len(hkd):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Matches", f"{len(df):,}")
        m2.metric("Median", f"{int(hkd.median()/1000):,}k")
        m3.metric("Low", f"{int(hkd.min()/1000):,}k")
        m4.metric("High", f"{int(hkd.max()/1000):,}k")
    else:
        st.caption(f"{len(df):,} matches · prices in HKD")

    # Six-column view. Year and N are separate so a row can show
    # year=2026 + N=N5 simultaneously without combining notation.
    compact = df[["Ref", "Year", "N", "Dial", "Description", "Price"]]
    st.dataframe(
        compact,
        width="stretch",
        hide_index=True,
        height=min(620, 38 * (len(compact) + 1) + 3),
        column_config={
            "Ref": st.column_config.TextColumn(width="small"),
            "Year": st.column_config.TextColumn(width="small"),
            "N": st.column_config.TextColumn(width="small", help="Newly-delivered month"),
            "Dial": st.column_config.TextColumn(width="medium"),
            "Description": st.column_config.TextColumn(width="large"),
            "Price": st.column_config.TextColumn(width="small"),
        },
    )

    with st.expander("Show full row (brand, seller, condition, raw line)"):
        full = df[[
            "reference", "brand", "Year", "N", "dial_color", "dial_details",
            "condition", "full_set", "price_hkd", "price_usdt", "seller",
            "posted_at", "clean_line",
        ]]
        st.dataframe(full, width="stretch", hide_index=True)
        st.download_button(
            "Download CSV",
            full.to_csv(index=False).encode("utf-8"),
            "filtered_listings.csv",
            "text/csv",
        )
else:
    st.info("No matches. Try a different reference or open 'More filters' to widen the search.")
