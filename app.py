# app.py
# -*- coding: utf-8 -*-

import datetime
import html
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

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
HK_TZ = pytz.timezone("Asia/Hong_Kong")
st.set_page_config(page_title="Tommy Sir 後援會新聞中心", layout="wide", page_icon="🗞️")

# =====================
# CSS
# =====================
st.markdown(
    dedent(
        """
<style>
body { font-family: "Microsoft JhengHei","PingFang TC",sans-serif; }

.card{
  background:#fff;border:1px solid #e5e7eb;border-radius:12px;
  padding:12px;height:520px;display:flex;flex-direction:column;
}

.items{ overflow-y:auto; flex:1; }

.item{
  border-left:4px solid #3b82f6;
  border-radius:8px;
  padding:8px 10px;
  margin:8px 0;
  position:relative;
}

.item a{
  text-decoration:none;color:#111827;font-weight:600;
}

.item-meta{
  font-size:0.78rem;color:#6b7280;margin-top:4px;
}

.new-badge{
  position:absolute;
  right:8px; top:8px;
  background:#111827;
  color:#fff;
  font-size:0.7rem;
  padding:2px 6px;
  border-radius:6px;
}

.item:hover .new-badge{
  display:none;
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
    media: str
    title: str
    link: str
    time_str: str
    content: str

# =====================
# Helpers
# =====================
def clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    soup = BeautifulSoup(raw, "html.parser")
    return soup.get_text(" ", strip=True)

def now_hk():
    return datetime.datetime.now(HK_TZ)

# =====================
# State init
# =====================
if "selected" not in st.session_state:
    st.session_state.selected: Dict[str, Article] = {}

if "seen_new" not in st.session_state:
    st.session_state.seen_new: Dict[str, bool] = {}

# =====================
# Fetch RSS
# =====================
def fetch_rss(url: str, media: str, limit=10) -> List[Article]:
    feed = feedparser.parse(url)
    out = []
    for e in feed.entries[:limit]:
        title = clean_text(getattr(e, "title", ""))
        link = getattr(e, "link", "")
        summary = clean_text(getattr(e, "summary", ""))
        dt = None
        if getattr(e, "published", None):
            try:
                dt = dtparser.parse(e.published)
            except:
                pass
        time_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "—"
        aid = f"{media}:{link}"
        out.append(
            Article(
                id=aid,
                media=media,
                title=title,
                link=link,
                time_str=time_str,
                content=summary,
            )
        )
    return out

# =====================
# Sidebar Action Panel
# =====================
with st.sidebar:
    st.header("🧾 Action Panel")

    if st.button("❌ 一鍵取消所有選擇"):
        st.session_state.selected.clear()

    st.markdown(f"**已選新聞：{len(st.session_state.selected)} 條**")

    if st.button("📤 要 Cir 嘅新聞", disabled=len(st.session_state.selected) == 0):
        st.session_state.show_dialog = True

# =====================
# Media sources
# =====================
sources = [
    ("政府新聞（中）", "https://www.info.gov.hk/gia/rss/general_zh.xml"),
    ("RTHK", "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"),
    ("HK01", "https://rsshub-production-9dfc.up.railway.app/hk01/latest"),
    ("on.cc", "https://rsshub-production-9dfc.up.railway.app/oncc/zh-hant/news"),
]

# =====================
# Main UI
# =====================
st.title("🗞️ Tommy Sir 後援會新聞中心")
st.caption(f"更新時間：{now_hk().strftime('%Y-%m-%d %H:%M:%S')}")

st_autorefresh(interval=60_000, key="auto")

cols = st.columns(4)

for col, (media, url) in zip(cols, sources):
    with col:
        st.markdown(f"### {media}")
        st.markdown('<div class="card"><div class="items">', unsafe_allow_html=True)

        for art in fetch_rss(url, media):
            is_new = art.id not in st.session_state.seen_new

            checked = art.id in st.session_state.selected
            cb = st.checkbox(
                art.title,
                value=checked,
                key=f"cb_{art.id}",
            )

            if cb:
                st.session_state.selected[art.id] = art
            else:
                st.session_state.selected.pop(art.id, None)

            badge = ""
            if is_new:
                badge = '<span class="new-badge">NEW</span>'
                st.session_state.seen_new[art.id] = True

            st.markdown(
                f"""
<div class="item">
<a href="{art.link}" target="_blank">{art.title}</a>
{badge}
<div class="item-meta">{art.time_str}</div>
</div>
""",
                unsafe_allow_html=True,
            )

        st.markdown("</div></div>", unsafe_allow_html=True)

# =====================
# Popup Dialog
# =====================
if st.session_state.get("show_dialog"):
    with st.dialog("📤 要 Cir 嘅新聞（可複製）"):
        text_blocks = []
        for art in st.session_state.selected.values():
            text_blocks.append(
                f"""{art.media}：{art.title}
[{art.time_str}]

{art.content}

{art.link}

Ends"""
            )
        final_text = "\n\n---\n\n".join(text_blocks)
        st.code(final_text, language="text")
        if st.button("關閉"):
            st.session_state.show_dialog = False
