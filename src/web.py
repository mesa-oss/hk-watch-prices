"""Streamlit web UI for browsing the watch price database.

Run with:
    streamlit run src/web.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "watches.db"

st.set_page_config(page_title="HK Watch Prices", layout="wide")
st.title("HK Watch Market Prices")

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
    min_d, max_d = conn.execute("SELECT MIN(posted_at), MAX(posted_at) FROM listings").fetchone()
    return total, refs, min_d, max_d


total, n_refs, min_d, max_d = overall_stats()
st.caption(
    f"**{total:,}** listings · **{n_refs:,}** unique references · "
    f"posted {min_d[:10]} → {max_d[:10]}"
)

# --- Sidebar filters ---
with st.sidebar:
    st.header("Filters")
    ref = st.text_input("Reference (contains)", "")
    brands = load_distinct("brand")
    brand = st.selectbox("Brand", [""] + brands)
    color = st.text_input("Dial color (contains)", "")
    year_min, year_max = st.slider("Year made", 1990, 2030, (2010, 2026))
    condition = st.radio("Condition", ["any", "new", "used"], horizontal=True)
    full_set = st.radio("Full set", ["any", "yes", "no"], horizontal=True)
    seller = st.text_input("Seller (contains)", "")
    st.markdown("---")
    st.markdown("**Tip:** type a partial reference like `5167` or `26240`")

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

sql = f"""
SELECT posted_at, seller, brand, reference, dial_color,
       year_made, month_made, condition, full_set,
       price_hkd, price_usdt, raw_line
FROM listings WHERE {' AND '.join(where)}
ORDER BY posted_at DESC
LIMIT 2000
"""

df = pd.read_sql_query(sql, conn, params=params)

# --- Summary block ---
if len(df):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Matches", f"{len(df):,}")
    hkd = df["price_hkd"].dropna()
    usdt = df["price_usdt"].dropna()
    if len(hkd):
        c2.metric("Median HKD", f"{int(hkd.median()):,}")
        c3.metric("Min HKD", f"{int(hkd.min()):,}")
        c4.metric("Max HKD", f"{int(hkd.max()):,}")

    # Quick chart: price by year
    if len(hkd) > 5 and df["year_made"].notna().sum() > 5:
        st.subheader("HKD price by year made")
        chart = df.dropna(subset=["price_hkd", "year_made"])
        st.scatter_chart(chart, x="year_made", y="price_hkd", color="brand")

    st.subheader("Listings")
    st.dataframe(df, width="stretch", height=600)
    st.download_button(
        "Download filtered CSV",
        df.to_csv(index=False).encode("utf-8"),
        "filtered_listings.csv",
        "text/csv",
    )
else:
    st.info("No matches. Try broader filters.")
