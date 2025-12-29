# app.py
# -*- coding: utf-8 -*-

import datetime
import html
import sys
import textwrap
from dataclasses import dataclass
from typing import List, Optional, Tuple

import feedparser
import pytz
import streamlit as st
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from streamlit_autorefresh import st_autorefresh

# =====================
# 基本設定
# =====================
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HK_TZ = pytz.timezone("Asia/Hong_Kong")
st.set_page_config(page_title="香港新聞聚合中心", layout="wide", page_icon="🗞️")

# =====================
# CSS
# =====================
st.markdown(
    """
<style>
body { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

.section-title{
  font-size:1.05rem;font-weight:800;margin:2px 0 8px 0;
}

.card{
  background:#fff;border:1px solid #e5e7eb;border-radius:12px;
  padding:12px;height:520px;display:flex;flex-direction:column;
}

.items{ overflow-y:auto; padding-right:6px; flex:1; }

.item{
  background:#fff;border-left:4px solid #3b82f6;border-radius:8px;
  padding:8px 10px;margin:8px 0;
}

.item a{
  text-decoration:none;color:#111827;font-weight:600;line-height:1.35;
}
.item a:hover{ color:#ef4444; }

.item-meta{
  font-size:0.78rem;color:#6b7280;font-family:monospace;margin-top:2px;
}

.empty{ color:#9ca3af;text-align:center;margin-top:20px; }
.warn { color:#b45309; font-size:0.85rem; margin:6px 0 0 0; }
.small { color:#6b7280; font-size:0.8rem; margin:0 0 8px 0; }
</style>
""",
    unsafe_allow_html=True,
)

# =====================
# Model
# =====================
@dataclass
class Article:
    title: str
    link: str
    time_str: str
    color: str

# =====================
# Helpers
# =====================
def now_hk():
    return datetime.datetime.now(HK_TZ)

def clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    soup = BeautifulSoup(raw, "html.parser")
    return soup.get_text(" ", strip=True)

def parse_time(entry) -> Optional[datetime.datetime]:
    if getattr(entry, "published_parsed", None):
        return datetime.datetime(*entry.published_parsed[:6], tzinfo=pytz.utc).astimezone(HK_TZ)
    if getattr(entry, "updated_parsed", None):
        return datetime.datetime(*entry.updated_parsed[:6], tzinfo=pytz.utc).astimezone(HK_TZ)

    for key in ("published", "updated", "pubDate"):
        val = getattr(entry, key, None)
        if val:
            try:
                dt = dtparser.parse(str(val))
                if dt.tzinfo is None:
                    dt = HK_TZ.localize(dt)
                return dt.astimezone(HK_TZ)
            except Exception:
                pass
    return None

