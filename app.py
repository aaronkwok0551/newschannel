# app.py
# -*- coding: utf-8 -*-

import datetime
import sys
import html as pyhtml
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import feedparser
import pytz
import requests
import streamlit as st
import streamlit.components.v1 as components
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
# CSS（New badge，hover 永久取消 New 由 JS 加 .seen）
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

        .news-row{
          border-left:4px solid #3b82f6;border-radius:10px;
          padding:10px 10px;margin:8px 0;background:#fff;
        }
        .news-row:hover{ background:#fafafa; }

        .row-top{ display:flex;align-items:center;gap:8px; }

        .new-badge{
          display:inline-block;
          font-size:0.72rem;
          padding:2px 8px;
          border-radius:999px;
          border:1px solid #fca5a5;
          color:#b91c1c;
          background:#fff1f2;
          font-weight:800;
          line-height:1.1;
          user-select:none;
          white-space:nowrap;
        }
        .news-row.seen .new-badge{ display:none; }

        .title-link{
          text-decoration:none;color:#111827;font-weight:650;line-height:1.35;
        }
        .title-link:hover{ color:#111827; text-decoration:underline; }

        .item-meta{
          font-size:0.78rem;color:#6b7280;font-family:monospace;margin-top:4px;
        }

        .empty{ color:#9ca3af;text-align:center;margin-top:20px; }
        .warn{ color:#b45309;font-size:0.85rem;margin:6px 0 0 0; }

        .cir-box{
          border:1px solid #e5e7eb;border-radius:12px;padding:12px;background:#fff;
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

# =====================
# Data model
# =====================
@dataclass
class Article:
    source: str
    key: str
    title: str
    link: str
    dt: Optional[datetime.datetime]
    time_str: str
    color: str
    content: str = ""
    is_new: bool = False


# =====================
# Helpers
# =====================
def now_hk() -> datetime.datetime:
    return datetime.datetime.now(HK_TZ)

def safe_key(s: str) -> str:
    out = []
    for ch in (s or ""):
        if ch.isalnum() or ch in ("-", "_", ":", ".", "/"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)[:220]

def clean_text(raw: str) -> str:
    raw = pyhtml.unescape(raw or "")
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
    return [lst[i:i + n] for i in range(0, len(lst), n)]

def sort_articles_desc(articles: List[Article]) -> List[Article]:
    with_dt = [a for a in articles if a.dt is not None]
    without_dt = [a for a in articles if a.dt is None]
    with_dt.sort(key=lambda x: x.dt, reverse=True)
    return with_dt + without_dt

def mark_new_by_first_seen(articles: List[Article], window_minutes: int = 20) -> None:
    if "seen_links_first" not in st.session_state:
        st.session_state["seen_links_first"] = {}  # link -> first_seen_iso

    seen: Dict[str, str] = st.session_state["seen_links_first"]
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

    st.session_state["seen_links_first"] = seen

def clear_all_selections():
    # 清掉 selected
    st.session_state["selected"] = {}
    # 清掉所有 checkbox key
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("cb::"):
            del st.session_state[k]


# =====================
# JS：hover 一次永久取消 New（localStorage），支援 reset nonce 清除
# （放 sidebar，用完全隱形 iframe，避免白框）
# =====================
def inject_new_hover_js(reset_nonce: str):
    components.html(
        f"""
        <html>
        <head>
          <style>
            html, body {{
              margin:0; padding:0; width:0; height:0; overflow:hidden; background:transparent;
            }}
          </style>
        </head>
        <body>
        <script>
        (function(){{
          const KEY = "seenNewKeys";
          const RESET_NONCE = "{pyhtml.escape(reset_nonce)}";

          function loadSeen(){{
            try {{ return JSON.parse(localStorage.getItem(KEY) || "{{}}"); }}
            catch(e){{ return {{}}; }}
          }}
          function saveSeen(obj){{
            try {{ localStorage.setItem(KEY, JSON.stringify(obj)); }} catch(e){{}}
          }}

          // reset：nonce 變化就清除
          try {{
            const last = localStorage.getItem("__NEW_RESET_NONCE__") || "";
            if (RESET_NONCE && RESET_NONCE !== last) {{
              localStorage.removeItem(KEY);
              localStorage.setItem("__NEW_RESET_NONCE__", RESET_NONCE);
            }}
          }} catch(e){{}}

          const seen = loadSeen();

          function applySeen(){{
            const rows = window.parent.document.querySelectorAll(".news-row[data-k]");
            rows.forEach(el=>{{
              const k = el.getAttribute("data-k");
              if(seen[k]) el.classList.add("seen");
            }});
          }}

          if(!window.parent.__NEW_HOVER_BOUND__){{
            window.parent.__NEW_HOVER_BOUND__ = true;
            window.parent.document.addEventListener("mouseover", function(ev){{
              const el = ev.target.closest && ev.target.closest(".news-row[data-k]");
              if(!el) return;
              const k = el.getAttribute("data-k");
              if(!k) return;

              if(!seen[k]) {{
                seen[k] = 1;
                saveSeen(seen);
              }}
              el.classList.add("seen");
            }}, true);
          }}

          setTimeout(applySeen, 50);
        }})();
        </script>
        </body>
        </html>
        """,
        height=0,
    )


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
            return [], "未有 entries（可能來源暫時無更新／或路由變更）"

        out: List[Article] = []
        for e in feed.entries[: (limit * 3)]:
            title = clean_text(getattr(e, "title", "") or "")
            link = getattr(e, "link", "") or ""
            if not title or not link:
                continue

            dt = parse_time_from_entry(e)
            time_str = dt.strftime("%H:%M") if dt else "—"

            # RSS 內文：summary / content
            summary = ""
            if getattr(e, "summary", None):
                summary = clean_text(getattr(e, "summary", "") or "")
            elif getattr(e, "content", None):
                try:
                    c0 = e.content[0].get("value", "")
                    summary = clean_text(c0)
                except Exception:
                    summary = ""

            key = safe_key(f"{source_name}::{link}")
            out.append(
                Article(
                    source=source_name,
                    key=key,
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

        if not candidates:
            return [], "Now API 回傳結構已變（找不到新聞列表）"

        out: List[Article] = []
        for it in candidates:
            if not isinstance(it, dict):
                continue

            title = clean_text(str(it.get("title") or it.get("newsTitle") or it.get("headline") or ""))
            news_id = str(it.get("newsId") or "").strip()

            link = f"https://news.now.com/home/local/player?newsId={news_id}" if news_id else ""
            if not title or not link:
                continue

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

            key = safe_key(f"{source_name}::{link}")
            out.append(
                Article(
                    source=source_name,
                    key=key,
                    title=title,
                    link=link,
                    dt=dt,
                    time_str=time_str,
                    color=color,
                    content="",   # Now list 無 summary
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

@st.cache_data(ttl=300)
def fetch_article_body(url: str) -> str:
    """抽文章內文（簡單 heuristic）；抽不到就回空字串"""
    if not url:
        return ""
    try:
        r = requests.get(url, timeout=15, headers=DEFAULT_HEADERS)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        # meta description（可作 fallback）
        desc = ""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            desc = clean_text(meta.get("content", ""))

        ps = [clean_text(p.get_text(" ", strip=True)) for p in soup.find_all("p")]
        ps = [t for t in ps if t and len(t) >= 15]

        body = "\n\n".join(ps[:12]).strip() if ps else ""
        if desc and (not body or len(desc) > len(body) * 0.6):
            body = desc if not body else (desc + "\n\n" + body)

        if len(body) > 2400:
            body = body[:2400].rstrip() + "…"
        return body.strip()
    except Exception:
        return ""

def build_cir_text(selected: List[Article]) -> str:
    blocks = []
    for a in selected:
        body = (a.content or "").strip()
        if not body:
            body = fetch_article_body(a.link).strip()
        if not body:
            body = "（未能自動抽取內文；可直接開連結查看）"

        blocks.append(
            "\n".join(
                [
                    f"{a.source}：{a.title}",
                    f"[{a.time_str}]",
                    "",
                    body,
                    "",
                    a.link,
                    "",
                    "Ends",
                ]
            )
        )
    return ("\n\n".join(blocks)).strip()

def copy_button_html(text: str):
    safe = pyhtml.escape(text).replace("\n", "\\n")
    components.html(
        f"""
        <html>
        <head>
          <style>
            html, body {{ margin:0; padding:0; background:transparent; }}
            button {{
              padding:8px 12px;border-radius:10px;border:1px solid #d1d5db;
              background:#111827;color:#fff;font-weight:800;cursor:pointer;
            }}
            span {{ font-family:monospace;color:#6b7280;margin-left:8px; }}
          </style>
        </head>
        <body>
          <button id="copyBtn">一鍵複製</button>
          <span id="copyMsg"></span>
          <script>
            (function(){{
              const btn = document.getElementById("copyBtn");
              const msg = document.getElementById("copyMsg");
              btn.onclick = async function(){{
                try {{
                  await navigator.clipboard.writeText("{safe}");
                  msg.textContent = "已複製";
                  setTimeout(()=>msg.textContent="", 1200);
                }} catch(e) {{
                  msg.textContent = "複製失敗（請手動全選複製）";
                }}
              }};
            }})();
          </script>
        </body>
        </html>
        """,
        height=44,
    )


# =====================
# Session state init
# =====================
if "selected" not in st.session_state:
    st.session_state["selected"] = {}
if "reset_new_nonce" not in st.session_state:
    st.session_state["reset_new_nonce"] = ""


# =====================
# UI Header
# =====================
st.title("🗞️ Tommy Sir後援會之新聞中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")


# =====================
# Sidebar Action Panel（固定左邊）
# =====================
MAX_PICK = 5

with st.sidebar:
    st.subheader("Action Panel")

    rsshub_base = st.text_input(
        "RSSHub Base URL（例如 https://rsshub-production-xxxx.up.railway.app）",
        value="https://rsshub-production-9dfc.up.railway.app",
    ).rstrip("/")

    auto = st.toggle("每分鐘自動更新", value=True)
    if auto:
        st_autorefresh(interval=60_000, key="auto")

    limit = st.slider("每個來源顯示幾多條", 5, 30, 12, 1)

    # 注入 hover-new JS（放 sidebar，避免白框）
    inject_new_hover_js(reset_nonce=st.session_state.get("reset_new_nonce", ""))

    # 清除紀錄（同時清伺服端 + 瀏覽器端）
    if st.button("清除 New 紀錄（全部）", use_container_width=True):
        # 伺服端：清 20 分鐘 first seen
        st.session_state["seen_links_first"] = {}
        # 瀏覽器端：透過 nonce 變化清 localStorage
        st.session_state["reset_new_nonce"] = now_hk().isoformat()
        st.rerun()

    # 一鍵取消選擇（真正 uncheck）
    if st.button("一鍵取消所有選擇", use_container_width=True):
        clear_all_selections()
        st.rerun()

    st.divider()
    sel_count = len(st.session_state.get("selected", {}))
    st.write(f"已選：**{sel_count}** / {MAX_PICK}")

    gen = st.button("要 Cir 嘅新聞（生成）", use_container_width=True, disabled=(sel_count == 0))


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


# =====================
# Checkbox callback（解決：要選兩次先計到）
# =====================
def on_checkbox_change(article_dict: dict):
    key = article_dict["key"]
    cb_key = f"cb::{key}"
    checked = bool(st.session_state.get(cb_key, False))

    sel: Dict[str, dict] = st.session_state.get("selected", {})

    if checked:
        # 上限控制
        if key not in sel and len(sel) >= MAX_PICK:
            st.session_state[cb_key] = False
            st.toast(f"最多只可選 {MAX_PICK} 條", icon="⚠️")
            return
        sel[key] = article_dict
    else:
        if key in sel:
            del sel[key]

    st.session_state["selected"] = sel


# =====================
# Render：每行 4 欄
# =====================
cols_per_row = 4
rows = chunked(sources, cols_per_row)

for row in rows:
    cols = st.columns(len(row))
    for col, src in zip(cols, row):
        with col:
            st.markdown(f"<div class='section-title'>{pyhtml.escape(src['name'])}</div>", unsafe_allow_html=True)
            st.markdown("<div class='card'><div class='items'>", unsafe_allow_html=True)

            if src["type"] == "now_api":
                arts, warn = fetch_now_api(src["name"], src["color"], limit=limit)
            else:
                arts, warn = fetch_rss(src["url"], src["name"], src["color"], limit=limit)

            mark_new_by_first_seen(arts, window_minutes=20)
            arts = sort_articles_desc(arts)

            if not arts:
                st.markdown("<div class='empty'>暫無內容</div>", unsafe_allow_html=True)
            else:
                for a in arts:
                    cb_key = f"cb::{a.key}"

                    # 初始值：以 selected 作準
                    selected_map: Dict[str, dict] = st.session_state.get("selected", {})
                    default_val = a.key in selected_map

                    # 容器（data-k 俾 hover-js 記住 seen）
                    st.markdown(
                        f'<div class="news-row" data-k="{pyhtml.escape(a.key)}" style="border-left-color:{a.color};">',
                        unsafe_allow_html=True,
                    )

                    c0, c1 = st.columns([0.12, 0.88], vertical_alignment="center")
                    with c0:
                        st.checkbox(
                            "",
                            key=cb_key,
                            value=default_val,
                            label_visibility="collapsed",
                            on_change=on_checkbox_change,
                            args=(a.__dict__,),
                        )
                    with c1:
                        top = '<div class="row-top">'
                        if a.is_new:
                            top += '<span class="new-badge">New</span>'
                        top += (
                            f'<a class="title-link" href="{pyhtml.escape(a.link)}" target="_blank" rel="noopener noreferrer">'
                            f"{pyhtml.escape(a.title)}</a>"
                        )
                        top += "</div>"
                        st.markdown(top, unsafe_allow_html=True)
                        st.markdown(f'<div class="item-meta">🕐 {pyhtml.escape(a.time_str)}</div>', unsafe_allow_html=True)

                    st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)
            if warn:
                st.markdown(f"<div class='warn'>⚠️ {pyhtml.escape(warn)}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)


# =====================
# 生成 Cir：用 st.dialog（冇就 fallback sidebar）
# =====================
def show_cir_dialog():
    sel_map: Dict[str, dict] = st.session_state.get("selected", {})
    selected_articles = [Article(**v) for v in sel_map.values()]
    selected_articles = sort_articles_desc(selected_articles)

    cir_text = build_cir_text(selected_articles)

    st.markdown("<div class='cir-box'>", unsafe_allow_html=True)
    st.write("以下為「要 Cir 嘅新聞」格式（可一鍵複製）：")
    st.text_area("Cir 內容", value=cir_text, height=360, label_visibility="collapsed")
    copy_button_html(cir_text)
    st.markdown("</div>", unsafe_allow_html=True)

if gen:
    if hasattr(st, "dialog"):
        @st.dialog("要 Cir 嘅新聞（可複製）")
        def _dlg():
            show_cir_dialog()
        _dlg()
    else:
        with st.sidebar:
            st.warning("你目前的 Streamlit 不支援彈窗（st.dialog）。已改為在左邊顯示。")
            show_cir_dialog()
