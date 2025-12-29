# -*- coding: utf-8 -*-
import datetime
import re
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import feedparser
import pytz
import requests
import streamlit as st
from bs4 import BeautifulSoup

# -----------------------
# Runtime / Encoding
# -----------------------
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

hk_tz = pytz.timezone("Asia/Hong_Kong")

# -----------------------
# Streamlit Page Config
# -----------------------
st.set_page_config(page_title="Tommy Sir後援會之新聞中心", layout="wide", page_icon="📰")

# -----------------------
# CSS
# -----------------------
st.markdown(
    """
<style>
body { font-family: "Microsoft JhengHei", "PingFang TC", sans-serif; }
.section-wrap { padding: 16px; border-radius: 12px; margin-bottom: 18px; }
.section-gov { background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); }
.section-core { background: #f8f9fa; }
.section-others { background: #f6f7fb; }

.source-header {
  font-size: 1.05em; font-weight: 700;
  margin: 0 0 10px 0; padding: 8px 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white; border-radius: 8px; display: inline-block;
}

.news-item {
  padding: 10px 12px; margin: 6px 0;
  background: white; border-left: 4px solid #3498db;
  border-radius: 8px; transition: all 0.18s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.news-item:hover {
  transform: translateX(3px);
  box-shadow: 0 3px 10px rgba(0,0,0,0.10);
  border-left-color: #e74c3c;
}
.news-title {
  font-size: 1rem; font-weight: 550;
  color: #1f2937; text-decoration: none;
  line-height: 1.45; display: block; margin-bottom: 4px;
}
.news-title:hover { color: #e74c3c; }
.news-meta { font-size: 0.85rem; color: #6b7280; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }

.badge {
  display: inline-block; padding: 2px 8px; border-radius: 999px;
  background: #111827; color: #fff; font-size: 0.78rem; margin-left: 8px;
}
.badge-warn { background: #b45309; }
hr { border: none; border-top: 1px solid #e5e7eb; margin: 14px 0; }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------
# Helpers
# -----------------------
def clean_html_text(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"<.*?>", "", text)
    return " ".join(text.split())


def safe_get(url: str, timeout: int = 12) -> requests.Response:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; HKNewsAggregator/1.0; +streamlit)",
        "Accept": "*/*",
    }
    return requests.get(url, headers=headers, timeout=timeout)


def parse_entry_time(entry) -> Tuple[datetime.datetime, str]:
    """
    Return (dt_obj in HK tz, HH:MM string).
    Prefer published_parsed, then updated_parsed; fallback to now.
    """
    now_hk = datetime.datetime.now(hk_tz)

    struct_time = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        struct_time = entry.published_parsed
    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
        struct_time = entry.updated_parsed

    if struct_time:
        dt_utc = datetime.datetime(*struct_time[:6], tzinfo=pytz.utc)
        dt_hk = dt_utc.astimezone(hk_tz)
        return dt_hk, dt_hk.strftime("%H:%M")

    return now_hk, "--:--"


@dataclass
class Article:
    source: str
    title: str
    link: str
    timestamp: datetime.datetime
    time_str: str
    color: str


def render_articles(articles: List[Article]) -> str:
    if not articles:
        return "<p style='color:#9ca3af; padding:14px; text-align:center;'>暫無新聞</p>"

    html = ""
    for a in articles:
        html += f"""
        <div class="news-item" style="border-left-color:{a.color};">
            <a class="news-title" href="{a.link}" target="_blank" rel="noopener noreferrer">{a.title}</a>
            <div class="news-meta">🕐 {a.time_str} · {a.source}</div>
        </div>
        """
    return html


# -----------------------
# Fetchers
# -----------------------
def fetch_rss(source_name: str, url: str, color: str, max_items: int = 20) -> List[Article]:
    articles: List[Article] = []
    try:
        feed = feedparser.parse(url)
        entries = getattr(feed, "entries", None) or []
        for entry in entries[:max_items]:
            title = clean_html_text(getattr(entry, "title", ""))
            link = getattr(entry, "link", "")
            if not title or not link:
                continue
            dt_obj, time_str = parse_entry_time(entry)
            articles.append(
                Article(
                    source=source_name,
                    title=title,
                    link=link,
                    timestamp=dt_obj,
                    time_str=time_str,
                    color=color,
                )
            )
    except Exception as e:
        st.warning(f"[RSS] {source_name} 讀取失敗：{e}")

    articles.sort(key=lambda x: x.timestamp, reverse=True)
    return articles


def fetch_hk01_json(source_name: str, url: str, color: str, max_items: int = 20) -> List[Article]:
    """
    HK01 提供 JSON feed（非 RSS）。結構可能變動，採多路徑保守解析。
    """
    articles: List[Article] = []
    now_hk = datetime.datetime.now(hk_tz)

    try:
        resp = safe_get(url)
        resp.raise_for_status()
        data = resp.json()

        candidates = None
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                candidates = data["items"]
            elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("items"), list):
                candidates = data["data"]["items"]
            elif isinstance(data.get("data"), list):
                candidates = data["data"]

        if not candidates:
            return articles

        for item in candidates[:max_items]:
            if not isinstance(item, dict):
                continue
            title = clean_html_text(item.get("title") or item.get("headline") or "")
            link = item.get("url") or item.get("link") or ""
            if link and link.startswith("/"):
                link = "https://www.hk01.com" + link

            # time
            dt_obj = now_hk
            time_str = "--:--"
            ts = item.get("published_at") or item.get("created_at") or item.get("publishTime") or item.get("timestamp")

            if isinstance(ts, str):
                try:
                    dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = hk_tz.localize(dt)
                    dt_obj = dt.astimezone(hk_tz)
                    time_str = dt_obj.strftime("%H:%M")
                except Exception:
                    pass

            if title and link:
                articles.append(
                    Article(
                        source=source_name,
                        title=title,
                        link=link,
                        timestamp=dt_obj,
                        time_str=time_str,
                        color=color,
                    )
                )

    except Exception as e:
        st.warning(f"[HK01] 讀取失敗：{e}")

    articles.sort(key=lambda x: x.timestamp, reverse=True)
    return articles


def fetch_google_news_query(source_name: str, query_rss_url: str, color: str, max_items: int = 20) -> List[Article]:
    """
    Google News RSS（非官方聚合）—作為商業電台等 JS 動態站的穩定替代方案。
    """
    return fetch_rss(source_name, query_rss_url, color, max_items=max_items)


# ---- Optional: real crawler hook (Playwright) ----
def fetch_881903_playwright_stub(*args, **kwargs) -> List[Article]:
    """
    真爬蟲（Playwright）接口保留。
    Railway 上要跑這個通常需要：
    - 安裝 playwright + browsers
    - 額外系統依賴
    你決定要啟用時，我再把完整版本給你。
    """
    return []


# -----------------------
# Source Configuration
# -----------------------
# 政府（官方 RSS）
GOV_FEEDS = [
    ("政府新聞 (中)", "https://www.info.gov.hk/gia/rss/general_zh.xml", "#E74C3C"),
    ("Gov News (En)", "https://www.info.gov.hk/gia/rss/general_en.xml", "#C0392B"),
]

# 核心你指定的第二、第三順位
RTHK_FEED = ("香港電台 RTHK（本地）", "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "#FF9800")

# 商業電台：預設用 Google News RSS 聚合（非官方）
COMMERCIAL_RADIO_FALLBACK = (
    "商業電台 881/903（非官方聚合）",
    "https://news.google.com/rss/search?q=881903%20OR%20%E5%95%86%E6%A5%AD%E9%9B%BB%E5%8F%B0%20OR%20%E5%8F%B1%E5%90%92903&hl=zh-HK&gl=HK&ceid=HK:zh-Hant",
    "#F59E0B",
)

# 其他媒體（多數有站方 RSS/Feed；若來源日後失效，你可直接改 URL）
OTHER_SOURCES: List[Tuple[str, str, str, str]] = [
    # (name, url, color, type)
    ("TVB 新聞（本地）", "https://news.tvb.com/rss/local.xml", "#10B981", "rss"),
    ("Now 新聞（本地）", "https://news.now.com/rss/local", "#3B82F6", "rss"),
    ("有線新聞 i-Cable", "https://www.i-cable.com/feed/", "#EF4444", "rss"),
    ("HK01", "https://web-data.api.hk01.com/v2/feed/category/0", "#1F4E79", "hk01"),
    # 你也可以加更多 Google News 搜尋聚合（非官方）
    ("明報（非官方聚合）", "https://news.google.com/rss/search?q=%E6%98%8E%E5%A0%B1&hl=zh-HK&gl=HK&ceid=HK:zh-Hant", "#6B7280", "google"),
    ("星島（非官方聚合）", "https://news.google.com/rss/search?q=%E6%98%9F%E5%B3%B6&hl=zh-HK&gl=HK&ceid=HK:zh-Hant", "#6B7280", "google"),
]

ICON_MAP: Dict[str, str] = {
    "政府": "🏛️",
    "RTHK": "📻",
    "商業電台": "📻",
    "TVB": "📺",
    "Now": "📺",
    "有線": "📺",
    "HK01": "📱",
}

# -----------------------
# Cached Fetch Wrapper
# -----------------------
Fetcher = Callable[[str, str, str, int], List[Article]]

@st.cache_data(ttl=60, show_spinner=False)
def get_articles_cached(fetcher_key: str, source_name: str, url: str, color: str, max_items: int) -> List[Article]:
    if fetcher_key == "rss":
        return fetch_rss(source_name, url, color, max_items=max_items)
    if fetcher_key == "hk01":
        return fetch_hk01_json(source_name, url, color, max_items=max_items)
    if fetcher_key == "google":
        return fetch_google_news_query(source_name, url, color, max_items=max_items)
    if fetcher_key == "881903_pw":
        return fetch_881903_playwright_stub(source_name, url, color, max_items=max_items)
    return []


# -----------------------
# UI
# -----------------------
st.title("🗞️ Tommy Sir後援會之新聞中心")
st.caption(f"最後更新（香港時間）: {datetime.datetime.now(hk_tz).strftime('%Y-%m-%d %H:%M:%S')}")

col_a, col_b = st.columns([1, 1])
with col_a:
    max_items_per_source = st.slider("每個來源最多顯示條數", min_value=5, max_value=40, value=18, step=1)
with col_b:
    if st.button("🔄 立即刷新", type="primary"):
        st.cache_data.clear()
        st.rerun()

st.markdown("<hr/>", unsafe_allow_html=True)

# ========== 1) 政府新聞（中英合併，按時間排序） ==========
st.markdown('<div class="section-wrap section-gov">', unsafe_allow_html=True)
st.markdown("### 🏛️ 政府新聞與公告（中英合併，按時間排序）")

with st.spinner("讀取政府 RSS 中..."):
    merged: List[Article] = []
    for (name, url, color) in GOV_FEEDS:
        merged.extend(get_articles_cached("rss", name, url, color, max_items=max_items_per_source))
    merged.sort(key=lambda x: x.timestamp, reverse=True)
    st.markdown(render_articles(merged), unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)
st.markdown("<hr/>", unsafe_allow_html=True)

# ========== 2) RTHK ==========
st.markdown('<div class="section-wrap section-core">', unsafe_allow_html=True)
st.markdown("### 📻 香港電台 RTHK（按時間排序）")

with st.spinner("讀取 RTHK RSS 中..."):
    name, url, color = RTHK_FEED
    rthk_articles = get_articles_cached("rss", name, url, color, max_items=max_items_per_source)
    st.markdown(render_articles(rthk_articles), unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)
st.markdown("<hr/>", unsafe_allow_html=True)

# ========== 3) 商業電台 ==========
st.markdown('<div class="section-wrap section-core">', unsafe_allow_html=True)
st.markdown("### 📻 商業電台（按時間排序）")
st.markdown(
    "<div style='margin:-6px 0 10px 0; color:#92400e;'>"
    "目前使用 <b>非官方聚合 RSS</b>（Google News）作穩定來源；如你要改成 <b>Playwright 真爬蟲</b>（抓 881903 網站），我可以再提供升級版。</div>",
    unsafe_allow_html=True,
)

with st.spinner("讀取商業電台來源中..."):
    name, url, color = COMMERCIAL_RADIO_FALLBACK
    cr_articles = get_articles_cached("google", name, url, color, max_items=max_items_per_source)
    st.markdown(render_articles(cr_articles), unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)
st.markdown("<hr/>", unsafe_allow_html=True)

# ========== 4) 其他媒體 ==========
st.markdown('<div class="section-wrap section-others">', unsafe_allow_html=True)
st.markdown("### 📰 其他新聞平台（各自按時間排序）")

# 用 3 欄網格展示
grid_cols = st.columns(3)
for idx, (name, url, color, typ) in enumerate(OTHER_SOURCES):
    with grid_cols[idx % 3]:
        icon = "📰"
        for k, v in ICON_MAP.items():
            if k in name:
                icon = v
                break

        badge = ""
        if typ == "google":
            badge = '<span class="badge badge-warn">非官方聚合</span>'
        elif typ == "rss":
            badge = '<span class="badge">RSS</span>'
        elif typ == "hk01":
            badge = '<span class="badge">JSON</span>'

        st.markdown(f'<div class="source-header">{icon} {name}{badge}</div>', unsafe_allow_html=True)
        with st.spinner("讀取中..."):
            arts = get_articles_cached(typ, name, url, color, max_items=max_items_per_source)
            st.markdown(render_articles(arts), unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)

# Footer
st.caption("提示：若個別來源長期顯示「暫無新聞」，多半是來源 URL 失效或站方改版；你只需更新該來源的 URL 即可。")
