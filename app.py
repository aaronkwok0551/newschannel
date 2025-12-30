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

MAX_SELECTED = 5

# =====================
# CSS（不再用 HTML 卡片包 widgets，避免白色方格）
# =====================
st.markdown(
    dedent(
        """
        <style>
        body { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

        .news-title a{
          text-decoration:none;
          color:#111827;
          font-weight:800;
          line-height:1.35;
        }
        .news-title a:hover{ color:#111827; }

        .meta{
          font-size:0.78rem;
          color:#6b7280;
          font-family:monospace;
          margin-top:2px;
        }

        .new-badge{
          display:inline-block;
          font-size:0.70rem;
          font-weight:800;
          padding:2px 8px;
          border-radius:999px;
          background:#111827;
          color:white;
          margin-left:8px;
          vertical-align:middle;
        }
        /* hover 時隱藏 New */
        .news-row:hover .new-badge{ display:none; }

        .copybtn{
          padding:8px 12px;
          border-radius:10px;
          border:1px solid #cbd5e1;
          background:white;
          font-weight:800;
          cursor:pointer;
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
    source: str
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

def chunked(lst: List, n: int) -> List[List]:
    return [lst[i : i + n] for i in range(0, len(lst), n)]

def sort_articles_desc(articles: List[Article]) -> List[Article]:
    with_dt = [a for a in articles if a.dt is not None]
    without_dt = [a for a in articles if a.dt is None]
    with_dt.sort(key=lambda x: x.dt, reverse=True)
    return with_dt + without_dt

def mark_new_by_first_seen(articles: List[Article], window_minutes: int = 20) -> None:
    if "seen_links" not in st.session_state:
        st.session_state["seen_links"] = {}
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

def make_item_key(src: str, link: str) -> str:
    # key 必須穩定且唯一
    return f"{src}||{link}"

def ensure_state():
    if "selected" not in st.session_state:
        st.session_state["selected"] = {}  # item_key -> payload

def clear_all_selections():
    st.session_state["selected"] = {}
    # ✅ 強制將頁面上所有 cb:: key reset
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("cb::"):
            st.session_state[k] = False

def trim_selected_to_max():
    sel: Dict[str, dict] = st.session_state["selected"]
    if len(sel) <= MAX_SELECTED:
        return

    items = list(sel.values())
    with_dt = [x for x in items if x.get("dt") is not None]
    without_dt = [x for x in items if x.get("dt") is None]
    with_dt.sort(key=lambda x: x["dt"], reverse=True)
    keep = (with_dt + without_dt)[:MAX_SELECTED]

    keep_keys = set(x["item_key"] for x in keep)
    remove_keys = [k for k in list(sel.keys()) if k not in keep_keys]

    for item_key in remove_keys:
        cb_key = f"cb::{item_key}"
        if cb_key in st.session_state:
            st.session_state[cb_key] = False
        del sel[item_key]

def build_cir_text() -> str:
    items = list(st.session_state.get("selected", {}).values())
    if not items:
        return ""

    with_dt = [x for x in items if x.get("dt") is not None]
    without_dt = [x for x in items if x.get("dt") is None]
    with_dt.sort(key=lambda x: x["dt"], reverse=True)
    items_sorted = with_dt + without_dt

    lines: List[str] = []
    for it in items_sorted:
        lines.append(f"{it['source']}：{it['title']}")
        lines.append(f"[{it['time']}]")
        lines.append("")
        lines.append(it.get("content", "") or "")
        lines.append("")
        lines.append(it["url"])
        lines.append("")
        lines.append("Ends")
        lines.append("")
    return "\n".join(lines).strip()

def copy_button_html(text_to_copy: str, btn_label: str = "一鍵複製") -> str:
    escaped = html.escape(text_to_copy).replace("\n", "&#10;")
    return dedent(
        f"""
        <textarea id="__cir_textarea" style="position:absolute; left:-9999px; top:-9999px;">{escaped}</textarea>
        <button id="__copy_btn" class="copybtn">{html.escape(btn_label)}</button>
        <span id="__copy_msg" style="margin-left:10px;color:#16a34a;font-weight:800;"></span>
        <script>
          const btn = document.getElementById("__copy_btn");
          const ta = document.getElementById("__cir_textarea");
          const msg = document.getElementById("__copy_msg");
          btn.addEventListener("click", async () => {{
            try {{
              await navigator.clipboard.writeText(ta.value);
              msg.textContent = "已複製";
              setTimeout(()=>msg.textContent="", 1200);
            }} catch(e) {{
              ta.focus(); ta.select(); document.execCommand("copy");
              msg.textContent = "已複製";
              setTimeout(()=>msg.textContent="", 1200);
            }}
          }});
        </script>
        """
    ).strip()

# =====================
# Fetchers
# =====================
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Streamlit; HK News Aggregator)",
    "Accept": "*/*",
}

@st.cache_data(ttl=60)
def fetch_rss(source_name: str, url: str, color: str, limit: int = 12) -> Tuple[List[Article], Optional[str]]:
    try:
        r = requests.get(url, timeout=15, headers=DEFAULT_HEADERS)
        r.raise_for_status()

        feed = feedparser.parse(r.content)
        if not feed.entries:
            return [], "未有 entries（可能來源暫時無更新／或 RSSHub 路由變更）"

        out: List[Article] = []
        for e in feed.entries[: (limit * 3)]:
            title = clean_text(getattr(e, "title", "") or "")
            link = getattr(e, "link", "") or ""
            if not title or not link:
                continue

            dt = parse_time_from_entry(e)
            time_str = dt.strftime("%H:%M") if dt else "—"
            out.append(Article(source=source_name, title=title, link=link, dt=dt, time_str=time_str, color=color))
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
        for it in candidates:
            if not isinstance(it, dict):
                continue

            title = clean_text(str(it.get("title") or it.get("newsTitle") or it.get("headline") or ""))
            news_id = str(it.get("newsId") or "").strip()

            link = f"https://news.now.com/home/local/player?newsId={news_id}" if news_id else ""
            if not link:
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
                            ts //= 1000
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
                out.append(Article(source=source_name, title=title, link=link, dt=dt, time_str=time_str, color=color))
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
# UI: Sidebar（固定用 st.sidebar，確保狀態每次都刷新）
# =====================
ensure_state()

st.sidebar.subheader("Action Panel")

rsshub_base = st.sidebar.text_input(
    "RSSHub Base URL（例如 https://rsshub-production-xxxx.up.railway.app）",
    value="https://rsshub-production-9dfc.up.railway.app",
).rstrip("/")

auto = st.sidebar.toggle("每分鐘自動更新", value=True)
if auto:
    st_autorefresh(interval=60_000, key="auto")

limit = st.sidebar.slider("每個來源顯示幾多條", 5, 30, 12, 1)

st.sidebar.markdown("---")
st.sidebar.markdown(f"**已選：{len(st.session_state['selected'])}/{MAX_SELECTED}**")

if st.sidebar.button("一鍵取消所有選擇", use_container_width=True):
    clear_all_selections()
    st.rerun()

# 「要Cir」永遠在 Sidebar，唔用 popover（避免版本差異）
with st.sidebar.expander("要Cir嘅新聞（可複製）", expanded=True):
    cir_text = build_cir_text()
    if not cir_text:
        st.info("未選擇任何新聞。")
    else:
        st.text_area("Cir 內容", value=cir_text, height=360, label_visibility="collapsed")
        st.components.v1.html(copy_button_html(cir_text, "一鍵複製"), height=50)
        st.download_button(
            "下載為 txt",
            data=cir_text.encode("utf-8"),
            file_name="cir_news.txt",
            mime="text/plain",
            use_container_width=True,
        )

# =====================
# Main
# =====================
st.title("🗞️ Tommy Sir後援會之新聞中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"

sources = [
    {"name": "政府新聞（中文）", "type": "rss", "url": GOV_ZH, "color": "#E74C3C"},
    {"name": "政府新聞（英文）", "type": "rss", "url": GOV_EN, "color": "#C0392B"},
    {"name": "RTHK", "type": "rss", "url": RTHK, "color": "#FF9800"},
    {"name": "Now 新聞（本地）", "type": "now_api", "url": "", "color": "#16A34A"},
    {"name": "HK01", "type": "rss", "url": f"{rsshub_base}/hk01/latest", "color": "#2563EB"},
    {"name": "on.cc 東網", "type": "rss", "url": f"{rsshub_base}/oncc/zh-hant/news", "color": "#7C3AED"},
    {"name": "星島即時", "type": "rss", "url": "https://www.stheadline.com/rss", "color": "#F97316"},
    {"name": "明報即時", "type": "rss", "url": "https://news.mingpao.com/rss/ins/all.xml", "color": "#7C3AED"},
    {"name": "i-CABLE 有線", "type": "rss", "url": "https://www.i-cable.com/feed", "color": "#A855F7"},
    {"name": "經濟日報", "type": "rss", "url": "https://www.hket.com/rss/hongkong", "color": "#7C3AED"},
    {"name": "信報即時", "type": "rss", "url": f"{rsshub_base}/hkej/index", "color": "#64748B"},
    {"name": "巴士的報", "type": "rss", "url": "https://www.bastillepost.com/hongkong/feed", "color": "#7C3AED"},
]

cols_per_row = 4
rows = chunked(sources, cols_per_row)

for row in rows:
    cols = st.columns(len(row), gap="small")
    for col, src in zip(cols, row):
        with col:
            # ✅ 用 Streamlit 原生 container 做方格（唔會再出現白色空框）
            box = st.container(border=True)
            with box:
                st.markdown(f"**{src['name']}**")

                if src["type"] == "now_api":
                    arts, warn = fetch_now_api(src["name"], src["color"], limit=limit)
                else:
                    arts, warn = fetch_rss(src["name"], src["url"], src["color"], limit=limit)

                mark_new_by_first_seen(arts, window_minutes=20)
                arts = sort_articles_desc(arts)

                if not arts:
                    st.caption("暫無內容")
                else:
                    # 每條：checkbox + 標題
                    for a in arts:
                        item_key = make_item_key(a.source, a.link)
                        cb_key = f"cb::{item_key}"

                        # 初始化：依照 selected 反映 checkbox
                        if cb_key not in st.session_state:
                            st.session_state[cb_key] = (item_key in st.session_state["selected"])

                        checked_now = bool(st.session_state.get(cb_key, False))
                        disable_cb = (len(st.session_state["selected"]) >= MAX_SELECTED) and (not checked_now)

                        c1, c2 = st.columns([0.13, 0.87], gap="small")
                        with c1:
                            val = st.checkbox("", key=cb_key, disabled=disable_cb)

                        payload = {
                            "item_key": item_key,
                            "source": a.source,
                            "title": a.title,
                            "time": a.time_str,
                            "dt": a.dt,
                            "content": "",
                            "url": a.link,
                        }

                        # ✅ 即時同步（揀第一條就計）
                        sel = st.session_state["selected"]
                        if val:
                            if item_key not in sel:
                                if len(sel) >= MAX_SELECTED:
                                    st.session_state[cb_key] = False
                                    st.warning(f"最多只可揀 {MAX_SELECTED} 條")
                                    st.rerun()
                                sel[item_key] = payload
                        else:
                            if item_key in sel:
                                del sel[item_key]

                        with c2:
                            new_badge = "<span class='new-badge'>New</span>" if a.is_new else ""
                            st.markdown(
                                f"""
                                <div class="news-row" style="border-left:4px solid {a.color}; padding-left:10px; margin:6px 0;">
                                  <div class="news-title">
                                    <a href="{html.escape(a.link)}" target="_blank" rel="noopener noreferrer">
                                      {html.escape(a.title)}{new_badge}
                                    </a>
                                  </div>
                                  <div class="meta">🕐 {html.escape(a.time_str)}</div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                if warn:
                    st.warning(warn)

# 最後保險：如果因為舊狀態曾經 >5，剪返 5，並取消多餘 checkbox
trim_selected_to_max()
