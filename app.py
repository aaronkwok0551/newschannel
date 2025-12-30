# app.py (Streamlit only, no Flask)
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests
import feedparser
import streamlit as st
import streamlit.components.v1 as components


# -----------------------------
# Config
# -----------------------------
HK_TZ = timezone(timedelta(hours=8))

DEFAULT_SOURCES = [
    {
        "key": "gov_zh",
        "title": "政府新聞（中）",
        "badge": "官方RSS",
        "color": "#E74C3C",
        "type": "official",
        "url": "https://www.info.gov.hk/gia/rss/general_zh.xml",
    },
    {
        "key": "gov_en",
        "title": "政府新聞（英）",
        "badge": "官方RSS",
        "color": "#C0392B",
        "type": "official",
        "url": "https://www.info.gov.hk/gia/rss/general.xml",
    },
    {
        "key": "rthk_local",
        "title": "RTHK（本地）",
        "badge": "官方RSS",
        "color": "#FF9800",
        "type": "official",
        "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",
    },
    # Now：你可以用官方 RSS / RSSHub。預設先留空給你填（因為 Now 的 RSS 來源你可能會變）
    {
        "key": "now",
        "title": "Now 新聞",
        "badge": "Now（可特別處理）",
        "color": "#2D89EF",
        "type": "now_special",
        "url": "",  # 你之後可在右上角輸入/儲存
    },
]

# Streamlit page
st.set_page_config(page_title="香港新聞聚合中心", layout="wide")


# -----------------------------
# Helpers
# -----------------------------
def hk_now():
    return datetime.now(HK_TZ)

def clean_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()

def entry_datetime(entry) -> datetime | None:
    # feedparser gives published_parsed / updated_parsed as time.struct_time
    t = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not t:
        return None
    # struct_time is in UTC-ish; treat as UTC then convert to HK for comparison display
    dt_utc = datetime(*t[:6], tzinfo=timezone.utc)
    return dt_utc.astimezone(HK_TZ)

def is_today_hk(dt: datetime) -> bool:
    now = hk_now()
    return (dt.date() == now.date())

