import os
import re
from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Optional, Tuple, Dict, Any

import requests
import streamlit as st
import feedparser
from dateutil import parser as dtparser
import pytz

# -----------------------------
# Timezone
# -----------------------------
HK_TZ = pytz.timezone("Asia/Hong_Kong")

def now_hk() -> datetime:
    return datetime.now(HK_TZ)

# -----------------------------
# Models
# -----------------------------
@dataclass
class Article:
    title: str
    link: str
    time_str: str
    color: str

# -----------------------------
# Helpers
# -----------------------------
def clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s

def _safe_get_json(url: str, params: Dict[str, Any], timeout: int = 12) -> Any:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NewsDashboard/1.0)",
        "Accept": "application/json,text/plain,*/*",
    }
    r = requests.get(url, params=params, timeout=timeout, headers=headers)
    r.raise_for_status()
    return r.json()

def _safe_get_rss(url: str, timeout: int = 12) -> feedparser.FeedParserDict:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NewsDashboard/1.0)",
        "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    r = requests.get(url, timeout=timeout, headers=headers)
    r.raise_for_status()
    return feedparser.parse(r.content)

def _pick_first_working_rss(urls: List[str]) -> Tuple[Optional[feedparser.FeedParserDict], Optional[str], Optional[str]]:
    """
    Try a list of RSS URLs and return (feed, used_url, error_message).
    """
    last_err = None
    for u in urls:
        try:
            feed = _safe_get_rss(u, timeout=12)
            # feedparser: if bozo, still may contain entries; accept if entries exist
            if getattr(feed, "entries", None):
                return feed, u, None
            # Sometimes empty due to parsing; still treat as success but warn
            return feed, u, "RSS 解析到 0 條（來源可能暫時無更新或結構改變）"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            continue
    return None, None, last_err or "RSS 讀取失敗"

def _parse_rss_entries_today(feed: feedparser.FeedParserDict, limit: int) -> Tuple[List[Article], Optional[str]]:
    """
    Keep only today's items (HK time). If none, fallback to latest.
    """
    today = now_hk().date()
    out_today: List[Article] = []
    out_latest: List[Article] = []

    entries = getattr(feed, "entries", []) or []
    for it in entries:
        title = clean_text(str(getattr(it, "title", "") or ""))
        link = str(getattr(it, "link", "") or "")

        # attempt date
        raw = None
        for k in ("published", "updated", "pubDate"):
            raw = getattr(it, k, None)
            if raw:
                break

        dt = None
        time_str = "今日"
        if raw:
            try:
                dt = dtparser.parse(str(raw))
                if dt.tzinfo is None:
                    dt = HK_TZ.localize(dt)
                dt = dt.astimezone(HK_TZ)
                time_str = dt.strftime("%H:%M")
            except Exception:
                dt = None
                time_str = "今日"

        if title and link:
            # latest buffer
            out_latest.append(Article(title=title, link=link, time_str=time_str, color="#666"))
            if dt and dt.date() == today:
                out_today.append(Article(title=title, link=link, time_str=time_str, color="#666"))

        if len(out_latest) >= limit:
            break

    if out_today:
        return out_today[:limit], None
    if out_latest:
        return out_latest[:limit], "未能篩出『今日』新聞，已改為顯示最新 10 條（RSS 的時間欄位可能缺失/格式異常）"
    return [], "RSS 有回傳但未能解析到有效新聞項目"

# -----------------------------
# Now (special) — You asked to keep this logic
# -----------------------------
NOW_API = os.getenv("NOW_API", "").strip()  # 建議你喺 Railway/本機環境變數設定
# 例子（你自己填）：NOW_API=https://news.now.com/api/getNews  （示例，實際以你驗證到為準）

