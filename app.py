# app.py
# -*- coding: utf-8 -*-

import datetime
import html as pyhtml
import sys
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
# CSS（New 文字 + hover 永久取消 New（靠 JS 加 seen class））
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

        .row-top{
          display:flex;align-items:center;gap:8px;
        }
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
        }
        /* JS 會加 .seen → 永久隱藏 New */
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

        /* Cir 彈窗內容樣式 */
        .cir-box{
          border:1px solid #e5e7eb;border-radius:12px;padding:12px;background:#fff;
        }
        .cir-actions{ display:flex; gap:10px; margin:10px 0 0 0; }
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
    key: str  # 用於 checkbox / New 記錄
    title: str
    link: str
    dt: Optional[datetime.datetime]  # HK time
    time_str: str
    color: str
    content: str = ""               # 內文（RSS summary 或抽頁面）
    is_new: bool = False            # 20 分鐘內「第一次見到」


# =====================
# Helpers
# =====================
def now_hk() -> datetime.datetime:
    return datetime.datetime.now(HK_TZ)

def clean_text(raw: str) -> str:
    raw = pyhtml.unescape(raw or "")
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    return " ".join(text.split())

def safe_key(s: str) -> str:
    # 只做簡單 key 安全化（避免 JS / widget key 出事）
    out = []
    for ch in (s or ""):
        if ch.isalnum() or ch in ("-", "_", ":", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)[:200]

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

def mark_new_by_first_seen(articles: List[Article], window_minutes: int = 20) -> None:
    """
    用「第一次見到 link 的時間」判斷新新聞（20 分鐘內）
    """
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

def sort_articles_desc(articles: List[Article]) -> List[Article]:
    with_dt = [a for a in articles if a.dt is not None]
    without_dt = [a for a in articles if a.dt is None]
    with_dt.sort(key=lambda x: x.dt, reverse=True)
    return with_dt + without_dt

def clear_all_selections():
    st.session_state["selected"] = {}
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("cb::"):
            del st.session_state[k]

