# -*- coding: utf-8 -*-
import datetime
import re
import sys
import textwrap
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import feedparser
import pytz
import requests
import streamlit as st
import streamlit.components.v1 as components
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
PANEL_HEIGHT_PX = 760  # 控制5欄對齊高度


def now_hk() -> datetime.datetime:
    return datetime.datetime.now(HK_TZ)


def today_hk_date() -> datetime.date:
    return now_hk().date()


def is_today_hk(dt_obj: datetime.datetime) -> bool:
    return dt_obj.astimezone(HK_TZ).date() == today_hk_date()


# -----------------------
# Streamlit Page Config
# -----------------------
st.set_page_config(page_title="Tommy Sir後援會之新聞中心", layout="wide", page_icon="📰")

# -----------------------
# CSS (fixed-height panels to align horizontally)
# -----------------------
st.markdown(
    f"""
<style>
body {{ font-family: "Microsoft JhengHei", "PingFang TC", sans-serif; }}

.section-wrap {{ padding: 16px; border-radius: 12px; margin-bottom: 12px; }}
.section-gov {{ background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); }}
.section-core {{ background: #f8f9fa; }}

.source-header {{
  font-size: 1.02em; font-weight: 800;
  margin: 0 0 10px 0; padding: 8px 12px;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: white; border-radius: 10px; display: inline-block;
}}

.panel {{
  height: {PANEL_HEIGHT_PX}px;
  overflow-y: auto;
  padding-right: 6px;
  box-sizing: border-box;
}}
.panel::-webkit-scrollbar {{ width: 10px; }}
.panel::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 999px; }}
.panel::-webkit-scrollbar-track {{ background: transparent; }}

.news-item {{
  padding: 10px 12px; margin: 6px 0;
  background: white; border-left: 5px solid #3498db;
  border-radius: 10px; transition: all 0.18s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}}
.news-item:hover {{
  transform: translateX(3px);
  box-shadow: 0 3px 10px rgba(0,0,0,0.10);
  border-left-color: #ef4444;
}}
.news-title {{
  font-size: 0.97rem; font-weight: 650;
  color: #111827; text-decoration: none;
  line-height: 1.45; display: block; margin-bottom: 4px;
}}
.news-title:hover {{ color: #ef4444; }}
.news-meta {{
  font-size: 0.83rem; color: #6b7280;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}}

.badge-new {{
  display:inline-block; margin-left:8px; padding:2px 8px;
  border-radius:999px; background:#ef4444; color:white;
  font-size:0.75rem; font-weight:800;
}}
.badge-warn {{
  display:inline-block; margin-left:8px; padding:2px 8px;
  border-radius:999px; background:#b45309; color:white;
  font-size:0.75rem; font-weight:800;
}}

.small-note {{ color:#92400e; font-size:0.88rem; margin:-4px 0 10px 0; }}
hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 12px 0; }}
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
def clean_text(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"<.*?>", "", text)
    return " ".join(text.split())


def safe_get(url: str, timeout: int = 14) -> requests.Response:
    headers = {
        # mobile-ish UA
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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


def extract_meta_time(html: str) -> Optional[datetime.datetime]:
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


def extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    ogt = soup.find("meta", attrs={"property": "og:title"})
    if ogt and ogt.get("content"):
        return clean_text(ogt["content"])
    if soup.title and soup.title.string:
        return clean_text(soup.title.string)
    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True))
    return ""


def parse_relative_zh_time(text: str) -> Optional[datetime.datetime]:
    if not text:
        return None
    s = clean_text(text)

    m = re.search(r"(\d+)\s*分鐘前", s)
    if m:
        return now_hk() - datetime.timedelta(minutes=int(m.group(1)))

    h = re.search(r"(\d+)\s*小時前", s)
    if h:
        return now_hk() - datetime.timedelta(hours=int(h.group(1)))

    t = re.search(r"(今日|今天)\s*(\d{{1,2}}):(\d{{2}})", s)
    if t:
        hh = int(t.group(2))
        mm = int(t.group(3))
        dt = datetime.datetime.combine(today_hk_date(), datetime.time(hh, mm))
        return HK_TZ.localize(dt)

    d = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{2})", s)
    if d:
        yy, mo, da, hh, mm = map(int, d.groups())
        return HK_TZ.localize(datetime.datetime(yy, mo, da, hh, mm))

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


# -----------------------
# HTML Rendering (MOST STABLE)
# -----------------------
def build_panel_html(articles: List[Article], warn_non_official: bool = False) -> str:
    if not articles:
        return "<div class='panel'><p style='color:#9ca3af; padding:14px; text-align:center;'>今日暫無新聞</p></div>"

    parts = ["<div class='panel'>"]
    for a in articles:
        new_badge = "<span class='badge-new'>NEW</span>" if a.is_new else ""
        warn_badge = "<span class='badge-warn'>非官方聚合</span>" if warn_non_official else ""
        parts.append(
            f"<div class='news-item' style='border-left-color:{a.color};'>"
            f"<a class='news-title' href='{a.link}' target='_blank' rel='noopener noreferrer'>{a.title}</a>"
            f"<div class='news-meta'>🕐 {a.time_str} · {a.source} {new_badge} {warn_badge}</div>"
            f"</div>"
        )
    parts.append("</div>")
    return textwrap.dedent("".join(parts))


def render_panel(articles: List[Article], warn_non_official: bool = False, height: int = PANEL_HEIGHT_PX + 40):
    # Use components.html to avoid Markdown interpreting HTML as code
    html = build_panel_html(articles, warn_non_official=warn_non_official)
    components.html(html, height=height, scrolling=False)


# -----------------------
# Fetchers (today only, limit N)
# -----------------------
def fetch_rss_today(source_key: str, source_name: str, url: str, color: str, limit: int = 10) -> List[Article]:
    out: List[Article] = []
    try:
        feed = feedparser.parse(url)
        entries = getattr(feed, "entries", None) or []
        for entry in entries:
            title = clean_text(getattr(entry, "title", ""))
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


def fetch_google_news_today(source_key: str, source_name: str, query: str, color: str, limit: int = 10) -> List[Article]:
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    )
    return fetch_rss_today(source_key, source_name, url, color, limit=limit)


def fetch_tvb_news_sitemap_today(source_key: str, source_name: str, sitemap_url: str, color: str, limit: int = 10) -> List[Article]:
    out: List[Article] = []
    try:
        resp = safe_get(sitemap_url, timeout=16)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)

        ns = {
            "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
            "news": "http://www.google.com/schemas/sitemap-news/0.9",
        }

        for url_node in root.findall("sm:url", ns)[:500]:
            loc = url_node.findtext("sm:loc", default="", namespaces=ns).strip()
            title = url_node.findtext("news:news/news:title", default="", namespaces=ns).strip()
            pub = url_node.findtext("news:news/news:publication_date", default="", namespaces=ns).strip()

            if not loc or not title or not pub:
                continue

            try:
                dt0 = datetime.datetime.fromisoformat(pub.replace("Z", "+00:00"))
                if dt0.tzinfo is None:
                    dt0 = HK_TZ.localize(dt0)
                dt = dt0.astimezone(HK_TZ)
            except Exception:
                continue

            if not is_today_hk(dt):
                continue

            out.append(Article(source=source_name, title=clean_text(title), link=loc, timestamp=dt, time_str=dt.strftime("%H:%M"), color=color))
            if len(out) >= limit:
                break

    except Exception as e:
        st.warning(f"[TVB sitemap] 讀取失敗：{e}")

    out.sort(key=lambda x: x.timestamp, reverse=True)
    return mark_new_and_remember(source_key, out[:limit])


def fetch_list_page_links(base_url: str, html: str, link_pattern: re.Pattern) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: List[str] = []
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if href.startswith("/"):
            href = base_url.rstrip("/") + href
        if link_pattern.search(href):
            links.append(href)

    seen = set()
    dedup: List[str] = []
    for x in links:
        if x not in seen:
            seen.add(x)
            dedup.append(x)
    return dedup


def fetch_hk01_latest_today_html(source_key: str, source_name: str, list_url: str, color: str, limit: int = 10) -> List[Article]:
    out: List[Article] = []
    try:
        resp = safe_get(list_url, timeout=16)
        resp.raise_for_status()

        link_pattern = re.compile(r"hk01\.com/(article/\d+|[^/]+/\d+)", re.IGNORECASE)
        candidates = fetch_list_page_links("https://www.hk01.com", resp.text, link_pattern)[:200]

        for link in candidates:
            try:
                page = safe_get(link, timeout=12)
                if page.status_code != 200:
                    continue
                dt = extract_meta_time(page.text)
                if not dt or not is_today_hk(dt):
                    continue
                title = extract_title(page.text)
                if not title:
                    continue

                out.append(Article(source=source_name, title=title, link=link, timestamp=dt, time_str=dt.strftime("%H:%M"), color=color))
                if len(out) >= limit:
                    break
            except Exception:
                continue

    except Exception as e:
        st.warning(f"[HK01 HTML] 讀取失敗：{e}")

    out.sort(key=lambda x: x.timestamp, reverse=True)
    return mark_new_and_remember(source_key, out[:limit])


def fetch_topick_news_today_html(source_key: str, source_name: str, list_url: str, color: str, limit: int = 10) -> List[Article]:
    out: List[Article] = []
    try:
        resp = safe_get(list_url, timeout=16)
        resp.raise_for_status()

        link_pattern = re.compile(r"topick\.hket\.com/(article/\d+|.+/\d+)", re.IGNORECASE)
        candidates = fetch_list_page_links("https://topick.hket.com", resp.text, link_pattern)[:240]

        for link in candidates:
            try:
                page = safe_get(link, timeout=12)
                if page.status_code != 200:
                    continue
                dt = extract_meta_time(page.text) or parse_relative_zh_time(page.text)
                if not dt or not is_today_hk(dt):
                    continue
                title = extract_title(page.text)
                if not title:
                    continue

                out.append(Article(source=source_name, title=title, link=link, timestamp=dt, time_str=dt.strftime("%H:%M"), color=color))
                if len(out) >= limit:
                    break
            except Exception:
                continue

    except Exception as e:
        st.warning(f"[TOPick HTML] 讀取失敗：{e}")

    out.sort(key=lambda x: x.timestamp, reverse=True)
    return mark_new_and_remember(source_key, out[:limit])


def fetch_dotdotnews_immed_today_html(source_key: str, source_name: str, list_url: str, color: str, limit: int = 10) -> List[Article]:
    out: List[Article] = []
    try:
        resp = safe_get(list_url, timeout=16)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        items = []
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            if href.startswith("/"):
                href = "https://www.dotdotnews.com" + href
            if "dotdotnews.com" not in href:
                continue
            if any(x in href for x in ["/immed", "/category", "/tag", "/search", "/video"]):
                continue

            title = clean_text(a.get_text(" ", strip=True))
            if not title or len(title) < 6:
                continue

            time_text = ""
            parent = a.parent
            if parent:
                time_text = clean_text(parent.get_text(" ", strip=True))

            dt = parse_relative_zh_time(time_text)
            if not dt or not is_today_hk(dt):
                continue

            items.append((title, href, dt))

        # dedup by link, keep newest
        best: Dict[str, Tuple[str, datetime.datetime]] = {}
        for title, link, dt in items:
            if link not in best or dt > best[link][1]:
                best[link] = (title, dt)

        out = [
            Article(source=source_name, title=t, link=l, timestamp=dt, time_str=dt.strftime("%H:%M"), color=color)
            for l, (t, dt) in best.items()
        ]
        out.sort(key=lambda x: x.timestamp, reverse=True)
        out = out[:limit]

    except Exception as e:
        st.warning(f"[點新聞 HTML] 讀取失敗：{e}")

    return mark_new_and_remember(source_key, out[:limit])


def fetch_tkww_top_news_today_html(source_key: str, source_name: str, list_url: str, color: str, limit: int = 10) -> List[Article]:
    out: List[Article] = []
    try:
        resp = safe_get(list_url, timeout=16)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        candidates: List[Article] = []
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            if href.startswith("/"):
                href = "https://www.tkww.hk" + href
            if "tkww.hk" not in href:
                continue
            if any(x in href for x in ["/top_news", "/topic", "/search", "/video"]):
                continue

            title = clean_text(a.get_text(" ", strip=True))
            if not title or len(title) < 6:
                continue

            time_text = ""
            block = a.parent
            if block:
                time_text = clean_text(block.get_text(" ", strip=True))

            dt = parse_relative_zh_time(time_text)
            if not dt:
                # fallback: open article to get meta time (limited)
                try:
                    page = safe_get(href, timeout=12)
                    if page.status_code == 200:
                        dt = extract_meta_time(page.text)
                except Exception:
                    dt = None

            if not dt or not is_today_hk(dt):
                continue

            candidates.append(Article(source=source_name, title=title, link=href, timestamp=dt, time_str=dt.strftime("%H:%M"), color=color))

        dedup: Dict[str, Article] = {}
        for a in candidates:
            if a.link not in dedup or a.timestamp > dedup[a.link].timestamp:
                dedup[a.link] = a

        out = list(dedup.values())
        out.sort(key=lambda x: x.timestamp, reverse=True)
        out = out[:limit]

    except Exception as e:
        st.warning(f"[tkww HTML] 讀取失敗：{e}")

    return mark_new_and_remember(source_key, out[:limit])


def fetch_telegram_channel_today(source_key: str, source_name: str, channel_public_url: str, color: str, limit: int = 10) -> List[Article]:
    out: List[Article] = []
    try:
        resp = safe_get(channel_public_url, timeout=16)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        blocks = soup.select("div.tgme_widget_message_wrap, div.tgme_widget_message")
        for b in blocks:
            post_link = ""
            a = b.select_one("a.tgme_widget_message_date")
            if a and a.get("href"):
                post_link = a["href"]

            msg = b.select_one("div.tgme_widget_message_text")
            text = clean_text(msg.decode_contents() if msg else "")
            if not text:
                continue

            dt = None
            if a and a.get("title"):
                dt = parse_relative_zh_time(a.get("title", ""))

            if dt is None:
                dt = now_hk()

            if not is_today_hk(dt):
                continue

            urls = re.findall(r"https?://[^\s)]+", text)
            link = urls[0] if urls else (post_link or channel_public_url)

            title = text.split("\n")[0].strip()
            title = re.sub(r"\s+", " ", title)
            if len(title) > 80:
                title = title[:80] + "…"

            out.append(Article(source=source_name, title=title, link=link, timestamp=dt, time_str=dt.strftime("%H:%M"), color=color))
            if len(out) >= limit:
                break

    except Exception as e:
        st.warning(f"[Telegram] {source_name} 讀取失敗：{e}")

    out.sort(key=lambda x: x.timestamp, reverse=True)
    return mark_new_and_remember(source_key, out[:limit])


# -----------------------
# Cache wrapper (60s)
# -----------------------
@st.cache_data(ttl=60, show_spinner=False)
def cached(kind: str, args: Tuple):
    if kind == "rss_today":
        return fetch_rss_today(*args)
    if kind == "google_today":
        return fetch_google_news_today(*args)
    if kind == "tvb_sitemap":
        return fetch_tvb_news_sitemap_today(*args)
    if kind == "hk01_html":
        return fetch_hk01_latest_today_html(*args)
    if kind == "topick_html":
        return fetch_topick_news_today_html(*args)
    if kind == "dotdot_html":
        return fetch_dotdotnews_immed_today_html(*args)
    if kind == "tkww_html":
        return fetch_tkww_top_news_today_html(*args)
    if kind == "telegram_today":
        return fetch_telegram_channel_today(*args)
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
    st.markdown("<div class='small-note'>NEW：同一個 session 內首次見到的連結。</div>", unsafe_allow_html=True)

if auto_on:
    st_autorefresh(interval=60 * 1000, key="auto_refresh_60s")

if st.button("🔄 立即刷新", type="primary"):
    st.cache_data.clear()
    st.rerun()

st.markdown("<hr/>", unsafe_allow_html=True)

# -----------------------
# Government (ZH/EN separate)
# -----------------------
st.markdown('<div class="section-wrap section-gov">', unsafe_allow_html=True)
st.markdown("### 🏛️ 政府新聞與公告（中 / 英分開｜各 10 條｜只顯示今日）")

gov_zh_col, gov_en_col = st.columns(2)
with gov_zh_col:
    st.markdown('<div class="source-header">🏛️ 政府新聞（中文）</div>', unsafe_allow_html=True)
    gov_zh = cached("rss_today", ("gov_zh", "政府新聞（中文）", "https://www.info.gov.hk/gia/rss/general_zh.xml", "#E74C3C", limit_each))
    render_panel(gov_zh, warn_non_official=False, height=420)

with gov_en_col:
    st.markdown('<div class="source-header">🏛️ Gov News (English)</div>', unsafe_allow_html=True)
    gov_en = cached("rss_today", ("gov_en", "Gov News (English)", "https://www.info.gov.hk/gia/rss/general_en.xml", "#C0392B", limit_each))
    render_panel(gov_en, warn_non_official=False, height=420)

st.markdown("</div>", unsafe_allow_html=True)
st.markdown("<hr/>", unsafe_allow_html=True)

# -----------------------
# Media sources (5 columns aligned)
# -----------------------
NEG_ENT = "-娛樂 -演唱會 -音樂 -歌手 -電影 -明星 -綜藝 -劇集 -頒獎禮 -花邊 -八卦 -KOL -旅遊 -美食"
BASE_NEWS_HINT = "(新聞 OR 港聞 OR 本地 OR 時事 OR 政府 OR 立法會 OR 警方 OR 法庭 OR 交通 OR 天氣 OR 經濟 OR 財經)"

MEDIA_SOURCES = [
    # key, display, kind, payload, warn_non_official
    ("rthk", "RTHK（本地 RSS）", "rss_today",
     ("rthk", "RTHK（本地）", "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "#FF9800", limit_each),
     False),

    ("cr_tg", "商業電台（Telegram）", "telegram_today",
     ("cr_tg", "商業電台（Telegram）", "https://t.me/s/cr881903", "#F59E0B", limit_each),
     False),

    ("tvb", "TVB（sitemap 即時）", "tvb_sitemap",
     ("tvb", "TVB（即時）", "https://news.tvb.com/sitemap.xml", "#10B981", limit_each),
     False),

    ("hk01", "HK01（HTML 即時）", "hk01_html",
     ("hk01", "HK01（即時）", "https://www.hk01.com/latest", "#1F4E79", limit_each),
     False),

    ("topick", "TOPick（HTML 新聞）", "topick_html",
     ("topick", "TOPick（新聞）", "https://topick.hket.com/srat006/%E6%96%B0%E8%81%9E", "#6B7280", limit_each),
     False),

    ("dotdot", "點新聞（HTML 即時）", "dotdot_html",
     ("dotdot", "點新聞（即時）", "https://www.dotdotnews.com/immed", "#6B7280", limit_each),
     False),

    ("tkww", "大公文匯（HTML 即時）", "tkww_html",
     ("tkww", "大公文匯（即時）", "https://www.tkww.hk/top_news", "#6B7280", limit_each),
     False),

    # 備援：商台（過濾娛樂）Google News
    ("cr_gn", "商台（新聞過濾・備援）", "google_today",
     ("cr_gn", "商台（備援）", '(881903 OR "商業電台" OR "叱咤903") ' + BASE_NEWS_HINT + " " + NEG_ENT, "#B45309", limit_each),
     True),
]

st.markdown('<div class="section-wrap section-core">', unsafe_allow_html=True)
st.markdown("### 📰 今日新聞（每個平台 10 條｜5 欄並排對齊｜只顯示今日）")

cols = st.columns(5)
for idx, (key, name, kind, payload, warn_non_official) in enumerate(MEDIA_SOURCES):
    with cols[idx % 5]:
        st.markdown(f'<div class="source-header">📰 {name}</div>', unsafe_allow_html=True)
        with st.spinner("讀取中..."):
            items = cached(kind, payload)
            render_panel(items, warn_non_official=warn_non_official, height=PANEL_HEIGHT_PX + 40)

st.markdown("</div>", unsafe_allow_html=True)

st.caption("提示：如個別網站出現 403/反爬，需再調整 headers 或改用 Playwright。")