@st.cache_data(ttl=60)
def fetch_now_local_today(color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    Now 新聞（本地）：
    - categoryId=119
    - 只顯示今日（香港時間）
    - 有時間顯示 HH:MM；時間解析失敗則顯示「今日」
    - 如今日篩選後為 0，但 API 有回傳 → fallback 顯示最新 10（並提示）
    """
    if not NOW_API:
        return [], "NOW_API 未設定：請在環境變數加入 NOW_API（Now 需用 API，不建議用 HTML 抓）"

    today = now_hk().date()
    out_today: List[Article] = []
    out_latest: List[Article] = []

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
                # 再掃一層 dict
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

            title = clean_text(str(it.get("newsTitle") or it.get("title") or it.get("headline") or ""))
            link = str(it.get("shareUrl") or it.get("url") or it.get("link") or "")
            if link.startswith("/"):
                link = "https://news.now.com" + link

            # 時間
            time_str = "今日"
            dt = None
            raw_time = it.get("publishDate") or it.get("publishTime") or it.get("publishedAt") or it.get("date")
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

            if title and link:
                art = Article(title=title, link=link, time_str=time_str, color=color)
                out_latest.append(art)
                if dt and dt.date() == today:
                    out_today.append(art)

            if len(out_latest) >= limit:
                break

        if out_today:
            return out_today[:limit], None
        if out_latest:
            return out_latest[:limit], "未能篩出『今日』新聞，已改為顯示最新 10 條（請確認 API 時間欄位格式）"
        return [], "Now API 有回傳但未能解析到有效新聞項目"

    except Exception as e:
        return [], f"Now API 讀取失敗：{type(e).__name__}: {e}"

# -----------------------------
# UI: keep horizontal cards
# -----------------------------
st.set_page_config(page_title="香港新聞聚合中心", layout="wide")

st.markdown(
    """
    <style>
      .card {
        border-radius: 14px;
        padding: 14px 16px;
        border: 1px solid rgba(0,0,0,0.08);
        background: #ffffff;
        min-height: 320px;
      }
      .card-title {
        font-weight: 700;
        font-size: 18px;
        margin-bottom: 6px;
      }
      .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 12px;
        border: 1px solid rgba(0,0,0,0.12);
        color: rgba(0,0,0,0.75);
        margin-left: 8px;
      }
      .meta {
        color: rgba(0,0,0,0.55);
        font-size: 12px;
        margin-bottom: 10px;
      }
      .item {
        margin: 10px 0 12px 0;
        padding-left: 10px;
        border-left: 4px solid rgba(0,0,0,0.15);
      }
      .item a { text-decoration: none; }
      .time {
        color: rgba(0,0,0,0.55);
        font-size: 12px;
        margin-right: 8px;
      }
      .warn {
        color: #b45309;
        font-size: 13px;
        margin-top: 8px;
      }
      .err {
        color: #b91c1c;
        font-size: 13px;
        margin-top: 8px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("香港新聞聚合中心")

auto_refresh = st.toggle("每分鐘自動更新", value=True)
show_today_only = st.toggle("只顯示今日", value=True)

st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

# Your RSSHub base (from your screenshot)
RSSHUB_BASE = os.getenv("RSSHUB_BASE", "https://rsshub-production-9dfc.up.railway.app").rstrip("/")

# --- Official RSS (fix obvious typo: RTHK should be .xml not .xmls)
GOV_ZH_CANDIDATES = [
    "https://www.info.gov.hk/gia/rss/general_zh.xml",
    "http://www.info.gov.hk/gia/rss/general_zh.xml",
]

# 你之前用 general.xml 會 404；我保守做多個候選，避免你再卡死
GOV_EN_CANDIDATES = [
    "https://www.info.gov.hk/gia/rss/general.xml",
    "http://www.info.gov.hk/gia/rss/general.xml",
    "https://www.info.gov.hk/gia/rss/general_en.xml",
    "http://www.info.gov.hk/gia/rss/general_en.xml",
]

RTHK_CANDIDATES = [
    "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",
    "http://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",
]

# If you also have RSSHub routes for other sources, keep them here (optional)
# Example placeholders (only used if you later want):
# HK01_RSS = f"{RSSHUB_BASE}/hk01/news"
# ONCC_RSS = f"{RSSHUB_BASE}/oncc/new"  # example only

LIMIT = 10

@st.cache_data(ttl=60)
def fetch_rss_today(url_candidates: List[str], limit: int) -> Tuple[List[Article], Optional[str], Optional[str]]:
    feed, used_url, err = _pick_first_working_rss(url_candidates)
    if not feed:
        return [], None, f"RSS 讀取失敗：{err}"
    items, warn = _parse_rss_entries_today(feed, limit=limit)
    # set default neutral color for rss items (UI border set later)
    return items, used_url, warn

def render_card(title: str, badge: str, color: str, items: List[Article], warn: Optional[str], err: Optional[str], source_url: Optional[str]):
    # apply color to left border
    def item_html(a: Article) -> str:
        return f"""
        <div class="item" style="border-left-color:{color}">
          <div>
            <span class="time">🕒 {a.time_str}</span>
            <a href="{a.link}" target="_blank">{a.title}</a>
          </div>
        </div>
        """

    items_block = "\n".join(item_html(a) for a in items) if items else ""
    source_line = f'<div class="meta">來源：{source_url}</div>' if source_url else '<div class="meta">來源：—</div>'
    warn_line = f'<div class="warn">提示：{warn}</div>' if warn else ""
    err_line = f'<div class="err">{err}</div>' if err else ""

    st.markdown(
        f"""
        <div class="card">
          <div class="card-title">{title} <span class="badge">{badge}</span></div>
          {source_line}
          {items_block if items_block else '<div class="meta">今日暫無新聞</div>'}
          {warn_line}
          {err_line}
        </div>
        """,
        unsafe_allow_html=True,
    )

# -----------------------------
# Fetch data
# -----------------------------
# 官方 RSS（政府／RTHK）
gov_zh_items, gov_zh_url, gov_zh_warn = fetch_rss_today(GOV_ZH_CANDIDATES, LIMIT)
gov_en_items, gov_en_url, gov_en_warn = fetch_rss_today(GOV_EN_CANDIDATES, LIMIT)
rthk_items, rthk_url, rthk_warn = fetch_rss_today(RTHK_CANDIDATES, LIMIT)

# Now（special）
now_items, now_warn = fetch_now_local_today(color="#2563eb", limit=LIMIT)

# If "只顯示今日" is off, we still show what fetch functions give (they already fallback to latest if today empty)
# If you want strict behavior, you can remove fallback in the functions; I kept your requested fallback.

# -----------------------------
# Layout: horizontal columns (your requested style)
# -----------------------------
cols = st.columns([1, 1, 1, 1])

with cols[0]:
    render_card(
        title="政府新聞（中）",
        badge="官方 RSS",
        color="#ef4444",
        items=[Article(a.title, a.link, a.time_str, "#ef4444") for a in gov_zh_items],
        warn=gov_zh_warn,
        err=None if gov_zh_items else "如長期讀唔到：請確認 RSS URL / 伺服器是否被擋（可先用瀏覽器直接開 RSS URL 測試）",
        source_url=gov_zh_url,
    )

with cols[1]:
    render_card(
        title="政府新聞（英）",
        badge="官方 RSS",
        color="#f59e0b",
        items=[Article(a.title, a.link, a.time_str, "#f59e0b") for a in gov_en_items],
        warn=gov_en_warn,
        err=None if gov_en_items else "你之前見到 404：我已加多個候選 URL；若仍 404，請用瀏覽器直開候選 URL 確認哪個先係真",
        source_url=gov_en_url,
    )

with cols[2]:
    render_card(
        title="RTHK（本地）",
        badge="官方 RSS",
        color="#10b981",
        items=[Article(a.title, a.link, a.time_str, "#10b981") for a in rthk_items],
        warn=rthk_warn,
        err=None if rthk_items else "你之前 URL 打咗 .xmls（多咗個 s）；我已改返 .xml",
        source_url=rthk_url,
    )

with cols[3]:
    render_card(
        title="Now 新聞（本地）",
        badge="Now（API 特別處理）",
        color="#2563eb",
        items=now_items,
        warn=now_warn,
        err=None if now_items else "Now 需要你提供 NOW_API（環境變數）。你而家見到 Now 有內容，通常係因為你已經有 API／或你之前用咗特定抓法。",
        source_url=NOW_API or None,
    )

# Optional auto refresh
if auto_refresh:
    st.caption("自動更新已開：建議配合部署平台本身的 refresh / cron。")