# =====================
# JS：hover 一次永久取消 New + 支援「清除 New 記錄」
# =====================
def inject_new_hover_js(reset_nonce: str = ""):
    """
    Streamlit 會阻止 <script> 在 st.markdown 執行，所以必須用 components.html
    reset_nonce：每次按「清除 New 記錄」就換一個 nonce 觸發清除 localStorage
    """
    components.html(
        f"""
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

          // reset：只要 nonce 變化就清除
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

          setTimeout(applySeen, 80);
        }})();
        </script>
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
        for idx, e in enumerate(feed.entries[: (limit * 3)]):
            title = clean_text(getattr(e, "title", "") or "")
            link = getattr(e, "link", "") or ""
            if not title or not link:
                continue

            dt = parse_time_from_entry(e)
            time_str = dt.strftime("%H:%M") if dt else "—"

            # 內文：優先 summary / content
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

            link = ""
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

            # Now list 通常無完整內文 → 留空（之後 Cir 時可 fallback 用 RSS summary/或你日後加 detail API）
            key = safe_key(f"{source_name}::{link}")
            if title and link:
                out.append(
                    Article(
                        source=source_name,
                        key=key,
                        title=title,
                        link=link,
                        dt=dt,
                        time_str=time_str,
                        color=color,
                        content="",
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
    """
    盡量從文章頁面抽內文（簡單 heuristic）
    - 不是所有媒體都一定抽到（可能有 JS / paywall / 防爬）
    - 抽不到就回傳空字串
    """
    if not url:
        return ""
    try:
        r = requests.get(url, timeout=15, headers=DEFAULT_HEADERS)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # 移除無用
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        # 優先 meta description
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            desc = clean_text(meta.get("content", ""))
        else:
            desc = ""

        # 收集 <p>
        ps = [clean_text(p.get_text(" ", strip=True)) for p in soup.find_all("p")]
        ps = [t for t in ps if t and len(t) >= 15]

        body = ""
        if ps:
            # 取較長的前幾段
            body = "\n\n".join(ps[:12])
        if desc and (not body or len(desc) > len(body) * 0.6):
            # desc 有時更乾淨
            body = desc if not body else (desc + "\n\n" + body)

        body = body.strip()
        # 避免太長
        if len(body) > 2400:
            body = body[:2400].rstrip() + "…"
        return body
    except Exception:
        return ""

# =====================
# Cir 內容生成 + 一鍵複製（JS）
# =====================
def build_cir_text(selected: List[Article]) -> str:
    blocks = []
    for a in selected:
        body = a.content.strip()
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
    return "\n\n" + ("\n\n".join(blocks)).strip()

def copy_button_html(text: str, btn_label: str = "一鍵複製"):
    # 用 components 注入 clipboard copy
    safe = pyhtml.escape(text).replace("\n", "\\n")
    components.html(
        f"""
        <div class="cir-actions">
          <button id="copyBtn"
            style="padding:8px 12px;border-radius:10px;border:1px solid #d1d5db;background:#111827;color:#fff;font-weight:700;cursor:pointer;">
            {pyhtml.escape(btn_label)}
          </button>
          <span id="copyMsg" style="font-family:monospace;color:#6b7280;"></span>
        </div>
        <script>
          (function(){{
            const btn = document.getElementById("copyBtn");
            const msg = document.getElementById("copyMsg");
            if(!btn) return;
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
        """,
        height=55,
    )

# =====================
# URLS
# =====================
GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"

# =====================
# Session State init
# =====================
if "selected" not in st.session_state:
    st.session_state["selected"] = {}  # key -> Article dict
if "reset_new_nonce" not in st.session_state:
    st.session_state["reset_new_nonce"] = ""

# =====================
# UI header
# =====================
st.title("🗞️ Tommy Sir後援會之新聞中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

# Sidebar / Action Panel（固定左邊）
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

    # 你要求：一鍵清除 New 記錄（localStorage）
    if st.button("清除 New 記錄（所有媒體）", use_container_width=True):
        st.session_state["reset_new_nonce"] = now_hk().isoformat()
        st.rerun()

    # 你要求：一鍵取消全部 checkbox（要真正 uncheck）
    if st.button("一鍵取消所有選擇", use_container_width=True):
        clear_all_selections()
        st.rerun()

    st.divider()
    sel_keys = list(st.session_state.get("selected", {}).keys())
    st.write(f"已選：**{len(sel_keys)}** / 5")

    # 生成 Cir（Popup / Dialog；沒有就 fallback 用 sidebar）
    can_generate = len(sel_keys) > 0
    gen = st.button("要 Cir 嘅新聞（生成）", use_container_width=True, disabled=not can_generate)

# 注入 hover New JS（含 reset nonce）
inject_new_hover_js(reset_nonce=st.session_state.get("reset_new_nonce", ""))

# =====================
# Sources（保持你原本；Now 特別 API）
# =====================
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
# Render cards：每行 4 個（保持方格內顯示）
# =====================
cols_per_row = 4
rows = chunked(sources, cols_per_row)

# 每次 rerun，先建立選擇上限（你之前提到 5 條）
MAX_PICK = 5

def upsert_selected(a: Article, checked: bool):
    sel: Dict[str, dict] = st.session_state.get("selected", {})
    if checked:
        # 限制最多 5 條
        if a.key not in sel and len(sel) >= MAX_PICK:
            # 超過就拒絕，並強制把 checkbox 拉回 False
            st.session_state[f"cb::{a.key}"] = False
            st.toast(f"最多只可選 {MAX_PICK} 條", icon="⚠️")
            return
        sel[a.key] = a.__dict__
    else:
        if a.key in sel:
            del sel[a.key]
    st.session_state["selected"] = sel

def render_article_row(a: Article):
    # checkbox + New + link + time，全在方格內
    row_key = f"cb::{a.key}"

    # 這個容器會有 data-k 俾 JS 記住「seen」
    st.markdown(
        f'<div class="news-row" data-k="{pyhtml.escape(a.key)}" style="border-left-color:{a.color};">',
        unsafe_allow_html=True,
    )

    c0, c1 = st.columns([0.12, 0.88], vertical_alignment="center")
    with c0:
        # 初始值：根據 selected
        sel = st.session_state.get("selected", {})
        if row_key not in st.session_state:
            st.session_state[row_key] = (a.key in sel)
        checked = st.checkbox("", key=row_key, label_visibility="collapsed")
    with c1:
        top = '<div class="row-top">'
        if a.is_new:
            top += '<span class="new-badge">New</span>'
        top += f'<a class="title-link" href="{pyhtml.escape(a.link)}" target="_blank" rel="noopener noreferrer">{pyhtml.escape(a.title)}</a>'
        top += "</div>"
        st.markdown(top, unsafe_allow_html=True)
        st.markdown(f'<div class="item-meta">🕐 {pyhtml.escape(a.time_str)}</div>', unsafe_allow_html=True)

    # 收尾 div
    st.markdown("</div>", unsafe_allow_html=True)

    # 同步選擇狀態
    upsert_selected(a, checked)

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

            # 20 分鐘 New（只顯示 New 字樣，不用紅色）
            mark_new_by_first_seen(arts, window_minutes=20)
            arts = sort_articles_desc(arts)

            if not arts:
                st.markdown("<div class='empty'>暫無內容</div>", unsafe_allow_html=True)
            else:
                # 右邊不自動縮減到 5 條：你上次提到想縮減
                # 這裡按你的要求：如果左邊已選滿 5 條，仍然顯示，但 checkbox 會限制不再新增
                for a in arts:
                    render_article_row(a)

            st.markdown("</div>", unsafe_allow_html=True)
            if warn:
                st.markdown(f"<div class='warn'>⚠️ {pyhtml.escape(warn)}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

# =====================
# Popup / Dialog（生成 Cir 文本 + 一鍵複製）
# 注意：你 Railway 的 streamlit 沒有 st.modal，所以用 st.dialog（有則用，冇則 fallback）
# =====================
def show_cir_dialog():
    sel_map: Dict[str, dict] = st.session_state.get("selected", {})
    selected_articles = [Article(**v) for v in sel_map.values()]
    # 按時間（有 dt 用 dt，冇就保持）
    selected_articles = sort_articles_desc(selected_articles)

    cir_text = build_cir_text(selected_articles)

    st.markdown("<div class='cir-box'>", unsafe_allow_html=True)
    st.write("以下為「要 Cir 嘅新聞」格式（可一鍵複製）：")
    st.text_area("Cir 內容", value=cir_text, height=360, label_visibility="collapsed")
    copy_button_html(cir_text, btn_label="一鍵複製 Cir 內容")
    st.markdown("</div>", unsafe_allow_html=True)

# 觸發生成（sidebar 的 gen 按鈕）
if gen:
    if hasattr(st, "dialog"):
        @st.dialog("要 Cir 嘅新聞（可複製）")
        def _dlg():
            show_cir_dialog()
        _dlg()
    else:
        # fallback：放在頁面頂部（但你話唔想，因為唔好複製）
        # 沒有 st.dialog 時，只能退而求其次：放在 sidebar 底部
        with st.sidebar:
            st.warning("你目前的 Streamlit 不支援彈窗（st.dialog）。已改為在左邊顯示。")
            show_cir_dialog()
