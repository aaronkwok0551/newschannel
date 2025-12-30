# app.py
import os
import re
import html
import time
from datetime import datetime, date
from urllib.parse import urlparse

import requests
import feedparser
import streamlit as st

try:
    import pytz
    HK_TZ = pytz.timezone("Asia/Hong_Kong")
except Exception:
    HK_TZ = None

# ---------------------------
# Config
# ---------------------------
DEFAULT_RSSHUB_BASE = os.getenv("RSSHUB_BASE", "").rstrip("/")
# 例：RSSHUB_BASE=https://rsshub.app 或你自己部署嘅 https://xxxx.railway.app
# 若留空，RSSHub 來源會顯示「未設定」

NOW_CATEGORY_DEFAULT = "119"  # 港聞（你提供嘅例子）

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NewsHub/1.0; +https://example.com)"
}

TIMEOUT = 12

# ---------------------------
# Helpers
# ---------------------------
def hk_now() -> datetime:
    if HK_TZ:
        return datetime.now(HK_TZ)
    return datetime.now()

def hk_today() -> date:
    return hk_now().date()

def safe_text(s: str) -> str:
    s = s or ""
    s = re.sub(r"\s+", " ", s).strip()
    return html.escape(s)

def normalize_url(u: str) -> str:
    if not u:
        return ""
    u = u.strip()
    return u

def is_today(dt: datetime) -> bool:
    if not dt:
        return False
    return dt.date() == hk_today()

def parse_feed_datetime(entry) -> datetime | None:
    # feedparser: entry.published_parsed / updated_parsed (time.struct_time)
    for key in ("published_parsed", "updated_parsed"):
        t = getattr(entry, key, None)
        if t:
            try:
                # treat as local time; if HK_TZ exists, localize
                d = datetime(*t[:6])
                if HK_TZ:
                    return HK_TZ.localize(d)
                return d
            except Exception:
                pass
    return None

def fetch_rss(url: str, limit: int = 10, today_only: bool = False):
    items = []
    err = None
    if not url:
        return items, "URL is empty"

    try:
        # feedparser can read via URL directly, but using requests gives better control
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        feed = feedparser.parse(r.content)

        for e in feed.entries[: max(50, limit * 3)]:
            title = getattr(e, "title", "") or ""
            link = getattr(e, "link", "") or ""
            dt = parse_feed_datetime(e)

            if today_only and dt and not is_today(dt):
                continue

            items.append(
                {
                    "title": title.strip(),
                    "link": normalize_url(link),
                    "time": dt.strftime("%H:%M") if dt else "",
                    "dt": dt,
                }
            )
            if len(items) >= limit:
                break
    except Exception as ex:
        err = f"RSS fetch failed: {ex}"

    return items, err

def fetch_now_news(category: str = NOW_CATEGORY_DEFAULT, page_no: int = 1, page_size: int = 20, limit: int = 10, today_only: bool = False):
    """
    Now 新聞：使用你提供嘅 JSON API 格式（newsapi1.now.com / getNewsListv2）
    """
    items = []
    err = None

    # 你截圖顯示 path: /pccw-news-api/api/getNewsListv2?category=119&pageNo=1...
    url = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2"
    params = {
        "category": str(category),
        "pageNo": str(page_no),
        "pageSize": str(page_size),
    }

    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()

        # 你提供例子係 list[dict]，但有機會包一層 dict
        if isinstance(data, dict):
            # 常見：{"newsList":[...]} 或 {"data":[...]}
            for k in ("newsList", "data", "result", "items"):
                if k in data and isinstance(data[k], list):
                    data = data[k]
                    break

        if not isinstance(data, list):
            return [], "Now API returned unexpected JSON structure"

        for it in data:
            title = (it.get("title") or it.get("storyTitle") or "").strip()
            news_id = (it.get("newsId") or "").strip()

            # Now 有時 webUrl 為 null，你例子見到內文有 link（player?newsId=xxxxx）
            link = it.get("webUrl")
            if not link and news_id:
                # 用你例子中出現過嘅路徑形式（最穩用 newsId 組）
                # local / international 其實可由 categoryName/欄目決定，但先用 home/local/player
                link = f"https://news.now.com/home/local/player?newsId={news_id}"

            publish_ms = it.get("publishDate")
            dt = None
            if isinstance(publish_ms, (int, float)):
                try:
                    dt_utc = datetime.utcfromtimestamp(publish_ms / 1000.0)
                    if HK_TZ:
                        dt = pytz.utc.localize(dt_utc).astimezone(HK_TZ)
                    else:
                        dt = dt_utc
                except Exception:
                    dt = None

            if today_only and dt and not is_today(dt):
                continue

            if title:
                items.append(
                    {
                        "title": title,
                        "link": normalize_url(link),
                        "time": dt.strftime("%H:%M") if dt else "",
                        "dt": dt,
                    }
                )
            if len(items) >= limit:
                break

    except Exception as ex:
        err = f"Now API fetch failed: {ex}"

    return items, err

