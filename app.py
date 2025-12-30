import os
import re
from datetime import datetime, timezone, timedelta

import requests
import streamlit as st
import feedparser

# ---------------------------
# Basic config
# ---------------------------
st.set_page_config(page_title="香港新聞聚合中心", layout="wide")

HKT = timezone(timedelta(hours=8))

DEFAULT_RSSHUB_BASE = os.getenv("RSSHUB_BASE", "https://rsshub-production-9dfc.up.railway.app").rstrip("/")
DEFAULT_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "12"))

# ---------------------------
# Helpers
# ---------------------------
def is_probably_html(text: str) -> bool:
    """Detect if response looks like HTML instead of RSS/XML."""
    if not text:
        return False
    head = text[:2000].lower()
    return ("<html" in head) or ("<!doctype html" in head) or ("<div" in head)

def safe_get(url: str, timeout: int = DEFAULT_TIMEOUT) -> requests.Response:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NewsAggregator/1.0; +https://example.com)",
        "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.7",
    }
    return requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)

def parse_feed_from_url(url: str) -> tuple[list[dict], str | None]:
    """
    Return (items, error). Items are list of dict(title, link, published, is_new).
    """
    try:
        r = safe_get(url)
        if r.status_code >= 400:
            return [], f"{r.status_code} {r.reason}: {url}"

        text = r.text or ""
        if is_probably_html(text):
            return [], f"Looks like HTML (not RSS/XML): {url}"

        feed = feedparser.parse(text)

        if getattr(feed, "bozo", 0):
            # bozo_exception can be noisy; give short message
            return [], f"Feed parse error: {url}"

        entries = getattr(feed, "entries", []) or []
        items = []
        now = datetime.now(HKT)

        for e in entries[:10]:
            title = getattr(e, "title", "").strip()
            link = getattr(e, "link", "").strip()

            # published
            published_dt = None
            if getattr(e, "published_parsed", None):
                try:
                    published_dt = datetime(*e.published_parsed[:6], tzinfo=timezone.utc).astimezone(HKT)
                except Exception:
                    published_dt = None

            # NEW if within 6 hours (adjustable)
            is_new = False
            if published_dt:
                delta_hours = (now - published_dt).total_seconds() / 3600.0
                is_new = delta_hours <= 6

            items.append(
                {
                    "title": title or "(no title)",
                    "link": link,
                    "published": published_dt.strftime("%H:%M") if published_dt else "",
                    "is_new": is_new,
                }
            )

        if not items:
            return [], f"No entries: {url}"
        return items, None

    except requests.exceptions.Timeout:
        return [], f"Timeout: {url}"
    except Exception as ex:
        return [], f"Error: {url} ({type(ex).__name__})"

def rsshub(route: str, base: str) -> str:
    route = route.strip()
    if not route.startswith("/"):
        route = "/" + route
    return base.rstrip("/") + route

def render_items(items: list[dict]):
    for it in items:
        title = it["title"]
        link = it["link"]
        published = it["published"]
        is_new = it["is_new"]

        pill = " <span class='pill'>NEW</span>" if is_new else ""
        time_html = f"<span class='meta'>🕒 {published}</span>" if published else ""

        st.markdown(
            f"""
            <div class="item">
              <a href="{link}" target="_blank" rel="noopener noreferrer">{title}</a>
              <div class="meta-row">{time_html}{pill}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ---------------------------
# UI + CSS
# ---------------------------
st.markdown(
    """
<style>
  .header {font-size: 34px; font-weight: 800; margin: 0 0 6px 0;}
  .sub {color: #666; margin: 0 0 12px 0;}
  .card {
    border: 1px solid #eee;
    border-radius: 16px;
    padding: 14px 14px 10px 14px;
    background: #fff;
    min-height: 240px;
  }
  .card h3 {
    margin: 0 0 10px 0;
    font-size: 18px;
  }
  .badge {
    display: inline-block;
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 999px;
    background: #f3f3f3;
    color: #333;
    margin-left: 8px;
    vertical-align: middle;
  }
  .item { margin: 10px 0; padding-left: 10px; border-left: 4px solid #ddd;}
  .item a { text-decoration: none; }
  .item a:hover { text-decoration: underline; }
  .meta-row { margin-top: 4px; }
  .meta { color: #777; font-size: 12px; margin-right: 8px; }
  .pill {
    display: inline-block;
    font-size: 11px;
    padding: 1px 7px;
    border-radius: 999px;
    background: #2ecc71;
    color: #fff;
  }
  .err { color: #c0392b; font-size: 12px; }
  .hint { color: #666; font-size: 12px; }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown("<div class='header'>香港新聞聚合中心</div>", unsafe_allow_html=True)
st.markdown(
    f"<div class='sub'>最後更新（香港時間）：{datetime.now(HKT).strftime('%Y-%m-%d %H:%M:%S')}</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.write("設定")
    rsshub_base = st.text_input("https://rsshub-production-9dfc.up.railway.app/", DEFAULT_RSSHUB_BASE).rstrip("/")
    auto_refresh = st.toggle("每分鐘自動更新", value=True)
    show_today_only = st.toggle("只顯示今日（如來源支援）", value=False)
    st.caption("提示：Now / RTHK 建議用 RSSHub。政府 RSS 可以直連。")

# Auto refresh
if auto_refresh:
    st.markdown(
        "<meta http-equiv='refresh' content='60'>",
        unsafe_allow_html=True,
    )

# ---------------------------
# Feeds (LOCKED + SAFE)
# ---------------------------
# Government official RSS (correct)
GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"

# RTHK: prefer RSSHub to avoid cloud blocking
# You can change route if needed, but this is stable baseline
RTHK_ROUTE = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xmls"

# Now: force RSSHub (avoid HTML being parsed)
NOW_ROUTE = "/now/news"

FEEDS = [
    {"name": "政府新聞（中）", "type": "official", "url": GOV_ZH},
    {"name": "政府新聞（英）", "type": "official", "url": GOV_EN},
    {"name": "RTHK（本地）", "type": "rsshub", "route": RTHK_ROUTE},
    {"name": "Now 新聞", "type": "rsshub", "route": NOW_ROUTE},
]

# ---------------------------
# Fetch + Render (horizontal)
# ---------------------------
cols = st.columns(len(FEEDS), gap="large")

for col, feed in zip(cols, FEEDS):
    with col:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        # Build URL
        if feed["type"] == "official":
            url = feed["url"]
            badge = "官方RSS"
        else:
            url = rsshub(feed["route"], rsshub_base)
            badge = "RSSHub"

        st.markdown(f"<h3>{feed['name']}<span class='badge'>{badge}</span></h3>", unsafe_allow_html=True)

        # Try parse
        items, err = parse_feed_from_url(url)

        # Fallback logic:
        # If official URL returns HTML/parse error, try to route via RSSHub automatically (optional)
        if err and feed["type"] == "official":
            # fallback: wrap official URL via RSSHub's generic route if you have one; if not, skip
            # Many RSSHub deployments don't provide a "generic" route; so we just show error.
            pass

        if err:
            st.markdown(f"<div class='err'>RSS fetch failed: {err}</div>", unsafe_allow_html=True)
            st.markdown("<div class='hint'>如顯示 HTML / 403 / Timeout：建議改用 RSSHub route。</div>", unsafe_allow_html=True)
        else:
            render_items(items)

        st.markdown("</div>", unsafe_allow_html=True)

st.caption("如某來源持續 403/Timeout：通常是網站封鎖雲端 IP；用 RSSHub route 會穩定得多。")
