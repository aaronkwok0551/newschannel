# app.py
# -*- coding: utf-8 -*-

import datetime
import html
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

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

st.set_page_config(page_title="香港新聞聚合中心", layout="wide", page_icon="🗞️")

# =====================
# CSS（白底版）
# =====================
st.markdown(
    """
<style>
/* 全局字體 */
html, body, [class*="css"]  { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

/* 標題 */
.section-title{
  font-size:1.05rem;
  font-weight:800;
  margin:2px 0 8px 0;
}

/* 卡片 */
.card{
  background:#ffffff;
  border:1px solid #e5e7eb;
  border-radius:12px;
  padding:12px;
  height:520px;
  display:flex;
  flex-direction:column;
}

/* 內部滾動 */
.items{
  overflow-y:auto;
  padding-right:6px;
  flex:1;
}

/* 每條新聞 */
.item{
  background:#ffffff;
  border-left:4px solid #3b82f6;
  border-radius:8px;
  padding:8px 10px;
  margin:8px 0;
}

.item a{
  text-decoration:none;
  color:#111827;
  font-weight:600;
  line-height:1.35;
  display:block;
}
.item a:hover{ color:#ef4444; }

.item-meta{
  font-size:0.78rem;
  color:#6b7280;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  margin-top:2px;
}

.badge{
  display:inline-block;
  font-size:0.72rem;
  padding:2px 8px;
  border-radius:999px;
  background:#f3f4f6;
  color:#374151;
  margin-left:8px;
}

.empty{
  color:#9ca3af;
  text-align:center;
  margin-top:20px;
}
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
def now_hk() -> datetime.datetime:
    return datetime.datetime.now(HK_TZ)

def clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    soup = BeautifulSoup(raw, "html.parser")
    return soup.get_text(" ", strip=True)

def _safe_get_bytes(url: str, timeout: int = 12) -> bytes:
    """
    用 requests 抓 RSS/XML（比 feedparser 直接 parse URL 更穩定）
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (NewsAggregator/1.0; +https://streamlit.io)",
        "Accept": "application/xml,text/xml,application/rss+xml,application/atom+xml,text/html,*/*",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.content

def _safe_get_json(url: str, params: Optional[dict] = None, timeout: int = 12) -> Any:
    headers = {
        "User-Agent": "Mozilla/5.0 (NewsAggregator/1.0; +https://streamlit.io)",
        "Accept": "application/json,text/plain,*/*",
    }
    r = requests.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

def parse_rss_time(entry) -> Optional[datetime.datetime]:
    # feedparser 標準欄位
    if getattr(entry, "published_parsed", None):
        return datetime.datetime(*entry.published_parsed[:6], tzinfo=pytz.utc).astimezone(HK_TZ)
    if getattr(entry, "updated_parsed", None):
        return datetime.datetime(*entry.updated_parsed[:6], tzinfo=pytz.utc).astimezone(HK_TZ)

    # 文字欄位嘗試 parse
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

def _chunk(lst: List[dict], n: int) -> List[List[dict]]:
    return [lst[i:i+n] for i in range(0, len(lst), n)]

# =====================
# Fetchers
# =====================
@st.cache_data(ttl=60)
def fetch_rss_today(url: str, color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    RSS：優先只顯示「今日」（香港時間）
    - 有時間：HH:MM
    - 無時間：顯示「今日」（fallback）
    - 若 RSS 讀取失敗／結構怪：回傳 error
    """
    today = now_hk().date()
    try:
        raw = _safe_get_bytes(url, timeout=12)
        feed = feedparser.parse(raw)

        dated: List[Article] = []
        undated: List[Article] = []

        for e in feed.entries or []:
            title = clean_text(getattr(e, "title", ""))
            link = getattr(e, "link", "")
            if not title or not link:
                continue

            dt = parse_rss_time(e)
            if dt and dt.date() == today:
                dated.append(Article(title, link, dt.strftime("%H:%M"), color))
            elif not dt:
                # 無法判斷日期：先當作可用候選
                undated.append(Article(title, link, "今日", color))

        if dated:
            return dated[:limit], None

        if undated:
            return undated[:limit], "此來源未提供可解析時間，已顯示最新條目並以「今日」標記"

        return [], None

    except Exception as e:
        return [], f"讀取失敗：{type(e).__name__}: {e}"

@st.cache_data(ttl=60)
def fetch_rss_latest(url: str, color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    RSS：永遠顯示最新（唔做今日過濾）
    """
    try:
        raw = _safe_get_bytes(url, timeout=12)
        feed = feedparser.parse(raw)

        out: List[Article] = []
        for e in (feed.entries or [])[:limit]:
            title = clean_text(getattr(e, "title", ""))
            link = getattr(e, "link", "")
            if not title or not link:
                continue

            dt = parse_rss_time(e)
            time_str = dt.strftime("%H:%M") if dt else "即時"
            out.append(Article(title, link, time_str, color))

        return out, None

    except Exception as e:
        return [], f"讀取失敗：{type(e).__name__}: {e}"

# =====================
# NOW（本地）API：你提供的 endpoint + 正確處理毫秒 timestamp
# =====================
NOW_API = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2"

@st.cache_data(ttl=60)
def fetch_now_local_today(color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    Now 新聞（本地）：
    - category=119
    - 只顯示今日（香港時間）
    - publishDate 係毫秒 timestamp → 必須 fromtimestamp(ts/1000)
    - 今日篩選為 0 時，fallback 顯示最新 10（並提示）
    """
    today = now_hk().date()
    out_today: List[Article] = []
    out_latest: List[Article] = []

    try:
        data = _safe_get_json(NOW_API, params={"category": 119, "pageNo": 1}, timeout=12)

        # 你貼出來的格式係 list 直接包住 dict
        candidates = None
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            # 保守掃 key
            for k in ("data", "list", "news", "items", "result"):
                v = data.get(k)
                if isinstance(v, list):
                    candidates = v
                    break
            if candidates is None:
                for v in data.values():
                    if isinstance(v, list):
                        candidates = v
                        break

        if not candidates:
            return [], "Now API 回傳結構已變（找不到新聞列表）"

        for it in candidates:
            if not isinstance(it, dict):
                continue

            title = clean_text(str(it.get("title") or it.get("newsTitle") or it.get("storyTitle") or ""))
            # Now 有時冇 webUrl/shareUrl：用 player?newsId=XXXX 兜底
            link = str(it.get("webUrl") or it.get("shareUrl") or it.get("url") or "")
            news_id = it.get("newsId") or it.get("id")

            if not link and news_id:
                link = f"https://news.now.com/home/local/player?newsId={news_id}"
            if link.startswith("/"):
                link = "https://news.now.com" + link

            raw_time = it.get("publishDate") or it.get("publishTime") or it.get("publishedAt") or it.get("date")

            dt = None
            time_str = "今日"
            if raw_time is not None:
                try:
                    # publishDate = 1767049974000（毫秒）
                    if isinstance(raw_time, (int, float)) or str(raw_time).isdigit():
                        ts = int(raw_time)
                        if ts > 1_000_000_000_000:  # > 1e12 視為毫秒
                            ts = ts / 1000
                        dt = datetime.datetime.fromtimestamp(ts, tz=HK_TZ)
                    else:
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
            return out_latest[:limit], "未能篩出『今日』新聞，已改為顯示最新 10 條（請確認 Now API 時間欄位）"

        return [], "Now API 有回傳但未能解析到有效新聞項目"

    except Exception as e:
        return [], f"Now API 讀取失敗：{type(e).__name__}: {e}"

# =====================
# Render（一次性輸出，避免 DOM 斷裂）
# =====================
def build_card_html(title: str, articles: List[Article], note: Optional[str] = None) -> str:
    if not articles:
        items_html = "<div class='empty'>今日暫無新聞</div>"
    else:
        parts = []
        for a in articles:
            parts.append(
                f"""
                <div class="item" style="border-left-color:{a.color}">
                  <a href="{a.link}" target="_blank" rel="noopener noreferrer">{html.escape(a.title)}</a>
                  <div class="item-meta">🕐 {html.escape(a.time_str)}</div>
                </div>
                """
            )
        items_html = "".join(parts)

    badge = f"""<span class="badge">{html.escape(note)}</span>""" if note else ""
    return f"""
    <div class="section-title">{html.escape(title)}{badge}</div>
    <div class="card">
      <div class="items">
        {items_html}
      </div>
    </div>
    """

# =====================
# Sources（你要求：唔好我自己揀）
# =====================
# 你之前用過嘅 RSSHub base（先放預設；你可在側欄輸入覆蓋）
DEFAULT_RSSHUB_BASE = "https://rsshub-production-9dfc.up.railway.app"

GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"

# =====================
# UI
# =====================
st.title("🗞️ 香港新聞聚合中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

with st.sidebar:
    st.subheader("設定")
    rsshub_base = st.text_input("RSSHub Base URL", value=DEFAULT_RSSHUB_BASE).strip().rstrip("/")
    auto = st.toggle("每分鐘自動更新", value=True)
    strict_today = st.toggle("RSS 只顯示今日", value=True)
    st.caption("提示：Now 使用官方 API（category=119），不走 RSSHub。")

if auto:
    st_autorefresh(interval=60_000, key="auto")

# 你要的媒體清單（官方 + RSSHub + Now API）
# type:
# - "rss_today": RSS（只顯示今日）
# - "rss_latest": RSS（最新）
# - "now_api_today": Now（今日 / fallback latest）
SOURCES: List[Dict[str, Any]] = [
    {"name": "政府新聞（中文）", "type": "rss_today", "url": GOV_ZH, "color": "#E74C3C"},
    {"name": "政府新聞（英文）", "type": "rss_today", "url": GOV_EN, "color": "#C0392B"},
    {"name": "RTHK", "type": "rss_today", "url": RTHK, "color": "#FF9800"},

    # Now：RSSHub 壞 -> 用 API
    {"name": "Now 新聞（本地）", "type": "now_api_today", "color": "#2563EB"},

    # 你列出的 RSSHub 香港媒體
    {"name": "HK01", "type": "rss_latest", "url": f"{rsshub_base}/hk01/latest", "color": "#7C3AED"},
    {"name": "on.cc 東網", "type": "rss_latest", "url": f"{rsshub_base}/oncc/zh-hant/news", "color": "#0EA5E9"},
    {"name": "TVB 新聞", "type": "rss_latest", "url": f"{rsshub_base}/tvb/news/tc", "color": "#1D4ED8"},
    {"name": "信報即時 (hkej)", "type": "rss_latest", "url": f"{rsshub_base}/hkej/index", "color": "#111827"},
    {"name": "星島即時", "type": "rss_latest", "url": f"{rsshub_base}/stheadline/std/realtime", "color": "#16A34A"},
    {"name": "i-CABLE 有線", "type": "rss_latest", "url": f"{rsshub_base}/icable/all", "color": "#F97316"},

    # 明報：你話「官方 RSS」，但你未提供 URL；唔會亂猜。
    # 你提供咗 URL 我再幫你加返去。
    # {"name": "明報", "type": "rss_latest", "url": "（請填入明報官方 RSS）", "color": "#DC2626"},
]

# =====================
# 取數（逐個 source）
# =====================
def get_articles(src: Dict[str, Any]) -> Tuple[List[Article], Optional[str]]:
    t = src["type"]
    color = src["color"]

    if t == "now_api_today":
        return fetch_now_local_today(color=color, limit=10)

    url = src.get("url", "")
    if not url:
        return [], "未設定 URL"

    if strict_today and t == "rss_today":
        return fetch_rss_today(url=url, color=color, limit=10)

    # 非 strict：用 latest
    return fetch_rss_latest(url=url, color=color, limit=10)

# =====================
# 排版：保持「橫向並列」；每行 4 格（你可改）
# =====================
PER_ROW = 4
rows = _chunk(SOURCES, PER_ROW)

for row in rows:
    cols = st.columns(len(row))
    for i, src in enumerate(row):
        arts, note = get_articles(src)
        with cols[i]:
            st.markdown(build_card_html(src["name"], arts, note), unsafe_allow_html=True)
