"""Streamlit web UI for browsing the watch price database.

Mobile-first: a compact 5-column table designed to fit on an iPhone screen
without horizontal scrolling. Full row details are available in an expander.

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
    layout="centered",  # narrower than "wide" — keeps table compact on phone
    initial_sidebar_state="collapsed",  # filters tucked away by default on mobile
)

# Trim Streamlit's default top padding so the title sits closer to the top of
# the phone viewport.
st.markdown(
    "<style>div.block-container{padding-top:1rem;padding-bottom:1rem;}</style>",
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

# --- Filters in sidebar (collapsed on mobile by default) ---
with st.sidebar:
    st.header("Filters")
    ref = st.text_input("Reference", "", placeholder="e.g. 5167")
    brands = load_distinct("brand")
    brand = st.selectbox("Brand", [""] + brands)
    color = st.text_input("Color", "", placeholder="e.g. blue, salmon")
    year_min, year_max = st.slider("Year made", 1990, 2030, (2010, 2026))
    condition = st.radio("Condition", ["any", "new", "used"], horizontal=True)
    full_set = st.radio("Full set", ["any", "yes", "no"], horizontal=True)
    seller = st.text_input("Seller", "")
    sort_by = st.selectbox(
        "Sort by",
        ["Newest first", "Price (low → high)", "Price (high → low)", "Year (newest)"],
    )

# --- Build query ---
where = ["1=1"]
params: list = []
if ref:
    where.append("reference LIKE ? COLLATE NOCASE")
    params.append(f"%{ref}%")
if brand:
    where.append("brand = ?")
    params.append(brand)
if color:
    where.append("dial_color LIKE ? COLLATE NOCASE")
    params.append(f"%{color}%")
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
    "Newest first": "posted_at DESC",
    "Price (low → high)": "COALESCE(price_hkd, price_usdt*8) ASC",
    "Price (high → low)": "COALESCE(price_hkd, price_usdt*8) DESC",
    "Year (newest)": "year_made DESC NULLS LAST, posted_at DESC",
}[sort_by]

sql = f"""
SELECT posted_at, seller, brand, reference, dial_color,
       year_made, month_made, condition, full_set,
       price_hkd, price_usdt, clean_line
FROM listings
WHERE {' AND '.join(where)}
ORDER BY {order_clause}
LIMIT 1000
"""

df = pd.read_sql_query(sql, conn, params=params)


# ----- Formatting helpers -----

def fmt_year(y, m) -> str:
    """N5/26 if month known, else 2024, else empty."""
    if pd.notna(m) and pd.notna(y):
        return f"N{int(m)}/{str(int(y))[-2:]}"
    if pd.notna(y):
        return str(int(y))
    if pd.notna(m):
        return f"N{int(m)}"
    return ""


def fmt_price(hkd, usdt) -> str:
    """Single compact price column. HKD is the default; only fall back to
    USDT when no HKD is present (rare — only when seller listed crypto only).
    """
    val = hkd if pd.notna(hkd) else None
    if val is not None:
        if val >= 1_000_000:
            return f"{val/1_000_000:.2f}M"
        return f"{int(val/1_000)}k"
    if pd.notna(usdt):
        u = int(usdt)
        if u >= 1_000_000:
            return f"{u/1_000_000:.2f}M ₮"
        return f"{int(u/1_000)}k ₮"
    return ""


# ----- Mobile-first compact table -----

if len(df):
    df["Year"] = df.apply(lambda r: fmt_year(r["year_made"], r["month_made"]), axis=1)
    df["Price"] = df.apply(lambda r: fmt_price(r["price_hkd"], r["price_usdt"]), axis=1)
    df["Cond"] = df["condition"].fillna("").str.slice(0, 4)
    df["Color"] = df["dial_color"].fillna("")
    df["Ref"] = df["reference"]

    compact = df[["Ref", "Year", "Cond", "Color", "Price"]]

    # Compact metrics above the table
    hkd = df["price_hkd"].dropna()
    if len(hkd):
        c1, c2, c3 = st.columns(3)
        c1.metric("Median", f"{int(hkd.median()/1000):,}k")
        c2.metric("Low", f"{int(hkd.min()/1000):,}k")
        c3.metric("High", f"{int(hkd.max()/1000):,}k")
    st.caption(f"{len(df):,} matches · prices in HKD")

    # The dataframe with constrained column widths so it always fits the
    # viewport (no horizontal scrolling on iPhone).
    st.dataframe(
        compact,
        width="stretch",
        hide_index=True,
        height=min(600, 38 * (len(compact) + 1) + 3),
        column_config={
            "Ref": st.column_config.TextColumn(width="small"),
            "Year": st.column_config.TextColumn(width="small"),
            "Cond": st.column_config.TextColumn(width="small"),
            "Color": st.column_config.TextColumn(width="small"),
            "Price": st.column_config.TextColumn(width="small"),
        },
    )

    # Full details available on demand (won't clutter mobile view)
    with st.expander("Show full details (brand, seller, raw line)"):
        full = df[[
            "reference", "brand", "Year", "dial_color", "Cond",
            "full_set", "price_hkd", "price_usdt", "seller",
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
    st.info("No matches. Open the sidebar (top-left **»**) and adjust filters.")
