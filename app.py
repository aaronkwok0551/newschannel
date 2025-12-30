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
# CSS
# =====================
st.markdown(
    dedent(
        """
        <style>
        body { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

        .section-title{ font-size:1.05rem;font-weight:800;margin:2px 0 8px 0; }

        .card{
          background:#fff;border:1px solid #e5e7eb;border-radius:12px;
          padding:10px 12px;height:560px;display:flex;flex-direction:column;
        }
        .items{ overflow-y:auto; padding-right:6px; flex:1; }

        .badge-new{
          display:inline-block;
          font-size:0.72rem;
          font-weight:800;
          padding:1px 8px;
          border-radius:999px;
          background:#111827;
          color:#fff;
          margin-left:6px;
        }

        .itemwrap{
          border-left:4px solid #3b82f6;border-radius:10px;
          padding:8px 10px;margin:10px 0;background:#fff;
        }
        .titleline a{ text-decoration:none;color:#111827;font-weight:650;line-height:1.35; }
        .titleline a:hover{ color:#2563eb; }
        .meta{ font-size:0.78rem;color:#6b7280;font-family:monospace;margin-top:2px; }

        .warn{ color:#b45309;font-size:0.85rem;margin:6px 0 0 0; }
        .empty{ color:#9ca3af;text-align:center;margin-top:20px; }

        .cirbox{
          border:1px solid #e5e7eb;border-radius:12px;
          padding:12px;background:#fff;
        }
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
    id: str
    source: str
    title: str
    link: str
    dt: Optional[datetime.datetime]
    time_str: str
    color: str
    is_new: bool = False
    content: str = ""

# =====================
# State helpers
# =====================
def now_hk() -> datetime.datetime:
    return datetime.datetime.now(HK_TZ)

def _ensure_state():
    st.session_state.setdefault("seen_first", {})      # link -> first seen iso
    st.session_state.setdefault("read_links", set())   # link set (cancel NEW)
    st.session_state.setdefault("selected", {})        # article_id -> bool
    st.session_state.setdefault("selected_order", [])  # preserve order
    st.session_state.setdefault("article_cache", {})   # article_id -> Article
    st.session_state.setdefault("show_cir_panel", False)

def mark_read(link: str):
    _ensure_state()
    if link:
        st.session_state["read_links"].add(link)

def compute_new_flag(link: str, window_minutes: int = 20) -> bool:
    _ensure_state()
    if not link:
        return False

    now = now_hk()
    seen_first: Dict[str, str] = st.session_state["seen_first"]
    read_links: set = st.session_state["read_links"]

    if link in read_links:
        return False

    if link not in seen_first:
        seen_first[link] = now.isoformat()

    try:
        first_seen = dtparser.parse(seen_first[link])
        if first_seen.tzinfo is None:
            first_seen = HK_TZ.localize(first_seen)
        first_seen = first_seen.astimezone(HK_TZ)
        return (now - first_seen) <= datetime.timedelta(minutes=window_minutes)
    except Exception:
        return False

def cache_articles(all_articles: List[Article]):
    _ensure_state()
    st.session_state["article_cache"] = {a.id: a for a in all_articles}

def get_selected_articles() -> List[Article]:
    _ensure_state()
    cache: Dict[str, Article] = st.session_state["article_cache"]
    selected: Dict[str, bool] = st.session_state["selected"]
    order: List[str] = st.session_state["selected_order"]

    out: List[Article] = []
    for aid in order:
        if selected.get(aid) and aid in cache:
            out.append(cache[aid])

    # 補漏
    for aid, v in selected.items():
        if v and aid in cache and aid not in order:
            out.append(cache[aid])

    return out

# =====================
# Text helpers
# =====================
def clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    return " ".join(text.split())

def parse_time_from_entry(entry) -> Optional[datetime.datetime]:
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

def sort_articles_desc(articles: List[Article]) -> List[Article]:
    with_dt = [a for a in articles if a.dt is not None]
    without_dt = [a for a in articles if a.dt is None]
    with_dt.sort(key=lambda x: x.dt, reverse=True)
    return with_dt + without_dt

def chunked(lst: List, n: int) -> List[List]:
    return [lst[i:i+n] for i in range(0, len(lst), n)]

def format_cir_text(articles: List[Article]) -> str:
    blocks = []
    for a in articles:
        pub = a.time_str or "—"
        body = (a.content or "").strip()
        if body:
            body = body[:1200]
        blocks.append(
            f"{a.source}：{a.title}\n[{pub}]\n\n{body}\n\n{a.link}\n\nEnds"
        )
    return "\n\n---\n\n".join(blocks)

# =====================
# Fetchers
# =====================
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Streamlit; HK News Aggregator)",
    "Accept": "*/*",
}

@st.cache_data(ttl=60)
def fetch_rss(url: str, source_name: str, color: str, limit: int = 12) -> Tuple[List[Article], Optional[str]]:
    try:
        r = requests.get(url, timeout=15, headers=DEFAULT_HEADERS)
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        if not feed.entries:
            return [], "未有 entries（可能來源暫時無更新／或 RSSHub 路由變更）"

        out: List[Article] = []
        i = 0
        for e in feed.entries[: (limit * 4)]:
            title = clean_text(getattr(e, "title", "") or "")
            link = getattr(e, "link", "") or ""
            if not title or not link:
                continue

            dt = parse_time_from_entry(e)
            time_str = dt.strftime("%H:%M") if dt else "—"
            summary = clean_text(getattr(e, "summary", "") or getattr(e, "description", "") or "")

            art_id = f"{source_name}-{i}-{abs(hash(link))}"
            i += 1
            out.append(
                Article(
                    id=art_id,
                    source=source_name,
                    title=title,
                    link=link,
                    dt=dt,
                    time_str=time_str,
                    color=color,
                    content=summary,
                )
            )
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
def fetch_now_api(source_name: str, color: str, limit: int = 12) -> Tuple[List[Article], Optional[str]]:
    NOW_URL = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2"
    params = {"category": 119, "pageNo": 1}

    try:
        r = requests.get(NOW_URL, params=params, timeout=15, headers=DEFAULT_HEADERS)
        r.raise_for_status()
        data = r.json()

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
        i = 0
        for it in candidates:
            if not isinstance(it, dict):
                continue

            title = clean_text(str(it.get("title") or it.get("newsTitle") or it.get("headline") or ""))
            news_id = str(it.get("newsId") or "").strip()
            if not title:
                continue

            if news_id:
                link = f"https://news.now.com/home/local/player?newsId={news_id}"
            else:
                raw = str(it.get("shareUrl") or it.get("url") or it.get("link") or "").strip()
                if raw.startswith("/"):
                    raw = "https://news.now.com" + raw
                link = raw

            dt = None
            time_str = "—"
            raw_time = it.get("publishDate") or it.get("publishTime") or it.get("publishedAt") or it.get("date")
            if raw_time is not None:
                try:
                    if isinstance(raw_time, (int, float)) or str(raw_time).isdigit():
                        ts = int(raw_time)
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
                    dt, time_str = None, "—"

            content = clean_text(str(it.get("content") or it.get("newsContent") or it.get("summary") or ""))

            art_id = f"{source_name}-{i}-{abs(hash(link))}"
            i += 1
            out.append(
                Article(
                    id=art_id,
                    source=source_name,
                    title=title,
                    link=link,
                    dt=dt,
                    time_str=time_str,
                    color=color,
                    content=content,
                )
            )
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
# Sidebar action panel（左邊固定）
# =====================
def sidebar_panel():
    _ensure_state()

    st.sidebar.title("Action Panel")
    st.sidebar.caption("選好新聞後按「要 Cir 嘅新聞」生成內容")

    # 一鍵清除：清 checkbox + 清已選
    if st.sidebar.button("一鍵取消所有選擇", use_container_width=True):
        for k in list(st.session_state.keys()):
            if str(k).startswith("cb__"):
                st.session_state[k] = False
        st.session_state["selected"] = {}
        st.session_state["selected_order"] = []
        st.session_state["show_cir_panel"] = False
        st.rerun()

    selected_items = get_selected_articles()
    st.sidebar.markdown(f"**已選：{len(selected_items)} 條**")

    if selected_items:
        for a in selected_items[:25]:
            st.sidebar.write(f"- {a.source}｜{a.time_str}｜{a.title[:25]}…")
        if len(selected_items) > 25:
            st.sidebar.caption(f"（仲有 {len(selected_items)-25} 條未顯示）")

    # 生成 Cir 面板（替代 popup）
    if st.sidebar.button("要 Cir 嘅新聞", use_container_width=True, disabled=(len(selected_items) == 0)):
        st.session_state["show_cir_panel"] = True

# =====================
# Cir panel（主畫面右上方出現）
# =====================
def render_cir_panel():
    _ensure_state()
    if not st.session_state.get("show_cir_panel"):
        return

    selected_items = get_selected_articles()
    cir_text = format_cir_text(selected_items)

    st.markdown("<div class='cirbox'>", unsafe_allow_html=True)
    colA, colB = st.columns([1, 1])
    with colA:
        st.subheader("要 Cir 嘅新聞（可複製）")
    with colB:
        if st.button("關閉 Cir 面板", use_container_width=True):
            st.session_state["show_cir_panel"] = False
            st.rerun()

    st.code(cir_text, language="text")

    # 一鍵複製（JS）
    st.markdown(
        f"""
        <button id="copyBtn" style="width:100%;padding:10px 12px;border-radius:10px;border:1px solid #e5e7eb;background:#111827;color:#fff;font-weight:700;">
          一鍵複製到剪貼簿
        </button>
        <textarea id="copyText" style="position:absolute;left:-9999px;top:-9999px;">{html.escape(cir_text)}</textarea>
        <script>
        const btn = document.getElementById("copyBtn");
        btn.addEventListener("click", async () => {{
            const t = document.getElementById("copyText").value;
            try {{
                await navigator.clipboard.writeText(t);
                btn.innerText = "已複製 ✅";
                setTimeout(()=>btn.innerText="一鍵複製到剪貼簿", 1500);
            }} catch(e) {{
                btn.innerText = "複製失敗（瀏覽器限制）";
                setTimeout(()=>btn.innerText="一鍵複製到剪貼簿", 1500);
            }}
        }});
        </script>
        """,
        unsafe_allow_html=True,
    )

    st.download_button(
        "下載成文字檔（備用）",
        data=cir_text.encode("utf-8"),
        file_name="cir_news.txt",
        mime="text/plain",
        use_container_width=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

# =====================
# Main UI
# =====================
_ensure_state()

st.title("🗞️ Tommy Sir後援會之新聞中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

rsshub_base = st.sidebar.text_input(
    "RSSHub Base URL（例如 https://rsshub-production-xxxx.up.railway.app）",
    value="https://rsshub-production-9dfc.up.railway.app",
).rstrip("/")

auto = st.toggle("每分鐘自動更新", value=True)
if auto:
    st_autorefresh(interval=60_000, key="auto")

limit = st.sidebar.slider("每個來源顯示幾多條", 5, 30, 12, 1)

# 左邊 action panel
sidebar_panel()

# 先渲染 Cir 面板（頂部）
render_cir_panel()

# =====================
# Sources
# =====================
GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"

sources = [
    {"name": "政府新聞（中文）", "type": "rss", "url": GOV_ZH, "color": "#E74C3C"},
    {"name": "政府新聞（英文）", "type": "rss", "url": GOV_EN, "color": "#C0392B"},
    {"name": "RTHK", "type": "rss", "url": RTHK, "color": "#FF9800"},
    {"name": "Now（本地）", "type": "now_api", "url": "", "color": "#2563EB"},

    {"name": "HK01", "type": "rss", "url": f"{rsshub_base}/hk01/latest", "color": "#06b6d4"},
    {"name": "on.cc 東網", "type": "rss", "url": f"{rsshub_base}/oncc/zh-hant/news", "color": "#7C3AED"},
    {"name": "星島（Feedly RSS）", "type": "rss", "url": "https://www.stheadline.com/rss", "color": "#F97316"},
    {"name": "明報即時", "type": "rss", "url": "https://news.mingpao.com/rss/ins/all.xml", "color": "#64748B"},

    {"name": "i-CABLE 有線", "type": "rss", "url": "https://www.i-cable.com/feed", "color": "#A855F7"},
    {"name": "經濟日報 HKET", "type": "rss", "url": "https://www.hket.com/rss/hongkong", "color": "#16A34A"},
    {"name": "信報", "type": "rss", "url": f"{rsshub_base}/hkej/index", "color": "#0EA5E9"},
    {"name": "巴士的報", "type": "rss", "url": "https://www.bastillepost.com/hongkong/feed", "color": "#f59e0b"},
]

# =====================
# Render cards（每行4個）
# =====================
cols_per_row = 4
rows = chunked(sources, cols_per_row)

all_articles_flat: List[Article] = []

for row in rows:
    cols = st.columns(len(row))
    for col, src in zip(cols, row):
        with col:
            # fetch
            if src["type"] == "now_api":
                arts, warn = fetch_now_api(src["name"], src["color"], limit=limit)
            else:
                arts, warn = fetch_rss(src["url"], src["name"], src["color"], limit=limit)

            # sort per source
            arts = sort_articles_desc(arts)

            st.markdown(f"<div class='section-title'>{html.escape(src['name'])}</div>", unsafe_allow_html=True)
            st.markdown("<div class='card'><div class='items'>", unsafe_allow_html=True)

            if not arts:
                st.markdown("<div class='empty'>暫無內容</div>", unsafe_allow_html=True)
            else:
                for idx, a in enumerate(arts):
                    a.is_new = compute_new_flag(a.link, window_minutes=20)

                    cb_key = f"cb__{a.id}"
                    if cb_key not in st.session_state:
                        st.session_state[cb_key] = False

                    # checkbox label
                    label = f"{a.time_str}  {a.title}"
                    checked = st.checkbox(label, value=st.session_state[cb_key], key=cb_key)

                    # update selection state
                    if checked:
                        st.session_state["selected"][a.id] = True
                        if a.id not in st.session_state["selected_order"]:
                            st.session_state["selected_order"].append(a.id)
                        mark_read(a.link)  # 勾選/互動即視為已讀，取消 NEW
                        a.is_new = False
                    else:
                        st.session_state["selected"][a.id] = False

                    # NEW badge（不再用紅色）
                    if a.is_new:
                        st.markdown("<span class='badge-new'>NEW</span>", unsafe_allow_html=True)

                    # clickable link
                    st.markdown(
                        f"""
                        <div class="itemwrap" style="border-left-color:{a.color}">
                          <div class="titleline">
                            <a href="{a.link}" target="_blank" rel="noopener noreferrer">{html.escape(a.title)}</a>
                          </div>
                          <div class="meta">🕐 {html.escape(a.time_str)}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    all_articles_flat.append(a)

            st.markdown("</div>", unsafe_allow_html=True)
            if warn:
                st.markdown(f"<div class='warn'>⚠️ {html.escape(warn)}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

cache_articles(all_articles_flat)
