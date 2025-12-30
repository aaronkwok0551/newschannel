import os
import time
import re
import html
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests
from flask import Flask, render_template, jsonify

import feedparser

app = Flask(__name__)

# =========================
# 基本設定
# =========================
HKT = timezone(timedelta(hours=8))

TEMPLATE_NAME = os.getenv("TEMPLATE_NAME", "index.html")  # 你現有模板檔名（例如 index.html）
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "12"))
MAX_ITEMS_PER_SOURCE = int(os.getenv("MAX_ITEMS_PER_SOURCE", "10"))

# 如果你有自建 RSSHub，放呢度（只用於「RSSHub 路徑來源」，唔會再錯誤套到官方RSS）
RSSHUB_BASE = os.getenv("RSSHUB_BASE", "").strip().rstrip("/")

# Now 新聞 JSON endpoint：你要填返「真係返回你貼嗰種 JSON array」嘅 url
NOW_JSON_URL = os.getenv("NOW_JSON_URL", "").strip()

# User-Agent：好多 RSS 來源冇 UA 會 403 / 或回奇怪內容
DEFAULT_HEADERS = {
    "User-Agent": os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (compatible; NewsAggregatorBot/1.0; +https://example.com/bot)"
    ),
    "Accept": "*/*",
}

# =========================
# Cache（避免每分鐘打爆）
# =========================
CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "45"))
_cache = {"ts": 0, "data": None, "error": None}


# =========================
# Sources 定義（你可按你原本欄位名去改 key）
# type:
# - "rss": 直接抓官方RSS（info/rthk/…）
# - "rsshub": 用 RSSHub route（例：某些網站冇官方RSS你先用rsshub）
# - "now_json": Now 特別 JSON
# =========================
SOURCES = [
    {
        "key": "gov_zh",
        "name": "政府新聞（中）",
        "type": "rss",
        "url": "https://www.info.gov.hk/gia/rss/general_zh.xml",
    },
    {
        "key": "gov_en",
        "name": "政府新聞（英）",
        "type": "rss",
        "url": "https://www.info.gov.hk/gia/rss/general.xml",
    },
    {
        "key": "rthk_local",
        "name": "RTHK（本地）",
        "type": "rss",
        "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml",
    },

    # Now：用 JSON（你要在 Railway env 填 NOW_JSON_URL）
    {
        "key": "now",
        "name": "Now 新聞",
        "type": "now_json",
        "url": "",  # 留空，實際用 NOW_JSON_URL
    },

    # 如你有 RSSHub 來源，咁先用 rsshub
    # {
    #     "key": "hket_rsshub",
    #     "name": "HKET（RSSHub）",
    #     "type": "rsshub",
    #     "path": "/hket/column/..."  # RSSHub route path
    # },
]


# =========================
# Helpers
# =========================
def _is_today_hkt(dt: datetime) -> bool:
    now = datetime.now(HKT).date()
    return dt.astimezone(HKT).date() == now


def _safe_text(s: str) -> str:
    if not s:
        return ""
    return html.escape(s, quote=False)


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("\n", " ").strip()
    return s


def _parse_entry_time(entry) -> datetime | None:
    # feedparser 可能提供 published_parsed / updated_parsed
    struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if struct:
        try:
            # struct_time -> timestamp（當作 UTC 再轉 HKT）
            ts = time.mktime(struct)
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(HKT)
        except Exception:
            pass
    return None


def fetch_rss(url: str) -> list[dict]:
    """
    直接抓官方 RSS（不要經 RSSHub）
    """
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    feed = feedparser.parse(r.content)
    items = []

    for e in feed.entries[:MAX_ITEMS_PER_SOURCE]:
        title = _strip_html(getattr(e, "title", "")).strip()
        link = getattr(e, "link", "") or ""
        dt = _parse_entry_time(e) or datetime.now(HKT)

        items.append({
            "title": title,
            "link": link,
            "time": dt.strftime("%H:%M"),
            "is_new": _is_today_hkt(dt),
            # 你如需摘要可開：
            "summary": _strip_html(getattr(e, "summary", ""))[:200],
        })

    return items


