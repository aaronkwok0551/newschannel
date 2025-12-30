# app.py
# -*- coding: utf-8 -*-

import datetime
import html
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import feedparser
import pytz
import requests
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
NEW_HIGHLIGHT_MINUTES = 20

st.set_page_config(page_title="香港新聞聚合中心", layout="wide", page_icon="🗞️")

# =====================
# CSS（你要的「橫向並列」卡片 + 新聞新出現紅色）
# =====================
st.markdown(
    """
<style>
body { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

.section-title{
  font-size:1.1rem;font-weight:800;margin:2px 0 8px 0;
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

.item.new-item{
  border-left-color:#ef4444 !important;
}

.item a{
  text-decoration:none;color:#111827;font-weight:600;line-height:1.35;
}
.item a:hover{ color:#ef4444; }

.item-meta{
  font-size:0.78rem;color:#6b7280;font-family:monospace;margin-top:2px;
}

.warn{
  font-size:0.82rem;color:#b45309;background:#fffbeb;border:1px solid #fcd34d;
  padding:8px 10px;border-radius:10px;margin:8px 0;
}

.empty{ color:#9ca3af;text-align:center;margin-top:20px; }
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
    dt: Optional[datetime.datetime] = None
    # 用 session_state 判斷「新出現」：第一次見到的時間
    first_seen: Optional[datetime.datetime] = None


# =====================
# Helpers
# =====================
def now_hk() -> datetime.datetime:
    return datetime.datetime.now(HK_TZ)


def clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    soup = BeautifulSoup(raw, "html.parser")
    return soup.get_text(" ", strip=True)


def _looks_like_html(content: bytes) -> bool:
    head = content[:800].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<div" in head


def _fetch_bytes(url: str, timeout: int = 12) -> Tuple[Optional[bytes], Optional[str]]:
    """用 requests 抓內容，避免 feedparser 直接吃到 HTML（div class）"""
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/rss+xml,application/xml;q=0.9,text/xml;q=0.8,*/*;q=0.7",
            },
        )
        r.raise_for_status()
        content = r.content or b""
        if _looks_like_html(content):
            return None, "回傳的是 HTML（div class）— 可能被擋／RSSHub 路由失效／站點改版"
        return content, None
    except Exception as e:
        return None, f"讀取失敗：{type(e).__name__}: {e}"


def _safe_get_json(url: str, params: Optional[dict] = None, timeout: int = 12):
    r = requests.get(
        url,
        params=params,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,*/*;q=0.8"},
    )
    r.raise_for_status()
    return r.json()


def _epoch_ms_to_dt(ms: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(ms / 1000.0, tz=HK_TZ)


def parse_time_from_feed_entry(entry) -> Optional[datetime.datetime]:
    if getattr(entry, "published_parsed", None):
        return datetime.datetime(*entry.published_parsed[:6], tzinfo=pytz.utc).astimezone(HK_TZ)
    if getattr(entry, "updated_parsed", None):
        return datetime.datetime(*entry.updated_parsed[:6], tzinfo=pytz.utc).astimezone(HK_TZ)

    for key in ("published", "updated", "pubDate", "date"):
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


def _ensure_seen_key():
    if "seen_map" not in st.session_state:
        st.session_state["seen_map"] = {}  # type: ignore


def mark_and_flag_new(source_key: str, articles: List[Article]) -> List[Article]:
    """
    - 記錄每條新聞首次見到時間
    - 新聞「新出現」維持 20 分鐘：顯示紅色邊（new-item）
    """
    _ensure_seen_key()
    seen_map: Dict[str, str] = st.session_state["seen_map"]  # type: ignore
    now = now_hk()

    for a in articles:
        k = f"{source_key}||{a.link}"
        if k not in seen_map:
            seen_map[k] = now.isoformat()
            a.first_seen = now
        else:
            try:
                a.first_seen = dtparser.parse(seen_map[k]).astimezone(HK_TZ)
            except Exception:
                a.first_seen = now

    return articles


def sort_latest_first(articles: List[Article]) -> List[Article]:
    """
    先按 dt（有就用），無 dt 就用 first_seen，再無就放後面。
    """
    def key(a: Article):
        if a.dt:
            return a.dt
        if a.first_seen:
            return a.first_seen
        return datetime.datetime(1970, 1, 1, tzinfo=HK_TZ)

    return sorted(articles, key=key, reverse=True)


def is_new(a: Article) -> bool:
    if not a.first_seen:
        return False
    return (now_hk() - a.first_seen) <= datetime.timedelta(minutes=NEW_HIGHLIGHT_MINUTES)


# =====================
# Fetchers
# =====================
@st.cache_data(ttl=60)
def fetch_rss_today(url: str, color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    content, warn = _fetch_bytes(url, timeout=12)
    if warn:
        return [], warn

    feed = feedparser.parse(content)
    today = now_hk().date()

    out_today: List[Article] = []
    out_latest: List[Article] = []

    for e in feed.entries or []:
        title = clean_text(getattr(e, "title", ""))
        link = getattr(e, "link", "")
        if not title or not link:
            continue

        dt = parse_time_from_feed_entry(e)
        if dt:
            art = Article(title=title, link=link, time_str=dt.strftime("%H:%M"), color=color, dt=dt)
            out_latest.append(art)
            if dt.date() == today:
                out_today.append(art)
        else:
            out_latest.append(Article(title=title, link=link, time_str="今日", color=color, dt=None))

        if len(out_latest) >= limit:
            break

    if out_today:
        return out_today[:limit], None

    if out_latest:
        return out_latest[:limit], "此來源未提供可解析時間／日期，已改為顯示最新 10 條"

    return [], "RSS 無內容或暫時讀取不到"


@st.cache_data(ttl=60)
def fetch_rss_latest(url: str, color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    content, warn = _fetch_bytes(url, timeout=12)
    if warn:
        return [], warn

    feed = feedparser.parse(content)
    out: List[Article] = []

    for e in feed.entries or []:
        title = clean_text(getattr(e, "title", ""))
        link = getattr(e, "link", "")
        if not title or not link:
            continue

        dt = parse_time_from_feed_entry(e)
        time_str = dt.strftime("%H:%M") if dt else "即時"
        out.append(Article(title=title, link=link, time_str=time_str, color=color, dt=dt))

        if len(out) >= limit:
            break

    if out:
        return out[:limit], None

    return [], "RSS 無內容或暫時讀取不到"


@st.cache_data(ttl=60)
def fetch_now_local_today(color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    Now 新聞（本地）：
    - 用你確認可用的 API：getNewsListv2?category=119&pageNo=1
    - 即使 webUrl/shareUrl 為 null，仍用 newsId 自動砌回可打開的 player link
    """
    today = now_hk().date()
    NOW_API = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2"

    out_today: List[Article] = []
    out_latest: List[Article] = []

    try:
        data = _safe_get_json(NOW_API, {"category": 119, "pageNo": 1}, timeout=12)

        # 取 list
        candidates = None
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            for k in ("data", "list", "news", "items", "result"):
                v = data.get(k)
                if isinstance(v, list):
                    candidates = v
                    break
            if candidates is None:
                for v in data.values():
                    if isinstance(v, dict):
                        for kk in ("data", "list", "news", "items", "result"):
                            vv = v.get(kk)
                            if isinstance(vv, list):
                                candidates = vv
                                break
                    if candidates is not None:
                        break

        if not candidates:
            return [], "Now API 回傳結構已變（找不到新聞列表）"

        for it in candidates:
            if not isinstance(it, dict):
                continue

            title = clean_text(str(it.get("title") or it.get("newsTitle") or it.get("headline") or ""))
            news_id = it.get("newsId")

            link = str(it.get("webUrl") or it.get("shareUrl") or it.get("url") or it.get("link") or "")
            if link.startswith("/"):
                link = "https://news.now.com" + link

            # webUrl 係 null 時，用 newsId 砌 player URL
            if (not link) and news_id:
                link = f"https://news.now.com/home/local/player?newsId={news_id}"

            # 時間：publishDate epoch ms
            dt = None
            time_str = "今日"
            raw = it.get("publishDate") or it.get("publishTime") or it.get("publishedAt") or it.get("date")
            if raw is not None:
                try:
                    if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.isdigit()):
                        dt = _epoch_ms_to_dt(int(raw))
                    else:
                        dt = dtparser.parse(str(raw))
                        if dt.tzinfo is None:
                            dt = HK_TZ.localize(dt)
                        dt = dt.astimezone(HK_TZ)
                    time_str = dt.strftime("%H:%M")
                except Exception:
                    dt = None
                    time_str = "今日"

            if title and link:
                art = Article(title=title, link=link, time_str=time_str, color=color, dt=dt)
                out_latest.append(art)
                if dt and dt.date() == today:
                    out_today.append(art)

            if len(out_latest) >= limit:
                break

        if out_today:
            return out_today[:limit], None

        if out_latest:
            return out_latest[:limit], "未能篩出『今日』新聞，已改為顯示最新 10 條"

        return [], "Now API 有回傳但未能解析到有效新聞（可能缺少 title/link/newsId）"

    except Exception as e:
        return [], f"Now API 讀取失敗：{type(e).__name__}: {e}"