# =====================
# Fetchers
# =====================
@st.cache_data(ttl=60)
def fetch_today(url: str, color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    嚴格：只顯示「今日」新聞
    - 有時間：HH:MM
    - 無時間：顯示「今日」
    - 若該來源無法判斷日期：fallback 取最新10條（顯示「今日」）
    """
    try:
        feed = feedparser.parse(url)
        if getattr(feed, "bozo", 0):
            # bozo_exception 代表解析錯誤，但未必完全無 entries
            pass

        today = now_hk().date()
        dated: List[Article] = []
        undated: List[Article] = []

        for e in feed.entries or []:
            title = clean_text(getattr(e, "title", ""))
            link = getattr(e, "link", "")
            if not title or not link:
                continue

            dt = parse_time(e)
            if dt and dt.date() == today:
                dated.append(Article(title, link, dt.strftime("%H:%M"), color))
            elif not dt:
                undated.append(Article(title, link, "今日", color))

        items = (dated[:limit] if dated else undated[:limit])
        if not items:
            return [], "今日未有可顯示項目（或來源未提供可判斷日期）"
        return items, None

    except Exception as e:
        return [], f"讀取失敗：{e}"

@st.cache_data(ttl=60)
def fetch_latest_only(url: str, color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    Telegram / 非標準時間來源：
    - 不做「今日」過濾
    - 永遠取最新10條
    - 時間欄顯示「即時」
    """
    try:
        feed = feedparser.parse(url)
        out: List[Article] = []
        for e in (feed.entries or [])[:limit]:
            title = clean_text(getattr(e, "title", ""))
            link = getattr(e, "link", "")
            if not title or not link:
                continue
            out.append(Article(title, link, "即時", color))

        if not out:
            return [], "來源暫無可顯示項目（可能 route/網址錯）"
        return out, None

    except Exception as e:
        return [], f"讀取失敗：{e}"

# =====================
# Render（一次性 HTML，避免黑底 code block）
# =====================
def build_card_html(title: str, articles: List[Article], warn: Optional[str] = None) -> str:
    if not articles:
        items_html = "<div class='empty'>今日暫無新聞</div>"
    else:
        parts = []
        for a in articles:
            parts.append(
                f"""<div class="item" style="border-left-color:{a.color}">
<a href="{a.link}" target="_blank" rel="noopener noreferrer">{a.title}</a>
<div class="item-meta">🕐 {a.time_str}</div>
</div>"""
            )
        items_html = "\n".join(parts)

    warn_html = f"<div class='warn'>⚠️ {warn}</div>" if warn else ""

    html_block = f"""
<div class="section-title">{title}</div>
<div class="card">
  <div class="items">
    {items_html}
  </div>
  {warn_html}
</div>
"""
    return textwrap.dedent(html_block).lstrip()

# =====================
# URLs / Sources（由你決定，不刪減）
# =====================
RSSHUB = "https://rsshub-production-9dfc.up.railway.app"

# 第一排（固定）
GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"
CR_TG = f"{RSSHUB}/telegram/channel/cr881903"

# 你列出的其他媒體：全部保留位置（你可以逐個填 URL / RSSHub route）
# 格式：(顯示名稱, url, 顏色, fetcher_type)
# fetcher_type: "today" 或 "latest"
SOURCES_OTHERS: List[Tuple[str, str, str, str]] = [
    ("HK01（RSSHub）", f"{RSSHUB}/hk01/latest", "#1F4E79", "today"),
    ("on.cc（RSSHub 即時）", "https://rsshub.app/oncc/zh-hant/news", "#EF4444", "today"),

    # 下面係你要求清單全部保留「位置」——請你把 url 改成正確官方 RSS 或 RSSHub route
    ("Now", "", "#3B82F6", "today"),
    ("明報", "https://news.mingpao.com/rss/ins/s00001.xml", "#6B7280", "today"),
    ("星島（即時）", "", "#6B7280", "today"),
    ("TOPick（如不用可留空）", "", "#6B7280", "today"),
    ("信報即時新聞", "", "#6B7280", "today"),
    ("Cable 即時新聞", "", "#6B7280", "today"),
    ("香港商報", "", "#6B7280", "today"),
    ("文匯報", "", "#6B7280", "today"),
    ("點新聞", "", "#6B7280", "today"),
    ("大公文匯", "", "#6B7280", "today"),
    ("TVB", "", "#10B981", "today"),
]

# =====================
# UI
# =====================
st.title("🗞️ 香港新聞聚合中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

if st.toggle("每分鐘自動更新", value=True):
    st_autorefresh(interval=60_000, key="auto")

# -------- 第一排（按你畫的 4 欄）--------
row1 = st.columns(4)

with row1[0]:
    arts, warn = fetch_today(GOV_ZH, "#E74C3C")
    st.markdown(build_card_html("政府新聞（中文）", arts, warn), unsafe_allow_html=True)

with row1[1]:
    arts, warn = fetch_today(GOV_EN, "#C0392B")
    st.markdown(build_card_html("政府新聞（英文）", arts, warn), unsafe_allow_html=True)

with row1[2]:
    arts, warn = fetch_today(RTHK, "#FF9800")
    st.markdown(build_card_html("RTHK", arts, warn), unsafe_allow_html=True)

with row1[3]:
    arts, warn = fetch_latest_only(CR_TG, "#2563EB")
    st.markdown(build_card_html("商業電台（Telegram）", arts, warn), unsafe_allow_html=True)

# -------- 第二排開始：其他媒體（由你決定清單；空 URL 會顯示提示）--------
st.markdown("---")
st.subheader("其他新聞媒體（請填入 URL 或 RSSHub route）")
st.markdown("<div class='small'>提示：空白 URL 代表尚未設定；填上後就會自動顯示。</div>", unsafe_allow_html=True)

cols = st.columns(5)
col_idx = 0

for name, url, color, mode in SOURCES_OTHERS:
    with cols[col_idx % 5]:
        if not url:
            st.markdown(build_card_html(name, [], "未設定 URL / RSSHub route"), unsafe_allow_html=True)
        else:
            if mode == "latest":
                arts, warn = fetch_latest_only(url, color)
            else:
                arts, warn = fetch_today(url, color)
            st.markdown(build_card_html(name, arts, warn), unsafe_allow_html=True)

    col_idx += 1