def fetch_rsshub(path: str) -> list[dict]:
    """
    只用於 RSSHub route。
    """
    if not RSSHUB_BASE:
        raise RuntimeError("RSSHUB_BASE is empty but a rsshub source is configured.")

    url = urljoin(RSSHUB_BASE + "/", path.lstrip("/"))
    return fetch_rss(url)


def fetch_now_json() -> list[dict]:
    """
    Now 新聞（JSON）
    你要提供 NOW_JSON_URL，回傳內容要係你貼嗰種 array of objects（包含 title / publishDate / webUrl 或 newsId…）
    """
    if not NOW_JSON_URL:
        # 無設就返回空，避免整站 error
        return []

    r = requests.get(NOW_JSON_URL, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    data = r.json()
    if not isinstance(data, list):
        # 有些 API 會包一層 dict，自己按實際結構調整
        raise RuntimeError("NOW_JSON_URL did not return a JSON list.")

    items = []
    for obj in data[:MAX_ITEMS_PER_SOURCE]:
        title = str(obj.get("title", "")).strip()
        news_id = str(obj.get("newsId", "")).strip()

        # 你貼嗰段 JSON: publishDate 似係毫秒 timestamp
        pd = obj.get("publishDate")
        dt = datetime.now(HKT)
        try:
            if isinstance(pd, (int, float)):
                dt = datetime.fromtimestamp(pd / 1000, tz=timezone.utc).astimezone(HKT)
        except Exception:
            pass

        # Now 連結：你可按你實際頁面路由改
        # 你 JSON 入面似乎冇 webUrl，所以用 newsId 組合 player url
        link = obj.get("webUrl") or (f"https://news.now.com/home/local/player?newsId={news_id}" if news_id else "")

        items.append({
            "title": title,
            "link": link,
            "time": dt.strftime("%H:%M"),
            "is_new": _is_today_hkt(dt),
            "summary": "",  # Now JSON 如要摘要可自行抽 newsContent
        })

    return items


def build_all_sources() -> dict:
    """
    回傳格式：
    {
      "gov_zh": {"name": "...", "items":[...] , "error": None},
      ...
    }
    """
    out = {}
    for s in SOURCES:
        key = s["key"]
        name = s["name"]
        typ = s["type"]

        try:
            if typ == "rss":
                items = fetch_rss(s["url"])
            elif typ == "rsshub":
                items = fetch_rsshub(s["path"])
            elif typ == "now_json":
                items = fetch_now_json()
            else:
                raise RuntimeError(f"Unknown source type: {typ}")

            out[key] = {"name": name, "items": items, "error": None}

        except Exception as e:
            out[key] = {"name": name, "items": [], "error": str(e)}

    return out


def get_cached_data() -> dict:
    now = time.time()
    if _cache["data"] and (now - _cache["ts"] <= CACHE_SECONDS):
        return _cache["data"]

    data = build_all_sources()
    _cache["ts"] = now
    _cache["data"] = data
    _cache["error"] = None
    return data


# =========================
# Routes
# =========================
@app.route("/")
def index():
    data = get_cached_data()

    # 你原本排版（圖二）多數係 template 入面固定 grid，
    # 你只需在 template 用 data["gov_zh"]["items"] 之類渲染就得。
    # app.py 唔會改你排版。
    last_update = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")

    return render_template(
        TEMPLATE_NAME,
        data=data,
        last_update=last_update,
        rsshub_base=RSSHUB_BASE
    )


@app.route("/api/items")
def api_items():
    # 如你前端係用 JS 拉資料，可用呢個
    return jsonify(get_cached_data())


@app.route("/health")
def health():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=True)