# =====================
# Render
# =====================
def build_card_html(title: str, articles: List[Article], warn: Optional[str] = None) -> str:
    warn_html = f"<div class='warn'>⚠️ {html.escape(warn)}</div>" if warn else ""

    if not articles:
        items_html = "<div class='empty'>今日暫無新聞</div>"
    else:
        parts = []
        for a in articles:
            new_cls = "new-item" if is_new(a) else ""
            parts.append(
                f"""
                <div class="item {new_cls}" style="border-left-color:{a.color}">
                  <a href="{html.escape(a.link)}" target="_blank" rel="noopener noreferrer">{html.escape(a.title)}</a>
                  <div class="item-meta">🕐 {html.escape(a.time_str)}</div>
                </div>
                """
            )
        items_html = "".join(parts)

    return f"""
    <div class="section-title">{html.escape(title)}</div>
    <div class="card">
      {warn_html}
      <div class="items">
        {items_html}
      </div>
    </div>
    """


def render_source(
    col,
    source_key: str,
    title: str,
    fetch_fn,
    *fetch_args,
    limit: int = 10,
):
    with col:
        arts, warn = fetch_fn(*fetch_args, limit)
        # 記錄首次見到時間，做「新出現」紅色 20 分鐘
        arts = mark_and_flag_new(source_key, arts)
        # 全部按時間由新到舊
        arts = sort_latest_first(arts)
        st.markdown(build_card_html(title, arts, warn), unsafe_allow_html=True)


