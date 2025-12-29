# -*- coding: utf-8 -*-
import datetime
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import feedparser
import pytz
import requests
import streamlit as st
from bs4 import BeautifulSoup
from streamlit_autorefresh import st_autorefresh

# -----------------------
# Runtime / Encoding
# -----------------------
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HK_TZ = pytz.timezone("Asia/Hong_Kong")


def now_hk() -> datetime.datetime:
    return datetime.datetime.now(HK_TZ)


def is_today_hk(dt_obj: datetime.datetime) -> bool:
    return dt_obj.astimezone(HK_TZ).date() == now_hk().date()


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
.section-wrap { padding: 16px; border-radius: 12px; margin-bottom: 12px; }
.section-gov { background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); }
.section-core { background: #f8f9fa; }

.source-header {
  font-size: 1.02em; font-weight: 800;
  margin: 0 0 10px 0; padding: 8px 12px;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: white; border-radius: 10px; display: inline-block;
}

.news-item {
  padding: 10px 12px; margin: 6px 0;
  background: white; border-left: 5px solid #3498db;
  border-radius: 10px; transition: all 0.18s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.news-item:hover {
  transform: translateX(3px);
  box-shadow: 0 3px 10px rgba(0,0,0,0.10);
  border-left-color: #ef4444;
}
.news-title {
  font-size: 0.97rem; font-weight: 650;
  color: #111827; text-decoration: none;
  line-height: 1.45; display: block; margin-bottom: 4px;
}
.news-title:hover { color: #ef4444; }
.news-meta {
  font-size: 0.83rem; color: #6b7280;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}
.badge-new {
  display:inline-block; margin-left:8px; padding:2px 8px;
  border-radius:999px; background:#ef4444; color:white;
  font-size:0.75rem; font-weight:800;
}
.badge-warn {
  display:inline-block; margin-left:8px; padding:2px 8px;
  border-radius:999px; background:#b45309; color:white;
  font-size:0.75rem; font-weight:800;
}
.small-note { color:#92400e; font-size:0.88rem; margin:-4px 0 10px 0; }
hr { border: none; border-top: 1px solid #e5e7eb; margin: 12px 0; }
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
def clean_html_text(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"<.*?>", "", text)
    return " ".join(text.split())


def safe_get(url: str, timeout: int = 12) -> requests.Response:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; HKNewsAggregator/3.0; +streamlit)",
        "Accept": "*/*",
        "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.7",
    }
    return requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)


def parse_entry_time_from_feed(entry) -> Tuple[datetime.datetime, str]:
    struct_time = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        struct_time = entry.published_parsed
    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
        struct_time = entry.updated_parsed

    if struct_time:
        dt_utc = datetime.datetime(*struct_time[:6], tzinfo=pytz.utc)
        dt_hk = dt_utc.astimezone(HK_TZ)
        return dt_hk, dt_hk.strftime("%H:%M")

    dt = now_hk()
    return dt, "--:--"


def extract_meta_published_time(html: str) -> Optional[datetime.datetime]:
    soup = BeautifulSoup(html, "html.parser")

    candidates: List[str] = []
    for prop in ["article:published_time", "og:updated_time", "article:modified_time"]:
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            candidates.append(tag["content"])

    for name in ["pubdate", "publishdate", "date", "parsely-pub-date"]:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            candidates.append(tag["content"])

    t = soup.find("time")
    if t and t.get("datetime"):
        candidates.append(t["datetime"])

    for s in candidates:
        s2 = s.strip().replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(s2)
            if dt.tzinfo is None:
                dt = HK_TZ.localize(dt)
            return dt.astimezone(HK_TZ)
        except Exception:
            continue

    return None


def mark_new_and_remember(source_key: str, items: List[Article]) -> List[Article]:
    if "seen_links" not in st.session_state:
        st.session_state["seen_links"] = {}  # type: ignore

    seen: Dict[str, set] = st.session_state["seen_links"]  # type: ignore
    if source_key not in seen:
        seen[source_key] = set()

    for it in items:
        it.is_new = it.link not in seen[source_key]

    for it in items:
        seen[source_key].add(it.link)

    return items


def render_articles(articles: List[Article], warn_non_official: bool = False) -> str:
    if not articles:
        return "<p style='color:#9ca3af; padding:14px; text-align:center;'>今日暫無新聞</p>"

    html = ""
    for a in articles:
        new_badge = ' <span class="badge-new">NEW</span>' if a.is_new else ""
        warn_badge = ' <span class="badge-warn">非官方聚合</span>' if warn_non_official else ""
        html += f"""
        <div class="news-item" style="border-left-color:{a.color};">
            <a class="news-title" href="{a.link}" target="_blank" rel="noopener noreferrer">{a.title}</a>
            <div class="news-meta">🕐 {a.time_str} · {a.source}{new_badge}{warn_badge}</div>
        </div>
        """
    return html


# -----------------------
# Fetchers (today only, limit N)
# -----------------------
def fetch_rss_today(source_key: str, source_name: str, url: str, color: str, limit: int = 10) -> List[Article]:
    out: List[Article] = []
    try:
        feed = feedparser.parse(url)
        entries = getattr(feed, "entries", None) or []
        for entry in entries:
            title = clean_html_text(getattr(entry, "title", ""))
            link = getattr(entry, "link", "")
            if not title or not link:
                continue

            dt_obj, time_str = parse_entry_time_from_feed(entry)
            if not is_today_hk(dt_obj):
                continue

            out.append(Article(source=source_name, title=title, link=link, timestamp=dt_obj, time_str=time_str, color=color))
            if len(out) >= limit:
                break
    except Exception as e:
        st.warning(f"[RSS] {source_name} 讀取失敗：{e}")

    out.sort(key=lambda x: x.timestamp, reverse=True)
    return mark_new_and_remember(source_key, out[:limit])


def fetch_hk01_today(source_key: str, source_name: str, url: str, color: str, limit: int = 10) -> List[Article]:
    out: List[Article] = []
    try:
        resp = safe_get(url)
        resp.raise_for_status()
        if "application/json" not in resp.headers.get("Content-Type", ""):
            return []

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
            return []

        for item in candidates:
            if not isinstance(item, dict):
                continue

            title = clean_html_text(item.get("title") or item.get("headline") or "")
            link = item.get("url") or item.get("link") or ""
            if link and link.startswith("/"):
                link = "https://www.hk01.com" + link

            ts = item.get("published_at") or item.get("created_at") or item.get("publishTime") or item.get("timestamp")
            if not isinstance(ts, str):
                continue

            dt_obj = None
            try:
                dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = HK_TZ.localize(dt)
                dt_obj = dt.astimezone(HK_TZ)
            except Exception:
                dt_obj = None

            if not dt_obj or not is_today_hk(dt_obj):
                continue

            if title and link:
                out.append(Article(source=source_name, title=title, link=link, timestamp=dt_obj, time_str=dt_obj.strftime("%H:%M"), color=color))
            if len(out) >= limit:
                break

    except Exception as e:
        st.warning(f"[HK01] 讀取失敗：{e}")

    out.sort(key=lambda x: x.timestamp, reverse=True)
    return mark_new_and_remember(source_key, out[:limit])


def fetch_google_news_today(source_key: str, source_name: str, query: str, color: str, limit: int = 10) -> List[Article]:
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    )
    items = fetch_rss_today(source_key, source_name, url, color, limit=limit)
    return items


def fetch_tvb_today_rss_then_sitemap(
    source_key: str,
    source_name: str,
    rss_url: str,
    sitemap_url: str,
    color: str,
    limit: int = 10,
) -> Tuple[List[Article], bool]:
    # returns (items, used_non_official?) -> sitemap is still "official-ish", but treat as crawler fallback (not Google)
    items = fetch_rss_today(source_key + "_rss", source_name, rss_url, color, limit=limit)
    if items:
        return items, False

    # sitemap fallback crawler
    out: List[Article] = []
    try:
        resp = safe_get(sitemap_url, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        locs: List[str] = []
        for url_node in root.findall("sm:url", ns):
            loc = url_node.findtext("sm:loc", default="", namespaces=ns)
            if loc:
                # try to prioritize TC local
                if "/tc/local/" in loc:
                    locs.append(loc)

        # fallback: if none matched, take first batch
        if not locs:
            for url_node in root.findall("sm:url", ns):
                loc = url_node.findtext("sm:loc", default="", namespaces=ns)
                if loc:
                    locs.append(loc)

        locs = locs[:80]

        for link in locs:
            try:
                page = safe_get(link, timeout=12)
                if page.status_code != 200:
                    continue
                dt = extract_meta_published_time(page.text)
                if not dt or not is_today_hk(dt):
                    continue

                soup = BeautifulSoup(page.text, "html.parser")
                title = ""
                ogt = soup.find("meta", attrs={"property": "og:title"})
                if ogt and ogt.get("content"):
                    title = ogt["content"].strip()
                if not title and soup.title and soup.title.string:
                    title = soup.title.string.strip()
                title = clean_html_text(title)
                if not title:
                    continue

                out.append(Article(source=source_name, title=title, link=link, timestamp=dt, time_str=dt.strftime("%H:%M"), color=color))
                if len(out) >= limit:
                    break
            except Exception:
                continue
    except Exception as e:
        st.warning(f"[TVB sitemap] 讀取失敗：{e}")

    out.sort(key=lambda x: x.timestamp, reverse=True)
    out = mark_new_and_remember(source_key + "_sitemap", out[:limit])
    return out, False


def fetch_now_today_html(source_key: str, source_name: str, home_url: str, color: str, limit: int = 10) -> List[Article]:
    out: List[Article] = []
    try:
        resp = safe_get(home_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        links: List[str] = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            if href.startswith("/"):
                href = "https://news.now.com" + href
            # Now news content often under /home/ or /home/local etc.
            if href.startswith("https://news.now.com/") and "/home/" in href:
                links.append(href)

        seen = set()
        dedup: List[str] = []
        for x in links:
            if x not in seen:
                seen.add(x)
                dedup.append(x)

        dedup = dedup[:120]

        for link in dedup:
            try:
                page = safe_get(link, timeout=12)
                if page.status_code != 200:
                    continue
                dt = extract_meta_published_time(page.text)
                if not dt or not is_today_hk(dt):
                    continue

                psoup = BeautifulSoup(page.text, "html.parser")
                title = ""
                ogt = psoup.find("meta", attrs={"property": "og:title"})
                if ogt and ogt.get("content"):
                    title = ogt["content"].strip()
                if not title and psoup.title and psoup.title.string:
                    title = psoup.title.string.strip()
                title = clean_html_text(title)
                if not title:
                    continue

                out.append(Article(source=source_name, title=title, link=link, timestamp=dt, time_str=dt.strftime("%H:%M"), color=color))
                if len(out) >= limit:
                    break
            except Exception:
                continue
    except Exception as e:
        st.warning(f"[Now HTML] 讀取失敗：{e}")

    out.sort(key=lambda x: x.timestamp, reverse=True)
    return mark_new_and_remember(source_key, out[:limit])


# -----------------------
# Cache wrapper (60s)
# -----------------------
@st.cache_data(ttl=60, show_spinner=False)
def cached(kind: str, args: Tuple):
    if kind == "rss_today":
        return fetch_rss_today(*args)
    if kind == "hk01_today":
        return fetch_hk01_today(*args)
    if kind == "google_today":
        return fetch_google_news_today(*args)
    if kind == "tvb_combo":
        return fetch_tvb_today_rss_then_sitemap(*args)
    if kind == "now_html":
        return fetch_now_today_html(*args)
    return []


# -----------------------
# UI Header + Auto refresh
# -----------------------
st.title("🗞️ Tommy Sir後援會之新聞中心")
st.caption(f"只顯示今日新聞（香港時間）｜最後更新：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

top_a, top_b, top_c = st.columns([1, 1, 2])
with top_a:
    limit_each = st.selectbox("每個媒體顯示", [10], index=0)
with top_b:
    auto_on = st.toggle("⏱️ 每分鐘自動更新", value=True)
with top_c:
    st.markdown("<div class='small-note'>NEW：代表本次運行首次見到的連結（會在同一個 session 內記住已出現過的連結）。</div>", unsafe_allow_html=True)

if auto_on:
    st_autorefresh(interval=60 * 1000, key="auto_refresh_60s")

if st.button("🔄 立即刷新", type="primary"):
    st.cache_data.clear()
    st.rerun()

st.markdown("<hr/>", unsafe_allow_html=True)

# -----------------------
# Government (ZH/EN separate, today only, 10 each)
# -----------------------
st.markdown('<div class="section-wrap section-gov">', unsafe_allow_html=True)
st.markdown("### 🏛️ 政府新聞與公告（中 / 英分開｜各 10 條｜只顯示今日）")

gov_zh_col, gov_en_col = st.columns(2)

with gov_zh_col:
    st.markdown('<div class="source-header">🏛️ 政府新聞（中文）</div>', unsafe_allow_html=True)
    gov_zh = cached("rss_today", ("gov_zh", "政府新聞（中文）", "https://www.info.gov.hk/gia/rss/general_zh.xml", "#E74C3C", limit_each))
    st.markdown(render_articles(gov_zh, warn_non_official=False), unsafe_allow_html=True)

with gov_en_col:
    st.markdown('<div class="source-header">🏛️ Gov News (English)</div>', unsafe_allow_html=True)
    gov_en = cached("rss_today", ("gov_en", "Gov News (English)", "https://www.info.gov.hk/gia/rss/general_en.xml", "#C0392B", limit_each))
    st.markdown(render_articles(gov_en, warn_non_official=False), unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)
st.markdown("<hr/>", unsafe_allow_html=True)

# -----------------------
# Media list you specified (5 columns grid, today only, 10 each)
# Strategy:
# - Official RSS/JSON: use those
# - Otherwise: Google News RSS with site:domain (non-official) and filter out entertainment
# -----------------------
NEG_ENT = "-娛樂 -演唱會 -音樂 -歌手 -電影 -明星 -綜藝 -劇集 -頒獎禮 -花邊 -八卦 -KOL -旅遊 -美食"
BASE_NEWS_HINT = "(新聞 OR 港聞 OR 本地 OR 時事 OR 政府 OR 立法會 OR 警方 OR 法庭 OR 交通 OR 天氣 OR 經濟 OR 財經)"


MEDIA_SOURCES = [
    # key, display_name, kind, payload, color, warn_non_official
    ("rthk", "RTHK（本地）", "rss_today", ("rthk", "RTHK（本地）", "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "#FF9800", limit_each), False),

    # 商業電台：用 Google News + 排除娛樂
    ("cr", "商業電台（新聞）", "google_today",
     ("cr", "商業電台（新聞過濾）",
      '(881903 OR "商業電台" OR "叱咤903") ' + BASE_NEWS_HINT + " " + NEG_ENT,
      "#F59E0B", limit_each),
     True),

    # HK01：JSON
    ("hk01", "HK01", "hk01_today",
     ("hk01", "HK01（JSON）", "https://web-data.api.hk01.com/v2/feed/category/0", "#1F4E79", limit_each),
     False),

    # Now：HTML
    ("now", "Now 新聞", "now_html",
     ("now", "Now（HTML）", "https://news.now.com/home", "#3B82F6", limit_each),
     False),

    # TVB：RSS + sitemap fallback
    ("tvb", "TVB 新聞", "tvb_combo",
     ("tvb", "TVB", "https://news.tvb.com/rss/local.xml", "https://news.tvb.com/sitemap.xml", "#10B981", limit_each),
     False),

    # 其餘：先用 Google News site:domain（非官方聚合）
    ("mingpao", "明報", "google_today",
     ("mingpao", "明報（聚合）", 'site:mingpao.com ' + BASE_NEWS_HINT + " " + NEG_ENT, "#6B7280", limit_each),
     True),

    ("onc", "on.cc", "google_today",
     ("onc", "on.cc（聚合）", 'site:on.cc ' + BASE_NEWS_HINT + " " + NEG_ENT, "#6B7280", limit_each),
     True),

    ("singtao", "星島", "google_today",
     ("singtao", "星島（聚合）", 'site:stheadline.com ' + BASE_NEWS_HINT + " " + NEG_ENT, "#6B7280", limit_each),
     True),

    ("topick", "TOPick", "google_today",
     ("topick", "TOPick（聚合）", 'site:topick.hket.com ' + BASE_NEWS_HINT + " " + NEG_ENT, "#6B7280", limit_each),
     True),

    ("hkej", "信報即時新聞", "google_today",
     ("hkej", "信報即時（聚合）", 'site:hkej.com ' + BASE_NEWS_HINT + " " + NEG_ENT, "#6B7280", limit_each),
     True),

    ("cable", "Cable 即時新聞", "google_today",
     ("cable", "Cable（聚合）", 'site:i-cable.com ' + BASE_NEWS_HINT + " " + NEG_ENT, "#6B7280", limit_each),
     True),

    ("hkcd", "香港商報", "google_today",
     ("hkcd", "香港商報（聚合）", 'site:hkcd.com ' + BASE_NEWS_HINT + " " + NEG_ENT, "#6B7280", limit_each),
     True),

    ("wenweipo", "文匯報", "google_today",
     ("wenweipo", "文匯報（聚合）", 'site:wenweipo.com ' + BASE_NEWS_HINT + " " + NEG_ENT, "#6B7280", limit_each),
     True),

    ("dotdotnews", "點新聞", "google_today",
     ("dotdotnews", "點新聞（聚合）", 'site:dotdotnews.com ' + BASE_NEWS_HINT + " " + NEG_ENT, "#6B7280", limit_each),
     True),

    ("tkww", "大公文匯", "google_today",
     ("tkww", "大公文匯（聚合）", 'site:tkww.hk ' + BASE_NEWS_HINT + " " + NEG_ENT, "#6B7280", limit_each),
     True),
]

st.markdown('<div class="section-wrap section-core">', unsafe_allow_html=True)
st.markdown("### 📰 今日新聞（你指定的媒體｜每個 10 條｜5 欄並排｜只顯示今日）")
st.markdown(
    "<div class='small-note'>註：未提供穩定官方 RSS/JSON 的媒體，暫以 Google News（site:domain）作「非官方聚合」替代；如你要逐個改成真爬蟲（requests/Playwright），我可再逐站升級。</div>",
    unsafe_allow_html=True,
)

cols = st.columns(5)
for idx, (key, name, kind, payload, warn_non_official) in enumerate(MEDIA_SOURCES):
    with cols[idx % 5]:
        st.markdown(f'<div class="source-header">📰 {name}</div>', unsafe_allow_html=True)

        with st.spinner("讀取中..."):
            if kind == "tvb_combo":
                # returns (items, flag)
                tvb_items, _flag = cached("tvb_combo", payload)
                st.markdown(render_articles(tvb_items, warn_non_official=False), unsafe_allow_html=True)
            else:
                items = cached(kind, payload)
                st.markdown(render_articles(items, warn_non_official=warn_non_official), unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)

st.caption(
    "提示：如某媒體長期顯示「今日暫無新聞」，多數原因是該站改版/反爬/動態渲染或 Google News 未即時收錄。"
    "你可指定「要真爬蟲」的媒體，我會逐個改成 requests 或 Playwright 版本。"
)
