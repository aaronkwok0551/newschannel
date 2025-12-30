# app.py
# -*- coding: utf-8 -*-

import datetime
import html
import pytz
import feedparser
import streamlit as st
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from dataclasses import dataclass
from typing import List, Optional
from streamlit_autorefresh import st_autorefresh
import streamlit.components.v1 as components

# =====================
# 基本設定
# =====================
HK_TZ = pytz.timezone("Asia/Hong_Kong")

st.set_page_config(
    page_title="Tommy Sir 後援會之新聞中心",
    layout="wide",
)

# =====================
# CSS（一定要用）
# =====================
st.markdown("""
<style>
body { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

.section-title{
  font-size:1.1rem;
  font-weight:800;
  margin:4px 0 8px 0;
}

.card{
  background:#ffffff;
  border:1px solid #e5e7eb;
  border-radius:12px;
  padding:12px;
  height:520px;
  display:flex;
  flex-direction:column;
}

.items{
  overflow-y:auto;
  flex:1;
}

.item{
  border-left:4px solid;
  border-radius:8px;
  padding:8px 10px;
  margin:8px 0;
  background:#fff;
}

.item a{
  text-decoration:none;
  color:#111827;
  font-weight:600;
  line-height:1.4;
}

.item a:hover{ color:#dc2626; }

.item-meta{
  font-size:0.78rem;
  color:#6b7280;
  margin-top:2px;
}

.empty{
  text-align:center;
  color:#9ca3af;
  margin-top:20px;
}
</style>
""", unsafe_allow_html=True)

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
# Fetch
# =====================
@st.cache_data(ttl=60)
def fetch_today(url: str, color: str, limit: int = 10) -> List[Article]:
    feed = feedparser.parse(url)
    today = now_hk().date()
    out: List[Article] = []

    for e in feed.entries or []:
        title = clean_text(getattr(e, "title", ""))
        link = getattr(e, "link", "")
        if not title or not link:
            continue

        dt = parse_time(e)
        if dt and dt.date() == today:
            out.append(Article(title, link, dt.strftime("%H:%M"), color))

    if not out:
        out.append(Article(f"今日 {today}", "", "", color))

    return out[:limit]

# =====================
# Render
# =====================
def render_block(title: str, articles: List[Article]) -> str:
    items = []
    for a in articles:
        if a.link:
            items.append(f"""
            <div class="item" style="border-left-color:{a.color}">
              <a href="{a.link}" target="_blank">{a.title}</a>
              <div class="item-meta">🕐 {a.time_str}</div>
            </div>
            """)
        else:
            items.append(f"<div class='empty'>{a.title}</div>")

    return f"""
    <div class="section-title">{title}</div>
    <div class="card">
      <div class="items">
        {''.join(items)}
      </div>
    </div>
    """

# =====================
# RSS
# =====================
RSSHUB = "https://rsshub-production-9dfc.up.railway.app"

SOURCES = [
    ("政府新聞（中文）", "https://www.info.gov.hk/gia/rss/general_zh.xml", "#E74C3C"),
    ("政府新聞（英文）", "https://www.info.gov.hk/gia/rss/general_en.xml", "#C0392B"),
    ("RTHK", "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "#FF9800"),
    ("Now 新聞", f"{RSSHUB}/now/news", "#2563EB"),
    ("HK01", f"{RSSHUB}/hk01/latest", "#111827"),
    ("on.cc", f"{RSSHUB}/oncc/zh-hant/news", "#7C3AED"),
    ("明報", "https://news.mingpao.com/rss/pns/s00001.xml", "#059669"),
    ("信報", f"{RSSHUB}/hkej/index", "#0F766E"),
    ("星島", f"{RSSHUB}/stheadline/std/realtime", "#B45309"),
    ("TVB", f"{RSSHUB}/tvb/news/tc", "#1D4ED8"),
]

# =====================
# UI
# =====================
st.title("Tommy Sir 後援會之新聞中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

if st.toggle("每分鐘自動更新", value=True):
    st_autorefresh(interval=60_000, key="refresh")

cols = st.columns(4)
for i, (name, url, color) in enumerate(SOURCES):
    with cols[i % 4]:
        html_block = render_block(name, fetch_today(url, color))
        # 估高度：卡 520px + title/外距，先用 600；之後你想再調都得
components.html(html_block, height=600, scrolling=True)

