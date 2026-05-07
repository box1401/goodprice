"""Streamlit 介面 — 繁中。

啟動：
    streamlit run web/app.py
"""
from __future__ import annotations

import io
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

# 讓 import src.* 在從 web/ 啟動時也能運作
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import DealDB  # noqa: E402


# ----------- 設定 -----------
def _load_cfg() -> dict:
    p = ROOT / "config.yaml"
    if not p.exists():
        p = ROOT / "config.yaml.template"
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


CFG = _load_cfg()
DB_PATH = ROOT / CFG.get("storage", {}).get("db_path", "data/deals.db")
DEFAULT_TOP_N = int(CFG.get("streamlit", {}).get("default_top_n", 50))
PAGE_TITLE = CFG.get("streamlit", {}).get("page_title", "Coupang 台灣特價監控")


st.set_page_config(page_title=PAGE_TITLE, layout="wide")
st.title(PAGE_TITLE)


if not DB_PATH.exists():
    st.warning(f"資料庫不存在：{DB_PATH}。請先執行 `python -m src.main`。")
    st.stop()

db = DealDB(DB_PATH)


# ----------- 側邊欄篩選 -----------
with st.sidebar:
    st.header("篩選條件")

    today = date.today()
    default_from = today - timedelta(days=7)
    date_from = st.date_input("起始日（抓取日）", value=default_from)
    date_to = st.date_input("結束日（抓取日）", value=today)

    region = st.selectbox(
        "地區",
        options=["ALL", "KR", "US"],
        format_func=lambda x: {"ALL": "全部", "KR": "韓國", "US": "美國"}[x],
    )

    min_discount = st.slider("最低折扣 % off", min_value=0, max_value=99, value=10, step=1)

    order_by = st.selectbox(
        "排序欄位",
        options=["discount_pct", "sale_price", "original_price", "scrape_date", "sale_end"],
        format_func=lambda x: {
            "discount_pct": "折扣率",
            "sale_price": "特價",
            "original_price": "原價",
            "scrape_date": "抓取日",
            "sale_end": "特價到期日",
        }[x],
    )
    descending = st.checkbox("由大到小", value=True)
    top_n = st.number_input("筆數上限", min_value=10, max_value=2000, value=DEFAULT_TOP_N, step=10)


# ----------- 查詢 -----------
rows = db.query(
    date_from=date_from,
    date_to=date_to,
    region=region,
    min_discount=float(min_discount) if min_discount else None,
    order_by=order_by,
    descending=descending,
    limit=int(top_n),
)

stats = db.stats()
c1, c2, c3 = st.columns(3)
c1.metric("資料庫總筆數", f"{stats['total']:,}")
c2.metric("今日新增", f"{stats['today']:,}")
c3.metric("最近抓取日", stats.get("latest_scrape_date") or "—")


if not rows:
    st.info("查無資料。調整篩選條件或先跑爬蟲。")
    st.stop()


# ----------- 整成 DataFrame -----------
df = pd.DataFrame([dict(r) for r in rows])

display = df.rename(columns={
    "region":         "地區",
    "title_zh":       "商品 (繁中)",
    "title_orig":     "商品 (原文)",
    "image_url":      "圖片",
    "original_price": "原價",
    "sale_price":     "特價",
    "discount_pct":   "折扣 %",
    "sale_start":     "特價開始",
    "sale_end":       "特價結束",
    "scrape_date":    "抓取日",
    "url":            "連結",
    "product_id":     "商品 ID",
})[[
    "圖片", "地區", "商品 (繁中)", "原價", "特價", "折扣 %",
    "特價開始", "特價結束", "抓取日", "連結",
]]


# ----------- 表格 + 圖表 -----------
tab1, tab_grid, tab2, tab3 = st.tabs(["表格", "圖卡", "圖表", "原始資料"])

with tab1:
    st.dataframe(
        display,
        use_container_width=True,
        height=700,
        column_config={
            "圖片": st.column_config.ImageColumn("圖片", width="small"),
            "連結": st.column_config.LinkColumn("連結", display_text="開啟"),
            "折扣 %": st.column_config.NumberColumn("折扣 %", format="%.1f"),
            "原價": st.column_config.NumberColumn("原價", format="NT$%d"),
            "特價": st.column_config.NumberColumn("特價", format="NT$%d"),
        },
    )

with tab_grid:
    st.caption("商品圖卡（5 欄）— 點圖開 Coupang 商品頁")
    cols_per_row = 5
    items = df.to_dict("records")
    for i in range(0, len(items), cols_per_row):
        cols = st.columns(cols_per_row)
        for col, rec in zip(cols, items[i:i + cols_per_row]):
            with col:
                if rec.get("image_url"):
                    col.markdown(
                        f'<a href="{rec["url"]}" target="_blank">'
                        f'<img src="{rec["image_url"]}" style="width:100%;border-radius:6px;"/></a>',
                        unsafe_allow_html=True,
                    )
                title = (rec.get("title_zh") or rec.get("title_orig") or "")[:40]
                col.markdown(
                    f"**[{rec['region']}] -{rec['discount_pct']:.0f}%**  \n"
                    f"<small>{title}</small>  \n"
                    f"~~NT${rec['original_price'] or '-'}~~ → **NT${rec['sale_price']:,}**",
                    unsafe_allow_html=True,
                )

with tab2:
    st.subheader("折扣率分布 (top 30)")
    chart_df = df.head(30).copy()
    chart_df["label"] = chart_df["title_zh"].fillna(chart_df["title_orig"]).str.slice(0, 25)
    st.bar_chart(chart_df.set_index("label")["discount_pct"], height=500)

    st.subheader("每日新增筆數")
    by_day = df.groupby("scrape_date").size().rename("筆數")
    st.bar_chart(by_day)

with tab3:
    st.dataframe(df, use_container_width=True, height=600)


# ----------- 匯出 -----------
st.subheader("匯出")
ex_col1, ex_col2 = st.columns(2)

with ex_col1:
    csv = display.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "下載 CSV",
        data=csv,
        file_name=f"coupang_deals_{date.today().isoformat()}.csv",
        mime="text/csv",
    )

with ex_col2:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        display.to_excel(w, index=False, sheet_name="deals")
    st.download_button(
        "下載 Excel",
        data=buf.getvalue(),
        file_name=f"coupang_deals_{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