def fetch_feed(url: str, *, timeout=15) -> feedparser.FeedParserDict:
    headers = {
        "User-Agent": "Mozilla/5.0 (NewsAggregator/1.0; +https://example.com)",
        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return feedparser.parse(r.content)

def load_items_for_source(src: dict, only_today: bool, limit: int = 10) -> tuple[list[dict], str | None]:
    """
    Returns (items, error_message)
    Each item: {title, link, dt, time_str}
    """
    url = (src.get("url") or "").strip()
    if not url:
        return [], "未設定 RSS URL"

    try:
        # Now 特別處理：有些 Now 來源會 403 / 需要跳轉 / content-type 古怪
        # 做法：同樣用 requests + feedparser，但加長 timeout 及容錯
        if src.get("type") == "now_special":
            fp = fetch_feed(url, timeout=20)
        else:
            fp = fetch_feed(url, timeout=15)

        items = []
        for e in fp.entries[: max(limit * 3, 30)]:  # 多撈少少，再按 today 過濾
            dt = entry_datetime(e)
            if dt and only_today and not is_today_hk(dt):
                continue

            title = clean_html(getattr(e, "title", "") or "")
            link = getattr(e, "link", "") or ""
            if not title:
                continue

            time_str = dt.strftime("%H:%M") if dt else "--:--"
            items.append({"title": title, "link": link, "dt": dt, "time_str": time_str})

            if len(items) >= limit:
                break

        return items, None
    except requests.HTTPError as ex:
        return [], f"RSS fetch failed: {ex}"
    except Exception as ex:
        return [], f"RSS parse failed: {type(ex).__name__}: {ex}"

def inject_auto_refresh(enabled: bool, seconds: int = 60):
    if not enabled:
        return
    ms = int(seconds * 1000)
    components.html(
        f"""
        <script>
          setTimeout(function() {{
            window.location.reload();
          }}, {ms});
        </script>
        """,
        height=0,
    )


# -----------------------------
# Sidebar controls (keep UI, not changing your card layout)
# -----------------------------
with st.sidebar:
    st.markdown("## 設定")
    auto_refresh = st.toggle("每分鐘自動更新", value=True)
    only_today = st.toggle("只顯示今日", value=True)
    per_source_limit = st.slider("每來源顯示條數", 3, 20, 10, 1)

    st.divider()
    st.markdown("### RSSHUB_BASE（如要用 RSSHub）")
    rsshub_base = st.text_input(
        "例如：https://rsshub.app 或你自建 RSSHub",
        value=os.getenv("RSSHUB_BASE", "").strip(),
        placeholder="https://your-rsshub-domain",
    )
    if rsshub_base:
        st.caption("如你有自建 RSSHub，建議用 Railway/Render 的公開 domain，並確保可外網訪問。")

    st.divider()
    st.markdown("### Now 新聞（特別設置）")
    st.caption("如果 Now 只有某條 RSS 可用，就在這裏填入那條 URL。")
    now_url = st.text_input("Now RSS URL", value=os.getenv("NOW_RSS_URL", "").strip(), placeholder="https://...")
    if now_url:
        st.caption("已設定 Now RSS URL（本次啟動生效；如要永久保存，請加到環境變數 NOW_RSS_URL）")


# -----------------------------
# Header
# -----------------------------
st.markdown(
    f"""
    <div style="display:flex; align-items:flex-end; justify-content:space-between; gap:12px;">
      <div>
        <div style="font-size:44px; font-weight:800; line-height:1;">香港新聞聚合中心</div>
        <div style="color:#666; margin-top:6px;">
          最後更新（香港時間）：{hk_now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

inject_auto_refresh(auto_refresh, 60)


# -----------------------------
# Build sources list (apply Now URL from sidebar/env)
# -----------------------------
sources = [dict(x) for x in DEFAULT_SOURCES]
for s in sources:
    if s["key"] == "now":
        s["url"] = now_url.strip() if now_url.strip() else s["url"]

# If user provided RSSHUB_BASE and Now still empty, optionally propose a default RSSHub route
# （我唔會亂改你資料，只係「幫你兜底」：有填 RSSHUB_BASE 先嘗試）
if rsshub_base and not sources[-1]["url"].strip():
    # 這個 route 你之後可以自行改成你確定可用的 Now RSSHub 路徑
    # 例如：rsshub_base + "/now/news"（不同 RSSHub 版本/路徑會唔同）
    sources[-1]["url"] = rsshub_base.rstrip("/") + "/now/news"


# -----------------------------
# CSS: black card layout (match your 圖二 feel)
# -----------------------------
st.markdown(
    """
<style>
  .board { margin-top: 12px; }
  .card {
    background: #0b0b0b;
    border: 1px solid #222;
    border-radius: 16px;
    padding: 14px 14px 12px 14px;
    min-height: 360px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.25);
  }
  .card-head {
    display:flex; align-items:center; justify-content:space-between;
    margin-bottom: 10px;
  }
  .title {
    font-size: 20px;
    font-weight: 800;
    color: #fff;
    letter-spacing: 0.2px;
  }
  .badge {
    font-size: 12px;
    color: #111;
    background: #ddd;
    padding: 5px 10px;
    border-radius: 999px;
    font-weight: 700;
    opacity: 0.95;
    white-space: nowrap;
  }
  .item {
    background: #111;
    border: 1px solid #222;
    border-left: 6px solid #666;
    border-radius: 14px;
    padding: 10px 10px 10px 12px;
    margin-bottom: 10px;
  }
  .item a {
    color: #f2f2f2;
    text-decoration: none;
    font-weight: 700;
    line-height: 1.25;
  }
  .meta {
    display:flex; align-items:center; justify-content:space-between;
    color: #bdbdbd;
    font-size: 12px;
    margin-top: 6px;
  }
  .pill {
    display:inline-block;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 800;
    background: #2b2b2b;
    color: #e7e7e7;
  }
  .err {
    color: #ffb4b4;
    background: rgba(255,0,0,0.08);
    border: 1px solid rgba(255,0,0,0.2);
    padding: 10px 12px;
    border-radius: 12px;
  }
</style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------
# Render: 5 cards per row (similar to your 圖二)
# -----------------------------
# 你可按需要加減 sources；我先放 4 個示例（政府中、政府英、RTHK、Now）
cols = st.columns(4, gap="large")

for idx, src in enumerate(sources[:4]):
    with cols[idx]:
        items, err = load_items_for_source(src, only_today=only_today, limit=per_source_limit)

        # Card header
        badge = src.get("badge", "")
        color = src.get("color", "#666")

        html = []
        html.append('<div class="card">')
        html.append('<div class="card-head">')
        html.append(f'<div class="title">{src["title"]}</div>')
        html.append(f'<div class="badge">{badge}</div>')
        html.append("</div>")

        if err:
            html.append(f'<div class="err">{err}</div>')
        elif not items:
            html.append('<div class="err">今日暫無新聞（或來源無回應）</div>')
        else:
            for it in items:
                html.append(
                    f"""
                    <div class="item" style="border-left-color:{color};">
                      <a href="{it["link"]}" target="_blank" rel="noopener noreferrer">
                        {it["title"]}
                      </a>
                      <div class="meta">
                        <span>🕒 {it["time_str"]}</span>
                        <span class="pill">NEW</span>
                      </div>
                    </div>
                    """
                )

        html.append("</div>")
        st.markdown("".join(html), unsafe_allow_html=True)


# -----------------------------
# Notes (small, no layout changes)
# -----------------------------
st.caption(
    "提示：如果某來源 404/403，通常係 RSS URL 錯、被擋、或需要 RSSHub 轉換。Now 可在側欄獨立設定 URL。"
)
