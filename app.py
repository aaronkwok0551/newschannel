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
import streamlit.components.v1 as components
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

def _safe_get_json(url: str, params: Optional[dict] = None, timeout: int = 12) -> Any:
    headers = {
        "User-Agent": "Mozilla/5.0 (Streamlit News Aggregator)",
        "Accept": "application/json,text/plain,*/*",
    }
    r = requests.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

def parse_time_from_rss(entry) -> Optional[datetime.datetime]:
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
# Render (iframe，避免把 HTML 當文字輸出)
# =====================
def build_card_html(title: str, articles: List[Article], note: Optional[str] = None, empty_hint: str = "今日暫無新聞") -> str:
    note_html = f"<span class='badge'>{clean_text(note)}</span>" if note else ""

    if not articles:
        items_html = f"<div class='empty'>{clean_text(empty_hint)}</div>"
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

    return f"""
    <div class="section-title">{html.escape(title)}{note_html}</div>
    <div class="card">
      <div class="items">
        {items_html}
      </div>
    </div>
    """

def render_card_iframe(card_inner_html: str, height: int = 560) -> None:
    full_html = f"""
    <html>
    <head>
      <meta charset="utf-8" />
      <style>
        html, body {{ margin:0; padding:0; font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }}
        .section-title{{ font-size:1.05rem; font-weight:800; margin:2px 0 8px 0; }}
        .card{{
          background:#ffffff;
          border:1px solid #e5e7eb;
          border-radius:12px;
          padding:12px;
          height:520px;
          display:flex;
          flex-direction:column;
          box-sizing:border-box;
        }}
        .items{{ overflow-y:auto; padding-right:6px; flex:1; }}
        .item{{ background:#ffffff; border-left:4px solid #3b82f6; border-radius:8px; padding:8px 10px; margin:8px 0; box-sizing:border-box; }}
        .item a{{ text-decoration:none; color:#111827; font-weight:600; line-height:1.35; display:block; }}
        .item a:hover{{ color:#ef4444; }}
        .item-meta{{ font-size:0.78rem; color:#6b7280; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; margin-top:2px; }}
        .badge{{ display:inline-block; font-size:0.72rem; padding:2px 8px; border-radius:999px; background:#f3f4f6; color:#374151; margin-left:8px; }}
        .empty{{ color:#9ca3af; text-align:center; margin-top:20px; }}
      </style>
    </head>
    <body>
      {card_inner_html}
    </body>
    </html>
    """
    components.html(full_html, height=height, scrolling=True)