# =====================
# URLs（你提供的來源 + RSSHub）
# =====================
GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"

# 你 RSSHub 域名（可在 sidebar 改）
DEFAULT_RSSHUB = "https://rsshub-production-9dfc.up.railway.app"

# =====================
# UI
# =====================
st.title("🗞️ 香港新聞聚合中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

with st.sidebar:
    st.subheader("設定")
    rsshub_base = st.text_input("RSSHub Base URL", value=DEFAULT_RSSHUB).strip().rstrip("/")
    limit = st.slider("每個媒體顯示條數", 5, 30, 10, 1)
    if st.toggle("每分鐘自動更新", value=True):
        st_autorefresh(interval=60_000, key="auto")

# RSSHub 路由（按你給的清單）
HK01 = f"{rsshub_base}/hk01/latest"
ONCC = f"{rsshub_base}/oncc/zh-hant/news"
TVB = f"{rsshub_base}/tvb/news/tc"
HKEJ = f"{rsshub_base}/hkej/index"
STHEADLINE = f"{rsshub_base}/stheadline/std/realtime"
ICABLE = f"{rsshub_base}/icable/all"

# 注意：你話 RSSHub Now 壞咗，所以 Now 改用 API（唔再用 rsshub now/news）
# NOW（本地）用 fetch_now_local_today()

# =====================
# 版面（保持「每個平台橫向並列」，不混合）
# 你可以按自己圖二的排列，改下面 row 的順序，但每格都係獨立平台
# =====================

# Row 1
row1 = st.columns(4)
render_source(row1[0], "gov_zh", "政府新聞（中文）", fetch_rss_today, GOV_ZH, "#E74C3C", limit=limit)
render_source(row1[1], "gov_en", "政府新聞（英文）", fetch_rss_today, GOV_EN, "#C0392B", limit=limit)
render_source(row1[2], "rthk", "RTHK", fetch_rss_today, RTHK, "#FF9800", limit=limit)
render_source(row1[3], "now_local", "Now（本地 / 港聞）", fetch_now_local_today, "#2563EB", limit=limit)

# Row 2
row2 = st.columns(4)
render_source(row2[0], "hk01", "HK01", fetch_rss_latest, HK01, "#0ea5e9", limit=limit)
render_source(row2[1], "oncc", "on.cc 東網", fetch_rss_latest, ONCC, "#111827", limit=limit)
render_source(row2[2], "tvb", "TVB 新聞", fetch_rss_latest, TVB, "#16a34a", limit=limit)
render_source(row2[3], "hkej", "信報即時", fetch_rss_latest, HKEJ, "#7c3aed", limit=limit)

# Row 3
row3 = st.columns(4)
render_source(row3[0], "stheadline", "星島即時", fetch_rss_latest, STHEADLINE, "#f97316", limit=limit)
render_source(row3[1], "icable", "i-CABLE 有線", fetch_rss_latest, ICABLE, "#dc2626", limit=limit)
# 你之後想加媒體就加在這兩格（暫留空）
with row3[2]:
    st.markdown(build_card_html("（預留）", [], "你可以在這格加下一個 RSSHub/官方 RSS"), unsafe_allow_html=True)
with row3[3]:
    st.markdown(build_card_html("（預留）", [], "你可以在這格加下一個 RSSHub/官方 RSS"), unsafe_allow_html=True)
