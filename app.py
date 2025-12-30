# app.py
# -*- coding: utf-8 -*-

import datetime
import hashlib
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

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HK_TZ = pytz.timezone("Asia/Hong_Kong")
MAX_SELECT = 5  # 左邊最多揀幾條

st.set_page_config(page_title="Tommy Sir後援會之新聞中心", layout="wide", page_icon="🗞️")

# =====================
# CSS（卡片＋NEW badge＋hover 隱藏 NEW）
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

        .item-row{
          display:flex; align-items:flex-start; gap:10px;
          background:#fff;border-left:4px solid #3b82f6;border-radius:10px;
          padding:8px 10px;margin:8px 0;
        }

        .item-content{ flex:1; min-width:0; }

        .item-title{
          font-weight:650; line-height:1.35; color:#111827;
          text-decoration:none; display:inline-block; max-width:100%;
        }
        .item-title:hover{ color:#111827; }

        .item-meta{
          font-size:0.78rem;color:#6b7280;font-family:monospace;margin-top:2px;
        }

        .badge-new{
          display:inline-block;
          margin-left:8px;
          font-size:0.70rem;
          padding:2px 7px;
          border-radius:999px;
          background:#111827;
          color:#fff;
          vertical-align:middle;
        }

        /* hover 到標題時，隱藏 NEW（你講 cursor 經過英文就取消 NEW） */
        .item-title:hover + .badge-new{
          display:none;
        }

        .empty{ color:#9ca3af;text-align:center;margin-top:20px; }
        .warn{ color:#b45309;font-size:0.85rem;margin:6px 0 0 0; }

        /* 把 checkbox 行距縮細少少 */
        div[data-testid="stCheckbox"] label { line-height: 1.1; }
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
    content: str = ""
    is_new: bool = False

# =====================
# Session State（一定要放最頂：解決「第一條唔計」）
# =====================
if "seen_links" not in st.session_state:
    st.session_state["seen_links"] = {}  # link -> first_seen_iso

if "selected" not in st.session_state:
    st.session_state["selected"] = {}  # link -> Article snapshot (dictable)

if "show_popup" not in st.session_state:
    st.session_state["show_popup"] = False

if "popup_text" not in st.session_state:
    st.session_state["popup_text"] = ""

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

def md5_key(s: str) -> str:
    return hashlib.md5((s or "").encode("utf-8")).hexdigest()[:12]

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
    return [lst[i:i+n] for i in range(0, len(lst), n)]

def mark_new_by_first_seen(articles: List[Article], window_minutes: int = 20) -> None:
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

def sort_articles_desc(articles: List[Article]) -> List[Article]:
    with_dt = [a for a in articles if a.dt is not None]
    without_dt = [a for a in articles if a.dt is None]
    with_dt.sort(key=lambda x: x.dt, reverse=True)
    return with_dt + without_dt

def build_cir_text(selected_articles: List[Article]) -> str:
    lines = []
    for a in selected_articles:
        lines.append(f"{a.source}：{a.title}")
        lines.append(f"[{a.time_str}]")
        lines.append("")
        if a.content:
            lines.append(a.content)
            lines.append("")
        lines.append(a.link)
        lines.append("")
        lines.append("Ends")
        lines.append("\n" + "-"*24 + "\n")
    return "\n".join(lines).strip()

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Streamlit; HK News Aggregator)",
    "Accept": "*/*",
}

# =====================
# Fetchers
# =====================
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

            # content：用 summary/description（清走 HTML）
            raw_sum = getattr(e, "summary", "") or getattr(e, "description", "") or ""
            content = clean_text(raw_sum) if raw_sum else ""

            out.append(
                Article(
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

            # content：Now list API 通常冇完整內文，先盡量抽 excerpt
            raw_content = it.get("content") or it.get("shortContent") or it.get("summary") or ""
            content = clean_text(str(raw_content)) if raw_content else ""

            if title and link:
                out.append(
                    Article(
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
# UI Header
# =====================
st.title("🗞️ Tommy Sir後援會之新聞中心")
st.caption(f"最後更新（香港時間）：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

# Sidebar controls
rsshub_base = st.sidebar.text_input(
    "RSSHub Base URL（例如 https://rsshub-production-xxxx.up.railway.app）",
    value="https://rsshub-production-9dfc.up.railway.app",
).rstrip("/")

auto = st.toggle("每分鐘自動更新", value=True)
if auto:
    st_autorefresh(interval=60_000, key="auto")

limit = st.sidebar.slider("每個來源顯示幾多條", 5, 30, 12, 1)

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
    {"name": "Now（本地）", "type": "now_api", "url": "", "color": "#16A34A"},
    {"name": "HK01", "type": "rss", "url": f"{rsshub_base}/hk01/latest", "color": "#2563EB"},
    {"name": "on.cc 東網", "type": "rss", "url": f"{rsshub_base}/oncc/zh-hant/news", "color": "#7C3AED"},
    {"name": "星島（Feedly RSS）", "type": "rss", "url": "https://www.stheadline.com/rss", "color": "#F97316"},
    {"name": "明報即時", "type": "rss", "url": "https://news.mingpao.com/rss/ins/all.xml", "color": "#0EA5E9"},
    {"name": "i-CABLE 有線", "type": "rss", "url": "https://www.i-cable.com/feed", "color": "#A855F7"},
    {"name": "經濟日報 HKET", "type": "rss", "url": "https://www.hket.com/rss/hongkong", "color": "#64748B"},
    {"name": "信報即時", "type": "rss", "url": f"{rsshub_base}/hkej/index", "color": "#334155"},
    {"name": "巴士的報", "type": "rss", "url": "https://www.bastillepost.com/hongkong/feed", "color": "#9333EA"},
]

# =====================
# Action Panel（左邊 pinned：用 sidebar）
# =====================
st.sidebar.markdown("### ✅ Action Panel")
selected_map: Dict[str, dict] = st.session_state["selected"]

def clear_all():
    # 清 selected
    st.session_state["selected"] = {}
    # 清所有 checkbox（所有 key 以 chk_ 開頭）
    for k in list(st.session_state.keys()):
        if str(k).startswith("chk_"):
            del st.session_state[k]
    st.session_state["show_popup"] = False
    st.session_state["popup_text"] = ""

st.sidebar.button("🧹 一鍵取消所有選擇", on_click=clear_all)

sel_count = len(st.session_state["selected"])
st.sidebar.write(f"已選擇：**{sel_count}/{MAX_SELECT}**")

if sel_count == 0:
    st.sidebar.info("勾選右邊新聞後，呢度會顯示要 Cir 嘅列表。")
else:
    # 顯示選中列表（按時間/或加入先後）
    # 我用加入先後（dict insertion order）方便你 Cir
    for link, snap in st.session_state["selected"].items():
        st.sidebar.markdown(f"- {snap['source']}：{snap['title']}  \n  `[{snap['time_str']}]`")

# 生成 popup 內容
def make_popup():
    arts = []
    for link, snap in st.session_state["selected"].items():
        arts.append(
            Article(
                source=snap["source"],
                title=snap["title"],
                link=snap["link"],
                dt=None,
                time_str=snap["time_str"],
                color=snap.get("color", "#111827"),
                content=snap.get("content", ""),
                is_new=False,
            )
        )
    st.session_state["popup_text"] = build_cir_text(arts)
    st.session_state["show_popup"] = True

st.sidebar.button("📌 要 Cir 嘅新聞（生成）", disabled=(sel_count == 0), on_click=make_popup)

# =====================
# Popup（st.dialog；冇就 fallback）
# =====================
def render_copy_box(text: str):
    # 顯示可複製文字 + 一鍵複製（JS）
    st.code(text, language="")
    # 一鍵複製（Streamlit 原生冇 clipboard button，改用 components）
    import streamlit.components.v1 as components

    safe = text.replace("\\", "\\\\").replace("`", "\\`")
    components.html(
        f"""
        <div style="margin-top:8px;">
          <button id="copybtn" style="
            padding:8px 12px;border-radius:8px;border:1px solid #e5e7eb;
            background:#111827;color:#fff;cursor:pointer;font-weight:700;">
            一鍵複製
          </button>
          <span id="copystatus" style="margin-left:10px;color:#16a34a;font-weight:700;"></span>
        </div>
        <script>
          const text = `{safe}`;
          const btn = document.getElementById("copybtn");
          const status = document.getElementById("copystatus");
          btn.addEventListener("click", async () => {{
            try {{
              await navigator.clipboard.writeText(text);
              status.textContent = "已複製";
              setTimeout(()=>status.textContent="", 1500);
            }} catch (e) {{
              status.textContent = "複製失敗（瀏覽器限制）";
              setTimeout(()=>status.textContent="", 2500);
            }}
          }});
        </script>
        """,
        height=70,
    )

if st.session_state["show_popup"] and st.session_state["popup_text"]:
    if hasattr(st, "dialog"):
        @st.dialog("要 Cir 嘅新聞（可複製）")
        def _dlg():
            render_copy_box(st.session_state["popup_text"])
            if st.button("關閉"):
                st.session_state["show_popup"] = False
        _dlg()
    else:
        # fallback：唔會整個白框喺頂，只喺 sidebar 展開顯示
        with st.sidebar.expander("要 Cir 嘅新聞（可複製）", expanded=True):
            render_copy_box(st.session_state["popup_text"])
            if st.button("關閉（fallback）"):
                st.session_state["show_popup"] = False

# =====================
# Render Grid（每行 4 個媒體；內容一定入卡片內）
# =====================
cols_per_row = 4
rows = chunked(sources, cols_per_row)

for row in rows:
    cols = st.columns(len(row))
    for col, src in zip(cols, row):
        with col:
            # 取新聞
            if src["type"] == "now_api":
                arts, warn = fetch_now_api(src["name"], src["color"], limit=limit)
            else:
                arts, warn = fetch_rss(src["url"], src["name"], src["color"], limit=limit)

            # NEW（20 分鐘）
            mark_new_by_first_seen(arts, window_minutes=20)

            # 排序（有時間的先排）
            arts = sort_articles_desc(arts)

            # 卡片 header
            st.markdown(f"<div class='section-title'>{html.escape(src['name'])}</div>", unsafe_allow_html=True)

            # 卡片 container（所有內容都放入 card，唔會跌到底下）
            with st.container(border=False):
                st.markdown("<div class='card'><div class='items'>", unsafe_allow_html=True)

                if not arts:
                    st.markdown("<div class='empty'>暫無內容</div>", unsafe_allow_html=True)
                else:
                    # 現在已選數
                    current_selected = len(st.session_state["selected"])

                    for a in arts:
                        # 每條獨立 checkbox key（避免第一條唔計/撞 key）
                        ck = f"chk_{md5_key(src['name'])}_{md5_key(a.link)}"

                        # 如果已選滿 5，其他未選的 disable
                        already_selected = (a.link in st.session_state["selected"])
                        disable_this = (current_selected >= MAX_SELECT) and (not already_selected)

                        # item row HTML 開始
                        st.markdown(
                            f"<div class='item-row' style='border-left-color:{a.color}'>",
                            unsafe_allow_html=True,
                        )

                        # 左邊 checkbox（真正 streamlit widget，唔會變 div class code）
                        checked = st.checkbox(
                            " ",
                            key=ck,
                            value=already_selected,
                            disabled=disable_this,
                            label_visibility="collapsed",
                        )

                        # 同步 selected（點第一條都會即時入 dict）
                        if checked and (a.link not in st.session_state["selected"]):
                            st.session_state["selected"][a.link] = {
                                "source": a.source,
                                "title": a.title,
                                "link": a.link,
                                "time_str": a.time_str,
                                "content": a.content,
                                "color": a.color,
                            }
                        if (not checked) and (a.link in st.session_state["selected"]):
                            del st.session_state["selected"][a.link]

                        # 右邊內容（標題＋NEW＋時間）
                        new_badge = "<span class='badge-new'>NEW</span>" if a.is_new else ""
                        st.markdown(
                            dedent(
                                f"""
                                <div class="item-content">
                                  <a class="item-title" href="{html.escape(a.link)}" target="_blank" rel="noopener noreferrer">
                                    {html.escape(a.title)}
                                  </a>
                                  {new_badge}
                                  <div class="item-meta">🕐 {html.escape(a.time_str)}</div>
                                </div>
                                """
                            ).strip(),
                            unsafe_allow_html=True,
                        )

                        # item row HTML 結束
                        st.markdown("</div>", unsafe_allow_html=True)

                # warning
                if warn:
                    st.markdown(f"<div class='warn'>⚠️ {html.escape(warn)}</div>", unsafe_allow_html=True)

                st.markdown("</div></div>", unsafe_allow_html=True)