# =====================
# Fetchers
# =====================
@st.cache_data(ttl=60)
def fetch_rss_today(url: str, color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    RSS：只顯示「今日（香港時間）」。
    重點修正：若 bozo(常見 div/html) 但其實有 entries → 先當「可用」，不顯示警告。
    只有真係冇 entries 或 0 news 才顯示警告。
    """
    today = now_hk().date()
    feed = feedparser.parse(url)

    entries = feed.entries or []

    # 先嘗試抽新聞；成功的話就唔顯示 bozo 警告（避免你見到成堆 div-class）
    dated: List[Article] = []
    undated_latest: List[Article] = []

    for e in entries:
        title = clean_text(getattr(e, "title", "") or "")
        link = getattr(e, "link", "") or ""
        if not title or not link:
            continue

        dt = parse_time_from_rss(e)
        if dt and dt.date() == today:
            dated.append(Article(title=title, link=link, time_str=dt.strftime("%H:%M"), color=color))
        else:
            undated_latest.append(Article(title=title, link=link, time_str="今日", color=color))

        if len(undated_latest) >= limit * 3:
            break

    # 有今日就直接回傳（不警告）
    if dated:
        return dated[:limit], None

    # 今日冇但有內容 → fallback 最新（不顯示 bozo 警告）
    if undated_latest:
        return undated_latest[:limit], "未能篩出『今日』或 RSS 無日期欄位，已改為顯示最新 10 條"

    # 真係冇內容 → 呢個時候先提示 bozo/錯
    if getattr(feed, "bozo", 0):
        err = str(getattr(feed, "bozo_exception", "RSS 解析失敗"))
        return [], f"RSS 解析失敗/被擋（{err}）"
    return [], "讀取失敗或無內容"

@st.cache_data(ttl=60)
def fetch_now_local_today(now_api_url: str, color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    Now 新聞（本地）：
    - 用你可用的 API
    - 今日=0 但有回傳 → fallback 最新10
    """
    today = now_hk().date()
    out_today: List[Article] = []
    out_latest: List[Article] = []

    try:
        data = _safe_get_json(now_api_url, params=None, timeout=12)

        candidates = None
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            for k in ("data", "list", "news", "items", "result"):
                v = data.get(k)
                if isinstance(v, list):
                    candidates = v
                    break

        if not candidates:
            return [], "Now API 回傳結構已變（找不到新聞列表）"

        for it in candidates:
            if not isinstance(it, dict):
                continue

            title = clean_text(str(it.get("title") or it.get("newsTitle") or it.get("storyTitle") or ""))
            news_id = str(it.get("newsId") or "").strip()

            link = str(it.get("webUrl") or it.get("shareUrl") or it.get("url") or it.get("link") or "").strip()
            if not link and news_id:
                link = f"https://news.now.com/home/local/player?newsId={news_id}"
            if link.startswith("/"):
                link = "https://news.now.com" + link

            time_str = "今日"
            dt = None
            raw_time = it.get("publishDate") or it.get("publishTime") or it.get("publishedAt") or it.get("date")
            if raw_time is not None and raw_time != "":
                try:
                    if isinstance(raw_time, (int, float)) or (isinstance(raw_time, str) and raw_time.isdigit()):
                        ts = int(raw_time)
                        if ts > 10**12:
                            ts = ts / 1000.0
                        dt = datetime.datetime.fromtimestamp(ts, tz=HK_TZ)
                        time_str = dt.strftime("%H:%M")
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
            return out_latest[:limit], "未能篩出『今日』新聞，已改為顯示最新 10 條"
        return [], "Now API 有回傳但未能解析到有效新聞項目"

    except Exception as e:
        return [], f"Now API 讀取失敗：{type(e).__name__}: {e}"

# =====================
# UI
# =====================
st.title("🗞️ 香港新聞聚合中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

with st.sidebar:
    st.subheader("設定")
    st.write("RSSHub Base（例如：https://rsshub.xxx.com ）")
    rsshub_base = st.text_input("RSSHub Base URL", value="https://rsshub-production-9dfc.up.railway.app").rstrip("/")
    st.write("Now API（你提供可用的）")
    now_api = st.text_input(
        "Now API URL",
        value="https://newsapi1.now.com/pccw-news-api/api/getNewsListv2?category=119&pageNo=1",
    ).strip()

    auto = st.toggle("每分鐘自動更新", value=True)
    limit = st.number_input("每個平台顯示條數", min_value=3, max_value=30, value=10, step=1)

    st.write("明報官方 RSS（可留空）")
    mingpao_rss = st.text_input("明報 RSS", value="").strip()

if auto:
    st_autorefresh(interval=60_000, key="auto")

# =====================
# Sources
# =====================
GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"

HK01 = f"{rsshub_base}/hk01/latest"
ONCC = f"{rsshub_base}/oncc/zh-hant/news"
TVB = f"{rsshub_base}/tvb/news/tc"
HKEJ = f"{rsshub_base}/hkej/index"
STHEADLINE = f"{rsshub_base}/stheadline/std/realtime"
ICABLE = f"{rsshub_base}/icable/all"

# =====================
# 固定 4 欄對齊：每行必定 4 格，不足用空白卡補
# =====================
def empty_src(title: str = "") -> Dict[str, Any]:
    return {"name": title or " ", "kind": "empty", "url": "", "color": "#E5E7EB"}

# 你要求：平台橫向並列；完全對齊（每行4格）
rows: List[List[Dict[str, Any]]] = [
    [
        {"name": "政府新聞（中文）", "kind": "rss_today", "url": GOV_ZH, "color": "#E74C3C"},
        {"name": "政府新聞（英文）", "kind": "rss_today", "url": GOV_EN, "color": "#C0392B"},
        {"name": "RTHK", "kind": "rss_today", "url": RTHK, "color": "#FF9800"},
        {"name": "Now（本地）", "kind": "now_api_today", "url": now_api, "color": "#22C55E"},
    ],
    [
        {"name": "HK01", "kind": "rss_today", "url": HK01, "color": "#2563EB"},
        {"name": "東網 on.cc", "kind": "rss_today", "url": ONCC, "color": "#111827"},
        {"name": "TVB 新聞", "kind": "rss_today", "url": TVB, "color": "#7C3AED"},
        {"name": "信報即時", "kind": "rss_today", "url": HKEJ, "color": "#0EA5E9"},
    ],
    [
        {"name": "星島即時", "kind": "rss_today", "url": STHEADLINE, "color": "#F59E0B"},
        {"name": "i-CABLE 有線", "kind": "rss_today", "url": ICABLE, "color": "#EF4444"},
        {"name": "明報（官方 RSS）", "kind": "rss_today", "url": mingpao_rss, "color": "#64748B"},
        empty_src(),  # 補齊第4格，保持對齊
    ],
]

def get_articles(src: Dict[str, Any], limit_n: int) -> Tuple[List[Article], Optional[str], str]:
    kind = src["kind"]
    url = (src.get("url") or "").strip()

    if kind == "empty":
        return [], None, " "

    if not url:
        return [], "未設定來源 URL", "未設定來源 URL"

    if kind == "rss_today":
        arts, note = fetch_rss_today(url, src["color"], limit=limit_n)
        return arts, note, ("今日暫無新聞" if not arts else " ")

    if kind == "now_api_today":
        arts, note = fetch_now_local_today(url, src["color"], limit=limit_n)
        return arts, note, ("今日暫無新聞" if not arts else " ")

    return [], "未知來源類型", "未知來源類型"

# =====================
# Render
# =====================
for row in rows:
    cols = st.columns(4, gap="small")
    for i in range(4):
        src = row[i]
        with cols[i]:
            arts, note, empty_hint = get_articles(src, int(limit))
            render_card_iframe(build_card_html(src["name"], arts, note, empty_hint=empty_hint), height=560)
