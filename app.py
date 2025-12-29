# app.py
# -*- coding: utf-8 -*-

import datetime
import html
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

import feedparser
import pytz
import streamlit as st
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from streamlit_autorefresh import st_autorefresh

# -----------------------
# Basic setup
# -----------------------
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

# -----------------------
# CSS
# -----------------------
st.markdown(
    """
<style>
body { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

.card {
  background:#fff;border:1px solid #e5e7eb;border-radius:12px;
  padding:12px;height:520px;display:flex;flex-direction:column;
}
.card h3 { margin:0 0 6px 0; font-size:1.05rem; }

.meta { font-size:0.8rem;color:#6b7280;margin-bottom:6px; }

.items { overflow-y:auto; padding-right:6px; flex:1; }

.item {
  background:#fff;border-left:4px solid #3b82f6;border-radius:8px;
  padding:8px 10px;margin:8px 0;
}
.item a {
  text-decoration:none;color:#111827;font-weight:600;line-height:1.35;
}
.item a:hover { color:#ef4444; }

.item-meta {
  font-size:0.78rem;color:#6b7280;
  font-family:monospace;margin-top:2px;
}

.new {
  background:#16a34a;color:#fff;
  padding:1px 6px;border-radius:999px;
  font-size:0.7rem;font-weight:700;margin-left:6px;
}

.empty { color:#9ca3af;text-align:center;margin-top:20px; }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------
# Data model
# -----------------------
@dataclass
class Article:
    title: str
    link: str
    dt: Optional[datetime.datetime]
    time_str: str
    color: str
    is_new: bool = False

# -----------------------
# Helpers
# -----------------------
def now_hk():
    return datetime.datetime.now(HK_TZ)

def is_today(dt: datetime.datetime) -> bool:
    return dt.astimezone(HK_TZ).date() == now_hk().date()

def clean_text(raw: str) -> str:
    if not raw:
        return ""
    raw = html.unescape(raw)
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    return " ".join(text.split())

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

# -----------------------
# Fetch RSS (core logic)
# -----------------------
@st.cache_data(ttl=60)
def fetch_articles(name: str, url: str, color: str, limit: int = 10) -> List[Article]:
    feed = feedparser.parse(url)
    entries = feed.entries or []

    articles: List[Article] = []
    undated: List[Article] = []

    for e in entries:
        title = clean_text(getattr(e, "title", ""))
        link = getattr(e, "link", "")
        if not title or not link:
            continue

        dt = parse_time(e)

        if dt:
            if is_today(dt):
                articles.append(
                    Article(
                        title=title,
                        link=link,
                        dt=dt,
                        time_str=dt.strftime("%H:%M"),
                        color=color,
                    )
                )
        else:
            undated.append(
                Article(
                    title=title,
                    link=link,
                    dt=None,
                    time_str="今日",
                    color=color,
                )
            )

    # 如果有「可判斷日期」的今日新聞 → 用它
    if articles:
        articles.sort(key=lambda x: x.dt, reverse=True)
        return articles[:limit]

    # 否則 fallback：取最新 10 條（無日期來源）
    return undated[:limit]

# -----------------------
# Render helpers (SAFE)
# -----------------------
def render_items(articles: List[Article], key: str):
    if "seen" not in st.session_state:
        st.session_state["seen"] = {}

    seen = st.session_state["seen"].setdefault(key, set())

    if not articles:
        st.markdown("<div class='empty'>今日暫無新聞</div>", unsafe_allow_html=True)
        return

    for a in articles:
        is_new = a.link not in seen
        seen.add(a.link)

        new_tag = "<span class='new'>NEW</span>" if is_new else ""
        st.markdown(
            f"""
            <div class="item" style="border-left-color:{a.color}">
              <a href="{a.link}" target="_blank">{a.title}</a>
              <div class="item-meta">🕐 {a.time_str} {new_tag}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# -----------------------
# Sources
# -----------------------
RSSHUB = "https://rsshub-production-9dfc.up.railway.app"

SOURCES = [
    ("政府新聞", "https://www.info.gov.hk/gia/rss/general_zh.xml", "#E74C3C"),
    ("RTHK", "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "#FF9800"),
    ("HK01", f"{RSSHUB}/hk01/latest", "#1F4E79"),
    ("on.cc", f"{RSSHUB}/oncc/zh-hant/news", "#EF4444"),
    ("商業電台", f"{RSSHUB}/telegram/channel/cr881903", "#2563EB"),
]

# -----------------------
# UI
# -----------------------
st.title("🗞️ 香港新聞聚合中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

if st.toggle("每分鐘自動更新", value=True):
    st_autorefresh(interval=60_000, key="auto")

cols = st.columns(5)

for idx, (name, url, color) in enumerate(SOURCES):
    with cols[idx]:
        st.markdown(f"<div class='card'><h3>{name}</h3>", unsafe_allow_html=True)
        st.markdown("<div class='items'>", unsafe_allow_html=True)

        articles = fetch_articles(name, url, color)
        render_items(articles, name)

        st.markdown("</div></div>", unsafe_allow_html=True)
