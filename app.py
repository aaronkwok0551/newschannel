# app.py
# -*- coding: utf-8 -*-

import datetime
import html
import re
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict

import feedparser
import pytz
import requests
import streamlit as st
from bs4 import BeautifulSoup
from streamlit_autorefresh import st_autorefresh


# =====================
# Runtime / Encoding
# =====================
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HK_TZ = pytz.timezone("Asia/Hong_Kong")


# =====================
# Streamlit Page Config
# =====================
st.set_page_config(page_title="香港新聞聚合中心", layout="wide", page_icon="🗞️")


# =====================
# CSS (固定高度 + 水平對齊 + 不鋸齒)
# =====================
st.markdown(
    """
<style>
body { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

.header-wrap { margin-bottom: 10px; }
.caption { color:#6b7280; font-size: 0.9rem; }

.grid-row { margin-top: 6px; }

.section-title{
  font-size:1.05rem;font-weight:800;margin:4px 0 10px 0;color:#111827;
}

.card{
  background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;
  padding:12px;
  height:540px;
  display:flex;flex-direction:column;
}

.card-head{
  display:flex;align-items:center;justify-content:space-between;
  margin-bottom:8px;
}

.card-name{
  font-size:1.0rem;font-weight:800;color:#111827;
}

.badge{
  display:inline-block;
  padding:2px 8px;border-radius:999px;
  font-size:0.75rem;font-weight:700;
  border:1px solid #e5e7eb;background:#f9fafb;color:#374151;
}

.badge-warn{
  background:#fff7ed;border-color:#fed7aa;color:#9a3412;
}

.hint{
  font-size:0.78rem;color:#6b7280;margin:0 0 6px 0;
}

.items{ overflow-y:auto; padding-right:6px; flex:1; }

.item{
  background:#fff;border-left:4px solid #3b82f6;border-radius:10px;
  padding:8px 10px;margin:8px 0;
}

.item a{
  text-decoration:none;color:#111827;font-weight:650;line-height:1.35;
  display:block;
}
.item a:hover{ color:#ef4444; }

.item-meta{
  font-size:0.78rem;color:#6b7280;font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono","Courier New", monospace;
  margin-top:2px;
}

.empty{ color:#9ca3af;text-align:center;margin-top:18px; }
hr { border:none;border-top:1px solid #e5e7eb;margin:14px 0; }
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

def today_hk() -> datetime.date:
    return now_hk().date()

def clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def parse_feed_entry_dt(entry) -> Optional[datetime.datetime]:
    """
    RSS entries:
    - Prefer published_parsed / updated_parsed (struct_time)
    - Else try common string fields
    """
    stime = None
    if getattr(entry, "published_parsed", None):
        stime = entry.published_parsed
    elif getattr(entry, "updated_parsed", None):
        stime = entry.updated_parsed

    if stime:
        dt_utc = datetime.datetime(*stime[:6], tzinfo=pytz.utc)
        return dt_utc.astimezone(HK_TZ)

    # fallback: try strings (best-effort)
    for k in ("published", "updated", "pubDate"):
        v = getattr(entry, k, None)
        if v:
            try:
                # very small parser: let feedparser do main work; if string appears, skip strict parse
                # Use datetime.fromisoformat only if looks like ISO; else ignore to avoid false positives.
                s = str(v)
                if "T" in s and ("+" in s or "Z" in s):
                    s = s.replace("Z", "+00:00")
                    dt = datetime.datetime.fromisoformat(s)
                    if dt.tzinfo is None:
                        dt = HK_TZ.localize(dt)
                    return dt.astimezone(HK_TZ)
            except Exception:
                pass
    return None


# =====================
# Render (一次性輸出，避免 HTML 被當文字)
# =====================
def build_card_html(title: str, articles: List[Article], warn: Optional[str] = None) -> str:
    badge_html = ""
    hint_html = ""

    if warn:
        badge_html = '<span class="badge badge-warn">注意</span>'
        hint_html = f'<div class="hint">⚠️ {html.escape(warn)}</div>'
    else:
        badge_html = '<span class="badge">今日</span>'

    if not articles:
        items_html = "<div class='empty'>今日暫無新聞</div>"
    else:
        parts = []
        for a in articles:
            parts.append(
                f"""
                <div class="item" style="border-left-color:{a.color};">
                  <a href="{html.escape(a.link)}" target="_blank" rel="noopener noreferrer">{html.escape(a.title)}</a>
                  <div class="item-meta">🕐 {html.escape(a.time_str)}</div>
                </div>
                """
            )
        items_html = "".join(parts)

    return f"""
    <div class="card">
      <div class="card-head">
        <div class="card-name">{html.escape(title)}</div>
        {badge_html}
      </div>
      {hint_html}
      <div class="items">
        {items_html}
      </div>
    </div>
    """


# =====================
# Fetchers
# =====================
def _safe_get_json(url: str, params: dict, timeout: int = 12):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; HKNewsAggregator/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://news.now.com/",
        "Origin": "https://news.now.com",
    }
    r = requests.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _now_ms_to_hk(ms: int) -> Optional[datetime.datetime]:
    try:
        dt_utc = datetime.datetime.fromtimestamp(int(ms) / 1000, tz=pytz.utc)
        return dt_utc.astimezone(HK_TZ)
    except Exception:
        return None


@st.cache_data(ttl=60)
def fetch_rss_today_or_top10(url: str, color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    你的規則：
    - 優先嚴格顯示「今日」
    - 如果來源無法判斷日期/時間：讀取頭 10 條，並把時間欄改成「今日 YYYY-MM-DD」
    """
    feed = feedparser.parse(url)
    entries = feed.entries or []
    if not entries:
        return [], "來源無條目或暫時無法讀取"

    today = today_hk()
    out_today: List[Article] = []
    out_top: List[Article] = []
    undated_count = 0

    for e in entries:
        title = clean_text(getattr(e, "title", ""))
        link = getattr(e, "link", "")
        if not title or not link:
            continue

        dt = parse_feed_entry_dt(e)
        if dt is None:
            undated_count += 1
            out_top.append(Article(title=title, link=link, time_str=f"今日 {today.strftime('%Y-%m-%d')}", color=color))
        else:
            if dt.date() == today:
                out_today.append(Article(title=title, link=link, time_str=dt.strftime("%H:%M"), color=color))

        # 收集 top10 備用
        if len(out_top) < limit and dt is not None:
            out_top.append(Article(title=title, link=link, time_str=dt.strftime("%H:%M"), color=color))

        if len(out_today) >= limit and len(out_top) >= limit:
            break

    if out_today:
        return out_today[:limit], None

    # 今日為 0：按你的要求，取頭 10 條並「編修沒有時間」
    warn = "未能篩出『今日』新聞（或時間欄位缺失），已顯示最新 10 條並以『今日』標示"
    if undated_count == 0:
        warn = "來源回傳時間可能非香港時間或格式改動，已顯示最新 10 條"
    return out_top[:limit], warn


# ---- Now：不用 RSSHub，直接 XHR JSON ----
NOW_API = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2"

@st.cache_data(ttl=60)
def fetch_now_local_today(limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    Now 本地：category=119
    - 支援 root list（你貼的格式）
    - publishDate = 毫秒 timestamp
    - webUrl 可能為 null：用 newsId 組 player link
    - 嚴格今日；若今日篩不到但有資料：fallback 最新10
    """
    color = "#3B82F6"
    today = today_hk()
    out_today: List[Article] = []
    out_latest: List[Article] = []

    try:
        data = _safe_get_json(NOW_API, {"category": 119, "pageNo": 1}, timeout=12)

        # root 可能係 list 或 dict
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            # 兼容另一種包裝
            candidates = None
            for k in ("data", "list", "news", "items", "result"):
                v = data.get(k)
                if isinstance(v, list):
                    candidates = v
                    break
            if candidates is None:
                # 再掃一層
                for v in data.values():
                    if isinstance(v, dict):
                        for kk in ("data", "list", "news", "items", "result"):
                            vv = v.get(kk)
                            if isinstance(vv, list):
                                candidates = vv
                                break
                    if candidates is not None:
                        break
            if candidates is None:
                candidates = []
        else:
            candidates = []

        if not candidates:
            return [], "Now API 無可用資料（可能改版或被封鎖）"

        for it in candidates:
            if not isinstance(it, dict):
                continue

            title = clean_text(str(it.get("title") or it.get("newsTitle") or ""))
            if not title:
                continue

            dt = _now_ms_to_hk(it.get("publishDate")) if it.get("publishDate") is not None else None
            time_str = dt.strftime("%H:%M") if dt else f"今日 {today.strftime('%Y-%m-%d')}"

            news_id = it.get("newsId")
            link = it.get("webUrl") or it.get("shareUrl") or it.get("url") or ""
            if not link:
                if news_id:
                    link = f"https://news.now.com/home/local/player?newsId={news_id}"
                else:
                    continue

            art = Article(title=title, link=link, time_str=time_str, color=color)
            out_latest.append(art)
            if dt and dt.date() == today:
                out_today.append(art)

            if len(out_latest) >= limit:
                break

        if out_today:
            return out_today[:limit], None

        if out_latest:
            return out_latest[:limit], "未能以時間欄位篩出『今日』，已顯示最新 10 條"
        return [], "Now API 有回傳但未能解析到有效新聞"

    except Exception as e:
        return [], f"Now API 讀取失敗：{type(e).__name__}: {e}"


# =====================
# Sources (按你指定)
# =====================
RSSHUB_BASE = "https://rsshub-production-9dfc.up.railway.app"

# 官方 RSS
GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"
MINGPAO = "https://news.mingpao.com/rss/ins/s00001.xml"
HKET = "https://www.hket.com/rss/hongkong"

# RSSHub routes（你提供）
RSSHUB_SOURCES: List[Tuple[str, str, str]] = [
    ("HK01（最新）", f"{RSSHUB_BASE}/hk01/latest", "#1F4E79"),
    ("on.cc 東網（即時）", f"{RSSHUB_BASE}/oncc/zh-hant/news", "#111827"),
    ("TVB 新聞（本地）", f"{RSSHUB_BASE}/tvb/news/tc", "#10B981"),
    ("信報即時（HKEJ）", f"{RSSHUB_BASE}/hkej/index", "#7C3AED"),
    ("星島即時", f"{RSSHUB_BASE}/stheadline/std/realtime", "#DC2626"),
    ("i-CABLE 有線（即時）", f"{RSSHUB_BASE}/icable/all", "#EF4444"),
]

# 你提到商業電台不準：先不硬加，保留你日後填入
# COMMERCIAL_RADIO = ( "商業電台", f"{RSSHUB_BASE}/xxx/xxx", "#2563EB" )


# =====================
# UI
# =====================
st.markdown('<div class="header-wrap">', unsafe_allow_html=True)
st.markdown("## 🗞️ 香港新聞聚合中心")
st.markdown(f'<div class="caption">最後更新（香港時間）：{now_hk().strftime("%Y-%m-%d %H:%M:%S")}</div>', unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

auto = st.toggle("每分鐘自動更新", value=True)
if auto:
    st_autorefresh(interval=60_000, key="auto_refresh_60s")

st.markdown("<hr/>", unsafe_allow_html=True)

# ===== 第一行：政府中 / 政府英 / RTHK / Now本地 =====
row1 = st.columns(4, gap="medium")

with row1[0]:
    arts, warn = fetch_rss_today_or_top10(GOV_ZH, "#E74C3C", limit=10)
    st.markdown(build_card_html("政府新聞（中文）", arts, warn), unsafe_allow_html=True)

with row1[1]:
    arts, warn = fetch_rss_today_or_top10(GOV_EN, "#C0392B", limit=10)
    st.markdown(build_card_html("政府新聞（英文）", arts, warn), unsafe_allow_html=True)

with row1[2]:
    arts, warn = fetch_rss_today_or_top10(RTHK, "#FF9800", limit=10)
    st.markdown(build_card_html("RTHK（本地）", arts, warn), unsafe_allow_html=True)

with row1[3]:
    arts, warn = fetch_now_local_today(limit=10)
    st.markdown(build_card_html("Now 新聞（本地）", arts, warn), unsafe_allow_html=True)

st.markdown("<hr/>", unsafe_allow_html=True)

# ===== 第二部分：其餘媒體（每行 5 個，水平對齊）=====
st.markdown('<div class="section-title">其他新聞媒體（每個來源 10 條、優先今日）</div>', unsafe_allow_html=True)

other_sources: List[Tuple[str, str, str]] = []
# 你提到的「經濟日報」、「明報」官方 RSS
other_sources.append(("經濟日報 HKET（港聞）", HKET, "#6B7280"))
other_sources.append(("明報（即時）", MINGPAO, "#374151"))
# RSSHub 媒體
other_sources.extend(RSSHUB_SOURCES)

# 每行 5 個
per_row = 5
for i in range(0, len(other_sources), per_row):
    cols = st.columns(per_row, gap="medium")
    chunk = other_sources[i:i + per_row]
    for j in range(per_row):
        with cols[j]:
            if j >= len(chunk):
                # 空位補齊，保持對齊
                st.markdown('<div class="card"><div class="empty"> </div></div>', unsafe_allow_html=True)
                continue
            name, url, color = chunk[j]
            arts, warn = fetch_rss_today_or_top10(url, color, limit=10)
            st.markdown(build_card_html(name, arts, warn), unsafe_allow_html=True)

st.caption(
    "備註：若某來源長期顯示『來源無條目或暫時無法讀取』，多半是 RSSHub 路徑或上游網站改版；只需更新該來源 URL。"
)
