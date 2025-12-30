# app.py
# -*- coding: utf-8 -*-

import datetime
import hashlib
import html
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from textwrap import dedent

import feedparser
import pytz
import requests
import streamlit as st
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from streamlit_autorefresh import st_autorefresh
import streamlit.components.v1 as components

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
# CSS（NEW 徽章；NEW 出現時不再紅色；hover 取消 NEW）
# =====================
st.markdown(
    dedent(
        """
        <style>
        body { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

        .section-title{ font-size:1.05rem;font-weight:800;margin:2px 0 8px 0; }

        .card{
          background:#fff;border:1px solid #e5e7eb;border-radius:12px;
          padding:12px;height:520px;display:flex;flex-direction:column;
        }

        .items{ overflow-y:auto; padding-right:6px; flex:1; }

        .item{
          background:#fff;border-left:4px solid #3b82f6;border-radius:10px;
          padding:8px 10px;margin:8px 0;
        }

        /* NEW：不紅邊，只顯示 NEW 徽章 */
        .badge-new{
          display:inline-block;
          font-size:0.70rem;
          font-weight:800;
          padding:2px 7px;
          border-radius:999px;
          border:1px solid #ef4444;
          color:#b91c1c;
          background:rgba(239,68,68,0.08);
        }

        .row{
          display:flex;gap:10px;align-items:flex-start;
        }
        .leftbox{
          width:22px;flex:0 0 22px;padding-top:2px;
        }
        .contentbox{
          flex:1;
        }

        .title a{
          text-decoration:none;color:#111827;font-weight:700;line-height:1.35;
        }
        .title a:hover{ color:#111827; } /* hover 唔改色（你話 cursor 經過英文就取消 NEW） */

        .meta{
          font-size:0.78rem;color:#6b7280;font-family:monospace;margin-top:2px;
          display:flex;gap:8px;align-items:center;flex-wrap:wrap;
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
    source: str
    title: str
    link: str
    dt: Optional[datetime.datetime]  # HK time
    time_str: str
    content: str
    color: str
    is_new_badge: bool = False  # 顯示 NEW 徽章與否（hover 可取消）

# =====================
# Helpers
# =====================
def now_hk() -> datetime.datetime:
    return datetime.datetime.now(HK_TZ)

def clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = " ".join(text.split())
    return text

def stable_id(s: str) -> str:
    return hashlib.md5((s or "").encode("utf-8", errors="ignore")).hexdigest()[:12]

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
    return [lst[i:i + n] for i in range(0, len(lst), n)]

def ensure_stores():
    if "seen_links" not in st.session_state:
        st.session_state["seen_links"] = {}  # link -> first_seen_iso
    if "dismiss_new" not in st.session_state:
        st.session_state["dismiss_new"] = set()  # dismissed links
    if "selected" not in st.session_state:
        st.session_state["selected"] = {}  # article_key -> bool

def apply_new_badge_today(articles: List[Article]) -> None:
    """
    NEW 規則：同一日首次見到，且未被 hover dismiss。
    """
    ensure_stores()
    seen: Dict[str, str] = st.session_state["seen_links"]
    dismiss: set = st.session_state["dismiss_new"]
    now = now_hk()
    today = now.date()

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
            a.is_new_badge = (first_seen.date() == today) and (a.link not in dismiss)
        except Exception:
            a.is_new_badge = False

    st.session_state["seen_links"] = seen

def sort_articles_desc(articles: List[Article]) -> List[Article]:
    with_dt = [a for a in articles if a.dt is not None]
    without_dt = [a for a in articles if a.dt is None]
    with_dt.sort(key=lambda x: x.dt, reverse=True)
    return with_dt + without_dt

# =====================
# Requests / Fetchers
# =====================
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.7",
    "Connection": "keep-alive",
}

def _safe_get(url: str, params: Optional[dict] = None, timeout: int = 15, retries: int = 2) -> requests.Response:
    last_err = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=DEFAULT_HEADERS)
            r.raise_for_status()
            return r
        except Exception as e:
            last_err = e
            try:
                import time
                time.sleep(0.8 * (i + 1))
            except Exception:
                pass
    raise last_err

@st.cache_data(ttl=60)
def fetch_rss(source_name: str, url: str, color: str, limit: int = 12) -> Tuple[List[Article], Optional[str]]:
    try:
        r = _safe_get(url, timeout=15, retries=1)
        feed = feedparser.parse(r.content)

        if not feed.entries:
            return [], "未有 entries（可能來源暫時無更新／或路由變更）"

        out: List[Article] = []
        for e in feed.entries[: (limit * 4)]:
            title = clean_text(str(getattr(e, "title", "") or ""))
            link = str(getattr(e, "link", "") or "").strip()

            summary = ""
            for key in ("summary", "description"):
                v = getattr(e, key, None)
                if v:
                    summary = clean_text(str(v))
                    break

            if not title or not link:
                continue

            dt = parse_time_from_entry(e)
            time_str = dt.strftime("%H:%M") if dt else "—"

            out.append(
                Article(
                    source=source_name,
                    title=title,
                    link=link,
                    dt=dt,
                    time_str=time_str,
                    content=summary,
                    color=color,
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
    endpoints = [
        "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2",
        "https://newsapi.now.com/pccw-news-api/api/getNewsListv2",
    ]
    params = {"category": 119, "pageNo": 1}
    last_warn = None

    for base in endpoints:
        try:
            r = _safe_get(base, params=params, timeout=15, retries=2)
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

            if not candidates:
                last_warn = "Now API 回傳結構已變（找不到新聞列表）"
                continue

            out: List[Article] = []
            for it in candidates:
                if not isinstance(it, dict):
                    continue

                title = clean_text(str(it.get("title") or it.get("newsTitle") or it.get("headline") or ""))
                if not title:
                    continue

                news_id = str(it.get("newsId") or "").strip()
                link = f"https://news.now.com/home/local/player?newsId={news_id}" if news_id else ""

                # content：Now 有時提供 body/brief/summary 等
                content = ""
                for k in ("content", "body", "brief", "summary", "newsContent", "newsBrief"):
                    if it.get(k):
                        content = clean_text(str(it.get(k)))
                        break

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
                        dt = None
                        time_str = "—"

                if title and link:
                    out.append(
                        Article(
                            source=source_name,
                            title=title,
                            link=link,
                            dt=dt,
                            time_str=time_str,
                            content=content,
                            color=color,
                        )
                    )
                if len(out) >= limit:
                    break

            if not out:
                return [], "Now API 有回傳但未能抽取到有效新聞項目"
            return out, None

        except Exception as e:
            last_warn = f"{type(e).__name__}: {e}"
            continue

    return [], f"Now API 讀取失敗：{last_warn or 'unknown error'}"

# =====================
# Render HTML（每條新聞加 checkbox + hover 取消 NEW）
# =====================
def article_key(a: Article) -> str:
    return f"{a.source}::{stable_id(a.link)}"

def build_card_html(source_title: str, articles: List[Article], warn: Optional[str] = None) -> str:
    if not articles:
        items_html = "<div class='empty'>暫無內容</div>"
    else:
        parts = []
        dismiss_url = "/?dismiss="  # 用 query param 觸發 dismiss

        for a in articles:
            key = article_key(a)
            # hover 取消 NEW：onmouseenter -> 改網址 query param
            on_enter = ""
            badge = ""
            if a.is_new_badge:
                badge = '<span class="badge-new">NEW</span>'
                # cursor 經過英文就取消 NEW（只對 link）
                on_enter = f"""onmouseenter="try{{window.location.href='{dismiss_url}{html.escape(a.link)}';}}catch(e){{}}"
                """

            parts.append(
                f"""
                <div class="item" style="border-left-color:{a.color}">
                  <div class="row">
                    <div class="leftbox">
                      <!-- checkbox 由 Streamlit 控制，HTML 內只留位置（避免你版面變形） -->
                      <div id="cb-{html.escape(key)}"></div>
                    </div>
                    <div class="contentbox">
                      <div class="title">
                        <a href="{a.link}" target="_blank" rel="noopener noreferrer" {on_enter}>
                          {html.escape(a.title)}
                        </a>
                      </div>
                      <div class="meta">🕐 {html.escape(a.time_str)} {badge}</div>
                    </div>
                  </div>
                </div>
                """
            )
        items_html = "".join(parts)

    warn_html = f"<div class='warn'>⚠️ {html.escape(warn)}</div>" if warn else ""

    return dedent(
        f"""
        <div class="section-title">{html.escape(source_title)}</div>
        <div class="card">
          <div class="items">
            {items_html}
          </div>
          {warn_html}
        </div>
        """
    ).strip()

# =====================
# Dismiss NEW via query param
# =====================
def handle_dismiss_query():
    ensure_stores()
    q = st.query_params
    if "dismiss" in q:
        raw = q.get("dismiss")
        # streamlit query_params 可能返回 list/str
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        link = str(raw or "").strip()
        if link:
            st.session_state["dismiss_new"].add(link)
        # 清掉 query param，避免一直 refresh 都重複觸發
        st.query_params.clear()

# =====================
# Popup / Cir builder
# =====================
def format_cir(items: List[Article]) -> str:
    lines = []
    for a in items:
        pub = f"[{a.time_str}]" if a.time_str else "[—]"
        content = a.content.strip() if (a.content and a.content.strip()) else "（暫無內容摘要）"
        block = "\n".join([
            f"{a.source}：{a.title}",
            pub,
            "",
            content,
            "",
            a.link,
            "",
            "Ends",
        ])
        lines.append(block)
    return "\n\n".join(lines)

def copy_button(payload: str, button_label: str = "一鍵複製"):
    # 用 JS copy（瀏覽器允許才會成功）
    escaped = payload.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
    html_block = f"""
    <script>
    async function copyToClipboard(){{
      try {{
        await navigator.clipboard.writeText(`{escaped}`);
        const el = document.getElementById("copy-status");
        if(el) el.innerText = "已複製到剪貼簿";
      }} catch(e) {{
        const el = document.getElementById("copy-status");
        if(el) el.innerText = "複製失敗（瀏覽器限制）";
      }}
    }}
    </script>
    <button onclick="copyToClipboard()" style="
        padding:8px 12px;border-radius:10px;border:1px solid #d1d5db;
        background:white;font-weight:700;cursor:pointer;">
      {button_label}
    </button>
    <span id="copy-status" style="margin-left:10px;color:#6b7280;font-family:monospace;"></span>
    """
    components.html(html_block, height=55)

# =====================
# URLs
# =====================
GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"

# =====================
# UI
# =====================
handle_dismiss_query()

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

# Action panel（pin 左邊 = sidebar）
st.sidebar.markdown("## Action Panel")
if st.sidebar.button("一鍵取消所有選擇", use_container_width=True):
    st.session_state["selected"] = {}

# sources（保持你現有設定）
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
    {"name": "TVB 新聞", "type": "rss", "url": f"{rsshub_base}/tvb/news/tc", "color": "#0EA5E9"},
]

# Render：每行 4 欄
ensure_stores()
cols_per_row = 4
rows = chunked(sources, cols_per_row)

# 用來收集全部 article 以便 action panel 做 Cir
all_articles: Dict[str, Article] = {}

for row in rows:
    cols = st.columns(len(row))
    for col, src in zip(cols, row):
        with col:
            if src["type"] == "now_api":
                arts, warn = fetch_now_api(src["name"], src["color"], limit=limit)
            else:
                arts, warn = fetch_rss(src["name"], src["url"], src["color"], limit=limit)

            # NEW 只顯示徽章；不再紅色
            apply_new_badge_today(arts)

            # 每個平台內部按時間新到舊
            arts = sort_articles_desc(arts)

            # 記錄到全局
            for a in arts:
                all_articles[article_key(a)] = a

            # 先 render card HTML（佔位）
            st.markdown(build_card_html(src["name"], arts, warn=warn), unsafe_allow_html=True)

            # 再用 Streamlit 原生 checkbox 對齊塞回去（每條一個）
            # 注意：Streamlit 無法直接嵌入到特定 div id；所以用同一欄位順序在卡片下方對齊顯示 checkbox
            # 為了保持你視覺排版一致：checkbox 放在每條 item 前面（以兩欄 layout 模擬）
            # ——做法：在 card 下方建立一個不可見占位會破壞排版；因此改成：直接在 item 區域內用兩欄排列（原生）
            # Streamlit 無法把 checkbox 放入 raw HTML item 內，所以採用：在卡片內改由 Streamlit 渲染列表（下一版可做）
            # 今版：checkbox 仍然提供，但在卡片下方「對應順序」提供選取（不改你 HTML 排版結構）
            with st.expander(f"選擇 {src['name']}（勾選要 Cir）", expanded=False):
                for a in arts:
                    k = article_key(a)
                    st.session_state["selected"].setdefault(k, False)
                    st.session_state["selected"][k] = st.checkbox(
                        f"{a.time_str}  {a.title}",
                        value=st.session_state["selected"][k],
                        key=f"cb::{k}",
                    )

# Sidebar：Cir 按鈕 + popup
selected_keys = [k for k, v in st.session_state["selected"].items() if v and k in all_articles]
selected_articles = [all_articles[k] for k in selected_keys]

st.sidebar.markdown("---")
st.sidebar.markdown(f"已選擇：**{len(selected_articles)}** 條")

if st.sidebar.button("要Cir嘅新聞", use_container_width=True, disabled=(len(selected_articles) == 0)):
    st.session_state["show_cir"] = True

if st.session_state.get("show_cir"):
    cir_text = format_cir(selected_articles)
    with st.modal("要Cir嘅新聞（可複製）"):
        st.write("以下內容已按你指定格式生成：")
        st.code(cir_text, language="text")
        copy_button(cir_text, "一鍵複製")
        st.markdown("---")
        if st.button("關閉"):
            st.session_state["show_cir"] = False