def build_rsshub_url(rsshub_base: str, path: str) -> str:
    rsshub_base = (rsshub_base or "").rstrip("/")
    if not rsshub_base:
        return ""
    if not path.startswith("/"):
        path = "/" + path
    return f"{rsshub_base}{path}"

def dedup_items(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for it in items:
        key = (it.get("link") or it.get("title") or "").strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out

def render_cards(source_name: str, items: list[dict], color: str = "#777", err: str | None = None):
    today_str = hk_today().strftime("%Y-%m-%d")
    st.markdown(
        f"""
        <div style="display:flex;align-items:flex-end;justify-content:space-between;margin:4px 0 8px 0;">
          <div style="font-weight:700;font-size:16px;">{safe_text(source_name)}</div>
          <div style="color:#666;font-size:12px;">今日 {today_str}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if err:
        st.markdown(f"<div style='color:#b00020;font-size:12px;margin-bottom:6px;'>{safe_text(err)}</div>", unsafe_allow_html=True)

    if not items:
        st.markdown("<div style='color:#666;font-size:13px;padding:10px;border:1px dashed #ddd;border-radius:10px;'>今日暫無更新（或來源暫時抓取不到）</div>", unsafe_allow_html=True)
        return

    # 卡片
    cards_html = []
    for it in items:
        title = safe_text(it.get("title", ""))
        link = it.get("link", "")
        t = safe_text(it.get("time", ""))
        left_bar = f"background:{color};"

        if link:
            title_html = f"<a href='{html.escape(link)}' target='_blank' rel='noopener noreferrer' style='text-decoration:none;color:#111;'>{title}</a>"
        else:
            title_html = f"<span style='color:#111;'>{title}</span>"

        cards_html.append(
            f"""
            <div style="border:1px solid #eee;border-radius:12px;padding:10px 12px;margin:8px 0;display:flex;gap:10px;">
              <div style="width:6px;border-radius:8px;{left_bar}"></div>
              <div style="flex:1;">
                <div style="font-size:14px;line-height:1.35;font-weight:600;">{title_html}</div>
                <div style="margin-top:6px;color:#666;font-size:12px;">🕒 {t if t else "--:--"}</div>
              </div>
            </div>
            """
        )

    st.markdown("".join(cards_html), unsafe_allow_html=True)

# ---------------------------
# Streamlit UI
# ---------------------------
st.set_page_config(page_title="香港新聞聚合中心", layout="wide")

st.title("香港新聞聚合中心")

# refresh control
col_a, col_b, col_c = st.columns([1.2, 1.2, 2.6])
with col_a:
    auto_refresh = st.toggle("每分鐘自動更新", value=True)
with col_b:
    today_only = st.toggle("只顯示今日", value=True)
with col_c:
    rsshub_base = st.text_input("RSSHUB_BASE（留空則停用 RSSHub 來源）", value=DEFAULT_RSSHUB_BASE, placeholder="例如：https://rsshub.app 或你的自建 RSSHub")

if auto_refresh:
    # Streamlit 1.33+ 有 st.autorefresh；舊版本用 st.experimental_rerun + sleep 會阻塞
    try:
        st.autorefresh(interval=60_000, key="autorefresh")
    except Exception:
        pass

st.caption(f"最後更新（香港時間）：{hk_now().strftime('%Y-%m-%d %H:%M:%S')}")

# ---------------------------
# Sources
# ---------------------------
# 顏色只係 UI 左邊色條
SOURCES = [
    # 政府新聞（官方 RSS，唔經 RSSHub）
    {
        "name": "政府新聞（中文）",
        "type": "rss",
        "url": "https://www.info.gov.hk/gia/rss/general_zh.xml",
        "color": "#E74C3C",
        "limit": 10,
    },
    {
        "name": "政府新聞（英文）",
        "type": "rss",
        "url": "https://www.info.gov.hk/gia/rss/general.xml",
        "color": "#C0392B",
        "limit": 10,
    },

    # RTHK（官方 RSS）
    {
        "name": "RTHK（本地）",
        "type": "rss",
        "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",
        "color": "#FF9800",
        "limit": 10,
    },

    # Now（唔用 RSSHub，直接 JSON API）
    {
        "name": "Now 新聞（港聞）",
        "type": "now_api",
        "category": NOW_CATEGORY_DEFAULT,
        "color": "#3B82F6",
        "limit": 10,
    },

    # RSSHub sources（需要 RSSHUB_BASE）
    {
        "name": "HK01（最新）",
        "type": "rsshub",
        "path": "/hk01/latest",
        "color": "#10B981",
        "limit": 10,
    },
    {
        "name": "on.cc 東網（新聞）",
        "type": "rsshub",
        "path": "/oncc/zh-hant/news",
        "color": "#7C3AED",
        "limit": 10,
    },
    {
        "name": "TVB 新聞（繁中）",
        "type": "rsshub",
        "path": "/tvb/news/tc",
        "color": "#111827",
        "limit": 10,
    },
    {
        "name": "信報即時（hkej）",
        "type": "rsshub",
        "path": "/hkej/index",
        "color": "#0EA5E9",
        "limit": 10,
    },
    {
        "name": "星島即時",
        "type": "rsshub",
        "path": "/stheadline/std/realtime",
        "color": "#F97316",
        "limit": 10,
    },
    {
        "name": "i-CABLE 有線",
        "type": "rsshub",
        "path": "/icable/all",
        "color": "#EF4444",
        "limit": 10,
    },
    {
        "name": "Now（RSSHub 版，可能會壞）",
        "type": "rsshub",
        "path": "/now/news",
        "color": "#2563EB",
        "limit": 10,
    },

    # 明報：你話「官方 RSS」—我唔強行猜 URL，留一個位置俾你填
    {
        "name": "明報（官方 RSS：請填 URL）",
        "type": "rss",
        "url": "",  # <- 你搵到官方 RSS URL 後填呢度
        "color": "#6B7280",
        "limit": 10,
    },
]

# ---------------------------
# Fetch & Render
# ---------------------------
# 頁面排版：兩行 grid（你可自行改 columns 數量）
cols = st.columns(4)

for idx, src in enumerate(SOURCES):
    c = cols[idx % 4]
    with c:
        items = []
        err = None

        if src["type"] == "rss":
            items, err = fetch_rss(src.get("url", ""), limit=src.get("limit", 10), today_only=today_only)

            # 如果係「明報」而 url 係空，俾更清晰訊息
            if not src.get("url"):
                err = "未設定 RSS URL（請在 app.py 補上官方 RSS 連結）"
                items = []

        elif src["type"] == "rsshub":
            url = build_rsshub_url(rsshub_base, src.get("path", ""))
            if not rsshub_base:
                err = "未設定 RSSHUB_BASE（已停用 RSSHub 來源）"
                items = []
            else:
                items, err = fetch_rss(url, limit=src.get("limit", 10), today_only=today_only)

        elif src["type"] == "now_api":
            items, err = fetch_now_news(
                category=src.get("category", NOW_CATEGORY_DEFAULT),
                page_no=1,
                page_size=20,
                limit=src.get("limit", 10),
                today_only=today_only,
            )

        # 去重（避免同一條重覆）
        items = dedup_items(items)

        # 顯示
        render_cards(src["name"], items, color=src.get("color", "#777"), err=err)
