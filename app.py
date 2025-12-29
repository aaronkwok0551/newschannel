# app.py
# -*- coding: utf-8 -*-

import datetime
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

import feedparser
import pytz
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# -----------------------
# Encoding / TZ
# -----------------------
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HK_TZ = pytz.timezone("Asia/Hong_Kong")

# -----------------------
# Page config
# -----------------------
st.set_page_config(page_title="香港新聞聚合中心", layout="wide", page_icon="📰")

# -----------------------
# CSS (5 columns aligned; each card scrolls; no jagged)
# -----------------------
st.markdown(
    """
<style>
body { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

.source-card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 12px 12px 10px 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  height: 520px;
  display: flex;
  flex-direction: column;
}

.source-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.source-title {
  font-weight: 800;
  font-size: 1.02rem;
  color: #111827;
  line-height: 1.2;
}

.source-badges { white-space: nowrap; }

.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.75rem;
  border: 1px solid #e5e7eb;
  margin-left: 6px;
  color: #111827;
  background: #f9fafb;
}
.badge-official { background: #ecfeff; border-color: #a5f3fc; }
.badge-rsshub { background: #f5f3ff; border-color: #ddd6fe; }
.badge-telegram { background: #eff6ff; border-color: #bfdbfe; }
.badge-google { background: #fff7ed; border-color: #fed7aa; }

.source-meta {
  font-size: 0.80rem;
  color: #6b7280;
  margin-bottom: 8px;
}

.items {
  overflow-y: auto;
  padding-right: 6px;
  flex: 1;
}

.item {
  background: #ffffff;
  border-left: 4px solid #3b82f6;
  border-radius: 10px;
  padding: 9px 10px;
  margin: 8px 0;
  transition: all 0.14s ease;
}
.item:hover {
  transform: translateX(2px);
  box-shadow: 0 2px 10px rgba(0,0,0,0.08);
  border-left-color: #ef4444;
}

.item a {
  text-decoration: none;
  color: #111827;
  font-weight: 600;
  line-height: 1.35;
  display: block;
}
.item a:hover { color: #ef4444; }

.item-meta {
  margin-top: 3px;
  font-size: 0.78rem;
  color: #6b7280;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono","Courier New", monospace;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.new-tag {
  display: inline-block;
  background: #16a34a;
  color: #ffffff;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 800;
}

.empty {
  color: #9ca3af;
  text-align: center;
  padding: 22px 10px;
}
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------
# Data model
# -----------------------
@dataclass
class Article:
    source: str
    title: str
    link: str
    timestamp: datetime.datetime
    time_str: str
    color: str
    is_new: bool = False


# -----------------------
# Helpers
# -----------------------
def now_hk() -> datetime.datetime:
    return datetime.datetime.now(HK_TZ)


def is_today_hk(dt: datetime.datetime) -> bool:
    return dt.astimezone(HK_TZ).date() == now_hk().date()


def clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<.*?>", "", s)
    return " ".join(s.strip().split())


def parse_entry_time(entry) -> Optional[datetime.datetime]:
    """
    Prefer published_parsed, then updated_parsed.
    Return HK timezone datetime, or None if missing.
    """
    struct_time = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        struct_time = entry.published_parsed
    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
        struct_time = entry.updated_parsed

    if not struct_time:
        return None

    dt_utc = datetime.datetime(*struct_time[:6], tzinfo=pytz.utc)
    return dt_utc.astimezone(HK_TZ)


def format_hhmm(dt: datetime.datetime) -> str:
    return dt.astimezone(HK_TZ).strftime("%H:%M")


def mark_new(source_key: str, articles: List[Article]) -> List[Article]:
    """
    Mark 'NEW' if link not seen before (per browser session).
    """
    if "seen_links" not in st.session_state:
        st.session_state["seen_links"] = {}

    seen_links: Dict[str, Dict[str, bool]] = st.session_state["seen_links"]
    if source_key not in seen_links:
        seen_links[source_key] = {}

    bucket = seen_links[source_key]
    for a in articles:
        if a.link and a.link not in bucket:
            a.is_new = True
            bucket[a.link] = True

    st.session_state["seen_links"] = seen_links
    return articles


# -----------------------
# RSS fetcher (cached)
# -----------------------
@st.cache_data(ttl=55, show_spinner=False)
def fetch_rss_today(source_name: str, url: str, color: str, limit: int = 10) -> List[Article]:
    """
    Fetch RSS and return today's latest items, sorted desc, up to limit.
    Strict rule: if timestamp missing -> skip (enforces '只顯示今日').
    """
    out: List[Article] = []
    feed = feedparser.parse(url)
    entries = getattr(feed, "entries", None) or []

    for e in entries:
        title = clean_text(getattr(e, "title", "") or "")
        link = getattr(e, "link", "") or ""
        if not title or not link:
            continue

        dt = parse_entry_time(e)
        if not dt:
            continue
        if not is_today_hk(dt):
            continue

        out.append(
            Article(
                source=source_name,
                title=title,
                link=link,
                timestamp=dt,
                time_str=format_hhmm(dt),
                color=color,
            )
        )

    # sort + dedup by link
    out.sort(key=lambda x: x.timestamp, reverse=True)
    dedup: Dict[str, Article] = {}
    for a in out:
        if a.link not in dedup:
            dedup[a.link] = a

    out = list(dedup.values())
    out.sort(key=lambda x: x.timestamp, reverse=True)
    return out[:limit]


# -----------------------
# Sources
# -----------------------
# Put your RSSHub base in Streamlit secrets:
#   RSSHUB_BASE = "https://YOUR-RSSHUB.up.railway.app"
RSSHUB_BASE = ""
try:
    RSSHUB_BASE = (st.secrets.get("RSSHUB_BASE", "") or "").rstrip("/")
except Exception:
    RSSHUB_BASE = ""

# You can hardcode instead:
# RSSHUB_BASE = "https://YOUR-RSSHUB.up.railway.app"

OFFICIAL = [
    ("政府新聞（中）", "https://www.info.gov.hk/gia/rss/general_zh.xml", "#E74C3C", "官方RSS"),
    ("政府新聞（英）", "https://www.info.gov.hk/gia/rss/general_en.xml", "#C0392B", "官方RSS"),
    ("RTHK（本地）", "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "#FF9800", "官方RSS"),
    ("經濟日報 HKET（港聞）", "https://www.hket.com/rss/hongkong", "#111827", "官方RSS"),
    ("明報（即時）", "https://news.mingpao.com/rss/ins/s00001.xml", "#6B7280", "官方RSS"),
]

# RSSHub + Telegram + (fallback) Google News
# - on.cc 你已確認可用：/oncc/zh-hant/news
# - 星島：你未找到 RSSHub route，先用 Google News RSS（可後續替換成官方 RSS 或自訂 RSSHub route）
RSSHUB_AND_OTHERS = [
    ("HK01（RSSHub）", f"{RSSHUB_BASE}/hk01/latest" if RSSHUB_BASE else "", "#1F4E79", "RSSHub"),
    ("on.cc（即時｜RSSHub）", f"{RSSHUB_BASE}/oncc/zh-hant/news" if RSSHUB_BASE else "", "#ef4444", "RSSHub"),
    ("商業電台（Telegram｜RSSHub）", f"{RSSHUB_BASE}/telegram/channel/cr881903" if RSSHUB_BASE else "", "#2563eb", "Telegram"),
    (
        "星島（即時｜Google News 備援）",
        "https://news.google.com/rss/search?q=%E6%98%9F%E5%B3%B6%20(%E5%8D%B3%E6%99%82%20OR%20%E6%96%B0%E8%81%9E)&hl=zh-HK&gl=HK&ceid=HK:zh-Hant",
        "#374151",
        "Google",
    ),
]


# -----------------------
# UI controls
# -----------------------
st.title("🗞️ 香港新聞聚合中心")
st.caption(f"最後更新（香港時間）: {now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

left, right = st.columns([1, 1])
with left:
    auto_refresh = st.toggle("每分鐘自動更新", value=True)
with right:
    if st.button("🔄 立即刷新", type="primary"):
        st.cache_data.clear()
        st.rerun()

if auto_refresh:
    st_autorefresh(interval=60_000, key="autorefresh_60s")

st.markdown("---")


# -----------------------
# Render helpers
# -----------------------
def badge_html(kind: str) -> str:
    if kind == "官方RSS":
        return '<span class="badge badge-official">官方RSS</span>'
    if kind == "Telegram":
        return '<span class="badge badge-telegram">Telegram</span>'
    if kind == "Google":
        return '<span class="badge badge-google">非官方聚合</span>'
    return '<span class="badge badge-rsshub">RSSHub</span>'


def render_card(source_key: str, name: str, url: str, color: str, kind: str, limit: int = 10) -> str:
    if not url:
        # only RSSHub items should reach here; show a clear instruction
        return f"""
        <div class="source-card">
          <div class="source-head">
            <div class="source-title">{name}</div>
            <div class="source-badges">{badge_html(kind)}</div>
          </div>
          <div class="source-meta">未設定 RSSHUB_BASE（此來源需要 RSSHub）</div>
          <div class="items"><div class="empty">請先在 Streamlit secrets 或程式內設定 RSSHUB_BASE</div></div>
        </div>
        """

    try:
        arts = fetch_rss_today(name, url, color, limit=limit)
    except Exception as e:
        return f"""
        <div class="source-card">
          <div class="source-head">
            <div class="source-title">{name}</div>
            <div class="source-badges">{badge_html(kind)}</div>
          </div>
          <div class="source-meta">讀取失敗：{clean_text(str(e))}</div>
          <div class="items"><div class="empty">請稍後再試</div></div>
        </div>
        """

    arts = mark_new(source_key, arts)

    meta = f"{kind} · 今日 {len(arts)} 條 · 顯示最新 {limit} 條"
    if kind == "Google":
        meta = f"{kind}（備援） · 今日 {len(arts)} 條 · 顯示最新 {limit} 條"

    if not arts:
        items_html = "<div class='empty'>今日暫無新聞</div>"
    else:
        items_html = ""
        for a in arts:
            new = "<span class='new-tag'>NEW</span>" if a.is_new else ""
            items_html += f"""
            <div class="item" style="border-left-color:{a.color};">
              <a href="{a.link}" target="_blank" rel="noopener noreferrer">{a.title}</a>
              <div class="item-meta">🕐 {a.time_str} {new}</div>
            </div>
            """

    return f"""
    <div class="source-card">
      <div class="source-head">
        <div class="source-title">{name}</div>
        <div class="source-badges">{badge_html(kind)}</div>
      </div>
      <div class="source-meta">{meta}</div>
      <div class="items">{items_html}</div>
    </div>
    """


# -----------------------
# Main display (5 columns)
# -----------------------
LIMIT_PER_SOURCE = 10

st.subheader("官方 RSS（只顯示今日 · 每來源 10 條）")
official_cols = st.columns(5)
for i, (name, url, color, kind) in enumerate(OFFICIAL):
    with official_cols[i % 5]:
        st.markdown(
            render_card(f"official_{i}", name, url, color, kind, limit=LIMIT_PER_SOURCE),
            unsafe_allow_html=True,
        )

st.markdown("---")

st.subheader("RSSHub / Telegram / 備援（只顯示今日 · 每來源 10 條）")
other_cols = st.columns(5)
for i, (name, url, color, kind) in enumerate(RSSHUB_AND_OTHERS):
    with other_cols[i % 5]:
        st.markdown(
            render_card(f"other_{i}", name, url, color, kind, limit=LIMIT_PER_SOURCE),
            unsafe_allow_html=True,
        )

st.caption(
    "提示：如某來源長期顯示「今日暫無新聞」，通常是該 RSS 沒有提供可解析的發佈時間，"
    "或該來源今天未更新。若你想把規則改為「最近 24 小時」會更寬鬆。"
)
