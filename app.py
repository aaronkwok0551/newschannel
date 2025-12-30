# app.py
# -*- coding: utf-8 -*-

import datetime
import html
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict

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
# CSS（不改排版，只加 new 高亮樣式）
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

.item a{
  text-decoration:none;color:#111827;font-weight:600;line-height:1.35;
}
.item a:hover{ color:#ef4444; }

.item-meta{
  font-size:0.78rem;color:#6b7280;font-family:monospace;margin-top:2px;
}

.empty{ color:#9ca3af;text-align:center;margin-top:20px; }

/* NEW: 新聞 20 分鐘紅色提示（不改 layout） */
.item.new{
  border-left-color:#ef4444 !important;
  background: rgba(239,68,68,0.06);
}
.item.new a{
  color:#b91c1c;
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
    dt: Optional[datetime.datetime] = None  # 用於排序（最新在上）

# =====================
# Helpers
# =====================
def now_hk() -> datetime.datetime:
    return datetime.datetime.now(HK_TZ)

def clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    soup = BeautifulSoup(raw, "html.parser")
    return soup.get_text(" ", strip=True)

def parse_time_from_feed_entry(entry) -> Optional[datetime.datetime]:
    # feedparser 標準欄位
    if getattr(entry, "published_parsed", None):
        return datetime.datetime(*entry.published_parsed[:6], tzinfo=pytz.utc).astimezone(HK_TZ)
    if getattr(entry, "updated_parsed", None):
        return datetime.datetime(*entry.updated_parsed[:6], tzinfo=pytz.utc).astimezone(HK_TZ)

    # 文字欄位嘗試 parse
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

def _safe_get_json(url: str, params: Optional[dict] = None, timeout: int = 12):
    r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()

def _epoch_ms_to_dt(ms: int) -> datetime.datetime:
    # Now API publishDate = epoch ms
    return datetime.datetime.fromtimestamp(ms / 1000.0, tz=HK_TZ)

def sort_articles_latest_first(items: List[Article]) -> List[Article]:
    # dt 有 -> 由新到舊；dt 無 -> 放最後
    def key(a: Article):
        return a.dt or datetime.datetime(1970, 1, 1, tzinfo=HK_TZ)
    return sorted(items, key=key, reverse=True)

# =====================
# Fetchers
# =====================
@st.cache_data(ttl=60)
def fetch_rss_today(url: str, color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    RSS（政府/RTHK/明報等）：
    - 只顯示今日（香港時間）
    - 有時間：HH:MM
    - 冇時間但可判斷日期：顯示「今日」（並用 dt=今日 00:00 排序到較後）
    - 完全冇日期：fallback 取最新10（time_str=今日，dt=None）
    """
    feed = feedparser.parse(url)
    today = now_hk().date()

    out_today: List[Article] = []
    out_undated: List[Article] = []

    for e in feed.entries or []:
        title = clean_text(getattr(e, "title", ""))
        link = getattr(e, "link", "")
        if not title or not link:
            continue

        dt = parse_time_from_feed_entry(e)
        if dt:
            if dt.date() == today:
                out_today.append(Article(title=title, link=link, time_str=dt.strftime("%H:%M"), color=color, dt=dt))
        else:
            # 冇時間冇日期：先放入 undated，可能會 fallback 用
            out_undated.append(Article(title=title, link=link, time_str="今日", color=color, dt=None))

    if out_today:
        out_today = sort_articles_latest_first(out_today)[:limit]
        return out_today, None

    if out_undated:
        return out_undated[:limit], "此來源未提供可解析時間／日期，已改為顯示最新 10 條（時間顯示『今日』）"

    return [], "RSS 無內容或暫時讀取不到"

@st.cache_data(ttl=60)
def fetch_rss_latest(url: str, color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    RSS（不做今日過濾）：取最新 10，並按 dt 排序（如果有）
    """
    feed = feedparser.parse(url)
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
        out = sort_articles_latest_first(out)
        return out, None
    return [], "RSS 無內容或暫時讀取不到"

@st.cache_data(ttl=60)
def fetch_now_local_today(color: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    Now 新聞（本地）：
    - category=119
    - 只顯示今日（香港時間）
    - publishDate 為 epoch ms
    """
    today = now_hk().date()
    NOW_API = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2"

    out_today: List[Article] = []
    out_latest: List[Article] = []

    try:
        data = _safe_get_json(NOW_API, {"category": 119, "pageNo": 1}, timeout=12)

        # Now 有時直接回 list，有時回 dict 包 list
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

            title = clean_text(str(it.get("newsTitle") or it.get("title") or it.get("headline") or ""))
            link = str(it.get("webUrl") or it.get("shareUrl") or it.get("url") or it.get("link") or "")
            if link.startswith("/"):
                link = "https://news.now.com" + link

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
            out_today = sort_articles_latest_first(out_today)[:limit]
            return out_today, None

        if out_latest:
            out_latest = sort_articles_latest_first(out_latest)[:limit]
            return out_latest, "未能篩出『今日』新聞，已改為顯示最新 10 條（請確認 publishDate 時區／格式）"

        return [], "Now API 有回傳但未能解析到有效新聞項目"

    except Exception as e:
        return [], f"Now API 讀取失敗：{type(e).__name__}: {e}"

# =====================
# NEW: 新聞「第一次見到」追蹤 + 20 分鐘紅色
# =====================
def _init_seen_state():
    if "seen_map" not in st.session_state:
        # link -> first_seen_epoch (seconds)
        st.session_state["seen_map"] = {}

def mark_and_check_is_new(link: str) -> bool:
    """
    回傳：此新聞是否屬於「新出現後 20 分鐘內」
    """
    _init_seen_state()
    seen_map: Dict[str, float] = st.session_state["seen_map"]
    now_ts = time.time()

    if link not in seen_map:
        seen_map[link] = now_ts
        st.session_state["seen_map"] = seen_map
        return True

    first = seen_map[link]
    return (now_ts - first) <= (NEW_HIGHLIGHT_MINUTES * 60)

# =====================
# Render（一次性輸出，避免 DOM 斷裂；並加入 new class）
# =====================
def build_card_html(title: str, articles: List[Article], note: Optional[str] = None) -> str:
    if not articles:
        items_html = "<div class='empty'>今日暫無新聞</div>"
    else:
        parts = []
        for a in articles:
            is_new = mark_and_check_is_new(a.link)
            new_cls = " new" if is_new else ""
            parts.append(
                f"""
                <div class="item{new_cls}" style="border-left-color:{a.color}">
                  <a href="{a.link}" target="_blank" rel="noopener noreferrer">{a.title}</a>
                  <div class="item-meta">🕐 {a.time_str}</div>
                </div>
                """
            )
        items_html = "".join(parts)

    note_html = f"<div class='item-meta' style='margin:0 0 6px 0;'>⚠️ {html.escape(note)}</div>" if note else ""

    return f"""
    <div class="section-title">{title}</div>
    <div class="card">
      {note_html}
      <div class="items">
        {items_html}
      </div>
    </div>
    """

# =====================
# URLs（你既 rsshub domain）
# =====================
RSSHUB = "https://rsshub-production-9dfc.up.railway.app"

GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"

# 你列出既 RSSHub routes
HK01 = f"{RSSHUB}/hk01/latest"
ONCC = f"{RSSHUB}/oncc/zh-hant/news"
TVB = f"{RSSHUB}/tvb/news/tc"
HKEJ = f"{RSSHUB}/hkej/index"
STHEADLINE = f"{RSSHUB}/stheadline/std/realtime"
ICABLE = f"{RSSHUB}/icable/all"

# =====================
# UI
# =====================
st.title("🗞️ 香港新聞聚合中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}｜新出現新聞紅色維持 {NEW_HIGHLIGHT_MINUTES} 分鐘")

if st.toggle("每分鐘自動更新", value=True):
    st_autorefresh(interval=60_000, key="auto")

# 你話「現在很好，不要修改排版了」：以下只維持橫向並列 column（你可自行按你原本想要嘅數量調整）
# 如你原本係「每行 4 個」，就 keep 4；如果你係「每行 5/6 個」，你照加多幾個 column group。
row1 = st.columns(4)
row2 = st.columns(4)
row3 = st.columns(4)

# ---------- Row 1 ----------
with row1[0]:
    items, note = fetch_rss_today(GOV_ZH, "#E74C3C")
    st.markdown(build_card_html("政府新聞（中文）", sort_articles_latest_first(items), note), unsafe_allow_html=True)

with row1[1]:
    items, note = fetch_rss_today(GOV_EN, "#C0392B")
    st.markdown(build_card_html("政府新聞（英文）", sort_articles_latest_first(items), note), unsafe_allow_html=True)

with row1[2]:
    items, note = fetch_rss_today(RTHK, "#FF9800")
    st.markdown(build_card_html("RTHK", sort_articles_latest_first(items), note), unsafe_allow_html=True)

with row1[3]:
    items, note = fetch_now_local_today("#10B981")
    st.markdown(build_card_html("Now（港聞 119）", sort_articles_latest_first(items), note), unsafe_allow_html=True)

# ---------- Row 2 ----------
with row2[0]:
    items, note = fetch_rss_latest(HK01, "#3B82F6")
    st.markdown(build_card_html("HK01", sort_articles_latest_first(items), note), unsafe_allow_html=True)

with row2[1]:
    items, note = fetch_rss_latest(ONCC, "#111827")
    st.markdown(build_card_html("on.cc 東網", sort_articles_latest_first(items), note), unsafe_allow_html=True)

with row2[2]:
    items, note = fetch_rss_latest(TVB, "#1D4ED8")
    st.markdown(build_card_html("TVB 新聞", sort_articles_latest_first(items), note), unsafe_allow_html=True)

with row2[3]:
    items, note = fetch_rss_latest(HKEJ, "#7C3AED")
    st.markdown(build_card_html("信報即時", sort_articles_latest_first(items), note), unsafe_allow_html=True)

# ---------- Row 3 ----------
with row3[0]:
    items, note = fetch_rss_latest(STHEADLINE, "#F59E0B")
    st.markdown(build_card_html("星島即時", sort_articles_latest_first(items), note), unsafe_allow_html=True)

with row3[1]:
    items, note = fetch_rss_latest(ICABLE, "#EF4444")
    st.markdown(build_card_html("i-CABLE 有線", sort_articles_latest_first(items), note), unsafe_allow_html=True)

with row3[2]:
    st.markdown(build_card_html("（預留）", [], None), unsafe_allow_html=True)

with row3[3]:
    st.markdown(build_card_html("（預留）", [], None), unsafe_allow_html=True)
