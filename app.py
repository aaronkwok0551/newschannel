# app.py
# -*- coding: utf-8 -*-

import datetime
import html
import sys
import textwrap
from dataclasses import dataclass
from typing import List, Optional, Tuple

import requests
from dateutil import parser as dtparser

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
st.set_page_config(page_title="Tommy Sir後援會之新聞中心", layout="wide", page_icon="🗞️")

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
.warn { color:#b45309; font-size:0.85rem; margin-top:6px; }
.small { color:#6b7280; font-size:0.8rem; }
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

NOW_API = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2"

def _safe_get_json(url: str, params: dict, timeout: int = 12) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; HKNewsAggregator/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://news.now.com/",
        "Origin": "https://news.now.com",
    }
    r = requests.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=60)
def fetch_now_local_today(color: str, limit: int = 10) -> List[Article]:
    """
    Now 新聞（本地）：
    - categoryId=119（你已在 XHR 找到）
    - 只顯示今日
    - 有時間顯示 HH:MM，無時間顯示「今日」
    """
    today = now_hk().date()
    out: List[Article] = []

    try:
        data = _safe_get_json(NOW_API, {"category": 119, "pageNo": 1}, timeout=12)

        # 保守取 list（Now 可能改 key）
        candidates = None
        if isinstance(data, dict):
            for k in ("data", "list", "news", "items", "result"):
                v = data.get(k)
                if isinstance(v, list):
                    candidates = v
                    break
            if candidates is None:
                for v in data.values():
                    if isinstance(v, dict):
                        for kk in ("data", "list", "news", "items"):
                            vv = v.get(kk)
                            if isinstance(vv, list):
                                candidates = vv
                                break
                    if candidates is not None:
                        break

        if not candidates:
            return []

        for it in candidates:
            if not isinstance(it, dict):
                continue

            title = clean_text(str(it.get("newsTitle") or it.get("title") or it.get("headline") or ""))
            link = str(it.get("shareUrl") or it.get("url") or it.get("link") or "")

            if link.startswith("/"):
                link = "https://news.now.com" + link

            time_str = "今日"
            dt = None
            raw_time = it.get("publishDate") or it.get("publishTime") or it.get("publishedAt")

            if raw_time:
                try:
                    dt = dtparser.parse(str(raw_time))
                    if dt.tzinfo is None:
                        dt = HK_TZ.localize(dt)
                    dt = dt.astimezone(HK_TZ)
                    time_str = dt.strftime("%H:%M")
                except Exception:
                    dt = None
                    time_str = "今日"

            # 今日過濾：有 dt 就嚴格比對
            if dt and dt.date() != today:
                continue

            if title and link:
                out.append(Article(title=title, link=link, time_str=time_str, color=color))

            if len(out) >= limit:
                break

        return out

    except Exception:
        return []


# =====================
@st.cache_data(ttl=60)
def fetch_today(url: str, color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    try:
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

        items = dated[:limit] if dated else undated[:limit]
        if not items:
            return [], "今日未有可顯示新聞"
        return items, None

    except Exception as e:
        return [], f"讀取失敗：{e}"

# =====================
# Render（一次性 HTML，避免黑色 code block）
# =====================
def build_card_html(title: str, articles: List[Article], warn: Optional[str] = None) -> str:
    if not articles:
        items_html = "<div class='empty'>今日暫無新聞</div>"
    else:
        items_html = "\n".join(
            f"""<div class="item" style="border-left-color:{a.color}">
<a href="{a.link}" target="_blank" rel="noopener noreferrer">{a.title}</a>
<div class="item-meta">🕐 {a.time_str}</div>
</div>"""
            for a in articles
        )

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
# RSSHub Base
# =====================
RSSHUB = "https://rsshub-production-9dfc.up.railway.app"

# =====================
# 第一排（核心來源）
# =====================
GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"
HK01 = f"{RSSHUB}/hk01/latest"

# =====================
# 其他新聞媒體（完全照你提供）
# =====================
OTHER_SOURCES = [
    ("HK01", f"{RSSHUB}/hk01/latest", "#1F4E79"),
    ("on.cc 東網", f"{RSSHUB}/oncc/zh-hant/news", "#EF4444"),
    ("Now 新聞", f"{RSSHUB}/now/news", "#3B82F6"),
    ("TVB 新聞", f"{RSSHUB}/tvb/news/tc", "#10B981"),
    ("明報", "https://news.mingpao.com/rss/ins/s00001.xml", "#6B7280"),
    ("信報即時", f"{RSSHUB}/hkej/index", "#92400e"),
    ("星島即時", f"{RSSHUB}/stheadline/std/realtime", "#6B7280"),
    ("i-CABLE 有線", f"{RSSHUB}/icable/all", "#DC2626"),
]

# =====================
# UI
# =====================
st.title("🗞️ 香港新聞聚合中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

if st.toggle("每分鐘自動更新", value=True):
    st_autorefresh(interval=60_000, key="auto")

# -------- 第一排（4 欄）--------
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
    st.markdown(build_card_html("（預留欄位）", [], "你可日後加入其他核心來源"), unsafe_allow_html=True)

    st.markdown(
        build_card_html("Now 新聞（本地）", fetch_now_local_today("#3B82F6")),
        unsafe_allow_html=True,
    )
# -------- 第二排開始：其他媒體（5 欄對齊）--------
st.markdown("---")
st.subheader("其他新聞媒體")

cols = st.columns(5)
for idx, (name, url, color) in enumerate(OTHER_SOURCES):
    with cols[idx % 5]:
        arts, warn = fetch_today(url, color)
        st.markdown(build_card_html(name, arts, warn), unsafe_allow_html=True)
