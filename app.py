# app.py
# -*- coding: utf-8 -*-

import datetime
import html
import sys
from dataclasses import dataclass
from typing import List, Optional

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

st.set_page_config(
    page_title="香港新聞聚合中心",
    layout="wide",
    page_icon="🗞️",
)

# =====================
# CSS（簡潔、穩定）
# =====================
st.markdown(
    """
<style>
body { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

.section-title {
  font-size: 1.1rem;
  font-weight: 800;
  margin-bottom: 6px;
}

.card {
  background:#fff;
  border:1px solid #e5e7eb;
  border-radius:12px;
  padding:12px;
  height:520px;
  display:flex;
  flex-direction:column;
}

.items {
  overflow-y:auto;
  padding-right:6px;
  flex:1;
}

.item {
  background:#fff;
  border-left:4px solid #3b82f6;
  border-radius:8px;
  padding:8px 10px;
  margin:8px 0;
}

.item a {
  text-decoration:none;
  color:#111827;
  font-weight:600;
  line-height:1.35;
}

.item a:hover { color:#ef4444; }

.item-meta {
  font-size:0.78rem;
  color:#6b7280;
  font-family:monospace;
  margin-top:2px;
}

.empty {
  color:#9ca3af;
  text-align:center;
  margin-top:20px;
}
</style>
""",
    unsafe_allow_html=True,
)

# =====================
# Data model
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

@st.cache_data(ttl=60)
def fetch_today(url: str, color: str, limit: int = 10) -> List[Article]:
    feed = feedparser.parse(url)
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

    # 有可判斷日期的今日新聞 → 用它
    if dated:
        return dated[:limit]

    # 否則 fallback：直接用最新 10 條（顯示為「今日」）
    return undated[:limit]

def render_articles(articles: List[Article]):
    if not articles:
        st.markdown("<div class='empty'>今日暫無新聞</div>", unsafe_allow_html=True)
        return

    for a in articles:
        st.markdown(
            f"""
            <div class="item" style="border-left-color:{a.color}">
              <a href="{a.link}" target="_blank">{a.title}</a>
              <div class="item-meta">🕐 {a.time_str}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# =====================
# RSS / RSSHub URLs
# =====================
RSSHUB = "https://rsshub-production-9dfc.up.railway.app"

GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"
CR = f"{RSSHUB}/telegram/channel/cr881903"

# 其他媒體（第二排）
HK01 = f"{RSSHUB}/hk01/latest"
ONCC = f"{RSSHUB}/oncc/zh-hant/news"

# =====================
# UI
# =====================
st.title("🗞️ 香港新聞聚合中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

if st.toggle("每分鐘自動更新", value=True):
    st_autorefresh(interval=60_000, key="auto")

# ========= 第一排（你畫的那一排） =========
row1 = st.columns(4)

with row1[0]:
    st.markdown("<div class='section-title'>政府新聞（中文）</div>", unsafe_allow_html=True)
    st.markdown("<div class='card'><div class='items'>", unsafe_allow_html=True)
    render_articles(fetch_today(GOV_ZH, "#E74C3C"))
    st.markdown("</div></div>", unsafe_allow_html=True)

with row1[1]:
    st.markdown("<div class='section-title'>政府新聞（英文）</div>", unsafe_allow_html=True)
    st.markdown("<div class='card'><div class='items'>", unsafe_allow_html=True)
    render_articles(fetch_today(GOV_EN, "#C0392B"))
    st.markdown("</div></div>", unsafe_allow_html=True)

with row1[2]:
    st.markdown("<div class='section-title'>RTHK</div>", unsafe_allow_html=True)
    st.markdown("<div class='card'><div class='items'>", unsafe_allow_html=True)
    render_articles(fetch_today(RTHK, "#FF9800"))
    st.markdown("</div></div>", unsafe_allow_html=True)

with row1[3]:
    st.markdown("<div class='section-title'>商業電台</div>", unsafe_allow_html=True)
    st.markdown("<div class='card'><div class='items'>", unsafe_allow_html=True)
    render_articles(fetch_today(CR, "#2563EB"))
    st.markdown("</div></div>", unsafe_allow_html=True)

# ========= 第二排（其他媒體） =========
st.markdown("---")
st.subheader("其他新聞媒體")

row2 = st.columns(2)

with row2[0]:
    st.markdown("<div class='section-title'>HK01</div>", unsafe_allow_html=True)
    st.markdown("<div class='card'><div class='items'>", unsafe_allow_html=True)
    render_articles(fetch_today(HK01, "#1F4E79"))
    st.markdown("</div></div>", unsafe_allow_html=True)

with row2[1]:
    st.markdown("<div class='section-title'>on.cc</div>", unsafe_allow_html=True)
    st.markdown("<div class='card'><div class='items'>", unsafe_allow_html=True)
    render_articles(fetch_today(ONCC, "#EF4444"))
    st.markdown("</div></div>", unsafe_allow_html=True)
