# app.py
# -*- coding: utf-8 -*-

import datetime
import html
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
from textwrap import dedent

# =====================
# 基本設定
# =====================
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HK_TZ = pytz.timezone("Asia/Hong_Kong")

st.set_page_config(page_title="Tommy Sir後援會之新聞中心", layout="wide", page_icon="🗞️")

# =====================
# CSS（包含：新新聞 20 分鐘紅色）
# =====================
st.markdown(
    dedent(
        """
        <style>
        body { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

        .section-title{
          font-size:1.05rem;font-weight:800;margin:2px 0 8px 0;
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

        /* 新新聞（20 分鐘內） */
        .item.new{
          border-left-color:#ef4444 !important;
          box-shadow: 0 0 0 1px rgba(239,68,68,0.25);
        }
        .item.new a{ color:#b91c1c !important; }

        .item a{
          text-decoration:none;color:#111827;font-weight:600;line-height:1.35;
        }
        .item a:hover{ color:#ef4444; }

        .item-meta{
          font-size:0.78rem;color:#6b7280;font-family:monospace;margin-top:2px;
        }

        .empty{ color:#9ca3af;text-align:center;margin-top:20px; }
        .warn{ color:#b45309;font-size:0.85rem;margin:6px 0 0 0; }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

# =====================
# Model
# =====================
@dataclass
class Article:
    title: str
    link: str
    dt: Optional[datetime.datetime]  # HK time
    time_str: str
    color: str
    is_new: bool = False

# =====================
# Helpers
# =====================
def now_hk() -> datetime.datetime:
    return datetime.datetime.now(HK_TZ)

def clean_text(raw: str) -> str:
    """把 RSS/JSON 裡的 HTML 轉純文字；div class 本身唔會再出現。"""
    raw = html.unescape(raw or "")
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    # 再保守清理一下
    return " ".join(text.split())

def parse_time_from_entry(entry) -> Optional[datetime.datetime]:
    """feedparser 時間解析（有就轉 HK time，冇就 None）"""
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

def chunked(lst: List, n: int) -> List[List]:
    return [lst[i:i+n] for i in range(0, len(lst), n)]

def mark_new_by_first_seen(articles: List[Article], window_minutes: int = 20) -> None:
    """
    用「第一次見到該 link 的時間」判斷新新聞，
    不依賴 feed 的 publish time（因為好多 RSS 係冇/唔準）。
    """
    if "seen_links" not in st.session_state:
        st.session_state["seen_links"] = {}  # link -> first_seen_iso

    seen: Dict[str, str] = st.session_state["seen_links"]
    now = now_hk()
    window = datetime.timedelta(minutes=window_minutes)

    for a in articles:
        if not a.link:
            continue
        if a.link not in seen:
            seen[a.link] = now.isoformat()

        try:
            first_seen = dtparser.parse(seen[a.link])
            if first_seen.tzinfo is None:
                first_seen = HK_TZ.localize(first_seen)
            first_seen = first_seen.astimezone(HK_TZ)
            a.is_new = (now - first_seen) <= window
        except Exception:
            a.is_new = False

    st.session_state["seen_links"] = seen

# =====================
# Fetchers
# =====================
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Streamlit; HK News Aggregator)",
    "Accept": "*/*",
}

@st.cache_data(ttl=60)
def fetch_rss(url: str, color: str, limit: int = 12) -> Tuple[List[Article], Optional[str]]:
    """
    通用 RSS / RSSHub：
    - 取最新 limit
    - 盡量解析時間（能排就排）
    - title/summary 全部轉純文字（唔會再出現 div class）
    """
    try:
        r = requests.get(url, timeout=15, headers=DEFAULT_HEADERS)
        r.raise_for_status()

        feed = feedparser.parse(r.content)
        if not feed.entries:
            return [], "未有 entries（可能來源暫時無更新／或 RSSHub 路由變更）"

        out: List[Article] = []
        for e in feed.entries[: (limit * 3)]:  # 多抓少少再篩
            title = clean_text(getattr(e, "title", "") or "")
            link = getattr(e, "link", "") or ""
            if not title or not link:
                continue

            dt = parse_time_from_entry(e)
            time_str = dt.strftime("%H:%M") if dt else "—"

            out.append(Article(title=title, link=link, dt=dt, time_str=time_str, color=color))
            if len(out) >= limit:
                break

        if not out:
            return [], "有 entries 但未能抽取到有效 title/link"
        return out, None

    except requests.HTTPError as e:
        return [], f"HTTPError: {e}"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"

@st.cache_data(ttl=60)
def fetch_now_api(color: str, limit: int = 12) -> Tuple[List[Article], Optional[str]]:
    """
    Now（本地）用 API：
    https://newsapi1.now.com/pccw-news-api/api/getNewsListv2?category=119&pageNo=1

    注意：Now 回傳 JSON 內某些欄位含 HTML 係正常；我哋只抽 title/link/time。
    """
    NOW_URL = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2"
    params = {"category": 119, "pageNo": 1}

    try:
        r = requests.get(NOW_URL, params=params, timeout=15, headers=DEFAULT_HEADERS)
        r.raise_for_status()

        data = r.json()
        # Now 可能係 list 或 dict；你貼過係 list[dict]
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
                # 再掃一層
                for v in data.values():
                    if isinstance(v, list):
                        candidates = v
                        break
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

        out: List[Article] = []
        for it in candidates:
            if not isinstance(it, dict):
                continue

            title = clean_text(str(it.get("title") or it.get("newsTitle") or it.get("headline") or ""))
            news_id = str(it.get("newsId") or "").strip()

            # link：用 now 網站 player（最穩定）
            link = ""
            if news_id:
                link = f"https://news.now.com/home/local/player?newsId={news_id}"
            else:
                raw = str(it.get("shareUrl") or it.get("url") or it.get("link") or "").strip()
                if raw.startswith("/"):
                    raw = "https://news.now.com" + raw
                link = raw

            # publishDate 多數係 epoch ms
            dt = None
            time_str = "—"
            raw_time = it.get("publishDate") or it.get("publishTime") or it.get("publishedAt") or it.get("date")
            if raw_time is not None:
                try:
                    if isinstance(raw_time, (int, float)) or str(raw_time).isdigit():
                        ts = int(raw_time)
                        # 如果係毫秒
                        if ts > 10_000_000_000:
                            ts = ts // 1000
                        dt = datetime.datetime.fromtimestamp(ts, tz=HK_TZ)
                    else:
                        dt = dtparser.parse(str(raw_time))
                        if dt.tzinfo is None:
                            dt = HK_TZ.localize(dt)
                        dt = dt.astimezone(HK_TZ)
                    time_str = dt.strftime("%H:%M") if dt else "—"
                except Exception:
                    dt = None
                    time_str = "—"

            if title and link:
                out.append(Article(title=title, link=link, dt=dt, time_str=time_str, color=color))
            if len(out) >= limit:
                break

        if not out:
            return [], "Now API 有回傳但未能抽取到有效新聞項目"
        return out, None

    except requests.HTTPError as e:
        return [], f"HTTPError: {e}"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"

# =====================
# Render（關鍵：避免縮排變成黑色 code block）
# =====================
def build_card_html(title: str, articles: List[Article], warn: Optional[str] = None) -> str:
    if not articles:
        items_html = "<div class='empty'>暫無內容</div>"
    else:
        parts = []
        for a in articles:
            new_class = " new" if a.is_new else ""
            parts.append(
                f"""<div class="item{new_class}" style="border-left-color:{a.color}">
<a href="{a.link}" target="_blank" rel="noopener noreferrer">{html.escape(a.title)}</a>
<div class="item-meta">🕐 {html.escape(a.time_str)}</div>
</div>"""
            )
        items_html = "".join(parts)

    warn_html = f"<div class='warn'>⚠️ {html.escape(warn)}</div>" if warn else ""

    # 重要：dedent + strip，避免 Markdown 誤判為 code block
    return dedent(
        f"""
        <div class="section-title">{html.escape(title)}</div>
        <div class="card">
          <div class="items">
            {items_html}
          </div>
          {warn_html}
        </div>
        """
    ).strip()

def sort_articles_desc(articles: List[Article]) -> List[Article]:
    # 有 dt 的排前面；冇 dt 的保持相對順序（靠原 feed 最新）
    with_dt = [a for a in articles if a.dt is not None]
    without_dt = [a for a in articles if a.dt is None]
    with_dt.sort(key=lambda x: x.dt, reverse=True)
    return with_dt + without_dt

# =====================
# URLs（你可自由加減；Now 用 API 特別處理）
# =====================
GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"

# =====================
# UI
# =====================
st.title("🗞️ Tommy Sir後援會之新聞中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

# RSSHub base（你話唔知 template name；呢度直接用 URL）
rsshub_base = st.sidebar.text_input(
    "RSSHub Base URL（例如 https://rsshub-production-xxxx.up.railway.app）",
    value="https://rsshub-production-9dfc.up.railway.app",
).rstrip("/")

auto = st.toggle("每分鐘自動更新", value=True)
if auto:
    st_autorefresh(interval=60_000, key="auto")

limit = st.sidebar.slider("每個來源顯示幾多條", 5, 30, 12, 1)

# 你指定的媒體（可再加）
sources = [
    {"name": "政府新聞（中文）", "type": "rss", "url": GOV_ZH, "color": "#E74C3C"},
    {"name": "政府新聞（英文）", "type": "rss", "url": GOV_EN, "color": "#C0392B"},
    {"name": "RTHK", "type": "rss", "url": RTHK, "color": "#FF9800"},

    # Now：特別處理（唔用 RSSHub，避免壞路由）
    {"name": "Now 新聞（本地）", "type": "now_api", "url": "", "color": "#16A34A"},

    # 你提供的 RSSHub routes（注意：Now RSSHub 你話壞咗，所以唔用）
    {"name": "HK01", "type": "rss", "url": f"{rsshub_base}/hk01/latest", "color": "#2563EB"},
    {"name": "on.cc 東網", "type": "rss", "url": f"{rsshub_base}/oncc/zh-hant/news", "color": "#7C3AED"},
    {"name": "星島即時", "type": "rss", "url": f"https://www.stheadline.com/rss", "color": "#F97316"},
    {"name": "明報即時", "type": "rss", "url": f"https://news.mingpao.com/rss/ins/all.xml", "color": "#7C3AED"},
    {"name": "i-CABLE 有線", "type": "rss", "url": f"{https://www.i-cable.com/feed", "color": "#A855F7"},
    {"name": "經濟日報", "type": "rss", "url": f"https://www.hket.com/rss/hongkong", "color": "#7C3AED"},
    {"name": "信報即時", "type": "rss", "url": f"{rsshub_base}/hkej/index", "color": "#64748B"},
    {"name": "巴士的報", "type": "rss", "url": f"https://www.bastillepost.com/hongkong/feed", "color": "#7C3AED"},
    {"name": "TVB 新聞", "type": "rss", "url": f"{rsshub_base}/tvb/news/tc", "color": "#0EA5E9"},



]

# 你可以日後再加（明報官方 RSS 你話「官方 RSS」，你未提供 URL，之後補上即可）

# Render：每行 4 欄（保持橫向並列）
cols_per_row = 4
rows = chunked(sources, cols_per_row)

for row in rows:
    cols = st.columns(len(row))
    for col, src in zip(cols, row):
        with col:
            if src["type"] == "now_api":
                arts, warn = fetch_now_api(src["color"], limit=limit)
            else:
                arts, warn = fetch_rss(src["url"], src["color"], limit=limit)

            # 新聞標紅（20 分鐘）
            mark_new_by_first_seen(arts, window_minutes=20)

            # 每個平台內部按時間新到舊
            arts = sort_articles_desc(arts)

            st.markdown(build_card_html(src["name"], arts, warn=warn), unsafe_allow_html=True)



