# app.py
# Streamlit 「香港新聞聚合中心」— 4 欄並列卡片版（按你張圖）
# - 每行 4 個媒體（固定）
# - 每個媒體卡片內：按時間由新到舊排序
# - 20 分鐘內的新消息：紅色 NEW + 左邊紅色條（維持 20 分鐘）
# - 支援：政府新聞（中/英）RSS、RTHK RSS、Now（API）
# - 盡量避免「div class…」：會清洗 HTML 標籤

import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st

try:
    import feedparser
except Exception as e:
    raise RuntimeError("需要安裝 feedparser：pip install feedparser") from e

try:
    from dateutil import parser as dtparser
except Exception as e:
    raise RuntimeError("需要安裝 python-dateutil：pip install python-dateutil") from e

try:
    import pytz
except Exception as e:
    raise RuntimeError("需要安裝 pytz：pip install pytz") from e


# =========================
# 基本設定
# =========================
HK_TZ = pytz.timezone("Asia/Hong_Kong")
NEW_MINUTES = 20
REQUEST_TIMEOUT = 12

GOV_ZH = "https://www.info.gov.hk/gia/rss/general_zh.xml"
GOV_EN = "https://www.info.gov.hk/gia/rss/general_en.xml"
RTHK_LOCAL = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"
NOW_API = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2"

# 你嘅 RSSHub 域名（你張圖顯示）
DEFAULT_RSSHUB_BASE = "https://rsshub-production-9dfc.up.railway.app"
RSSHUB_BASE = os.getenv("RSSHUB_BASE", DEFAULT_RSSHUB_BASE).rstrip("/")

# 你可以之後自行加更多來源，用 RSSHub route
# 例：HK01（RSSHub 路徑視乎你部署版本/route，有需要再加）
# HK01_RSS = f"{RSSHUB_BASE}/hk01/latest"  # 例子（未必啱你個 route）

UA = os.getenv(
    "UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
)


# =========================
# 資料結構
# =========================
@dataclass
class Article:
    title: str
    link: str
    dt: Optional["datetime"]  # aware datetime in HK
    time_str: str
    is_new: bool


# =========================
# 工具：時間/文字清洗
# =========================
def now_hk():
    return dtparser.parse(time.strftime("%Y-%m-%d %H:%M:%S")).replace(tzinfo=None).astimezone(HK_TZ)  # safety fallback


def hk_now():
    # 直接用 pytz
    import datetime as _dt

    return _dt.datetime.now(HK_TZ)


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\u200b", " ")  # zero-width space
    s = _TAG_RE.sub("", s)  # remove html tags
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    s = _WS_RE.sub(" ", s).strip()
    return s


def to_hk_dt(raw: Optional[str]) -> Optional["datetime"]:
    if not raw:
        return None
    try:
        dt = dtparser.parse(str(raw))
        if dt.tzinfo is None:
            dt = HK_TZ.localize(dt)
        return dt.astimezone(HK_TZ)
    except Exception:
        return None


def fmt_time(dt: Optional["datetime"]) -> str:
    if not dt:
        return "今日"
    return dt.strftime("%H:%M")


def is_new_item(dt: Optional["datetime"]) -> bool:
    if not dt:
        return False
    diff = hk_now() - dt
    return 0 <= diff.total_seconds() <= NEW_MINUTES * 60


# =========================
# HTTP / JSON 安全讀取
# =========================
def _requests_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.7",
            "Connection": "keep-alive",
        }
    )
    return s


def safe_get(url: str, params: Optional[dict] = None, timeout: int = REQUEST_TIMEOUT) -> requests.Response:
    sess = _requests_session()
    last_exc = None
    # 簡單重試：處理 Now 偶發 500
    for i in range(3):
        try:
            r = sess.get(url, params=params, timeout=timeout)
            # Now 偶發 500：小等再試
            if r.status_code >= 500:
                time.sleep(0.6 * (i + 1))
                r.raise_for_status()
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            time.sleep(0.4 * (i + 1))
    raise last_exc  # type: ignore


def safe_get_json(url: str, params: dict, timeout: int = REQUEST_TIMEOUT) -> dict:
    r = safe_get(url, params=params, timeout=timeout)
    return r.json()


# =========================
# 來源：RSS
# =========================
@st.cache_data(ttl=60, show_spinner=False)
def fetch_rss(url: str, limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    try:
        # 用 requests 拿內容，避免 feedparser 自己抓出怪 header
        r = safe_get(url, timeout=REQUEST_TIMEOUT)
        parsed = feedparser.parse(r.content)

        if getattr(parsed, "bozo", 0):
            # bozo 代表解析有問題，但未必不能用
            pass

        items: List[Article] = []
        for e in parsed.entries[: max(limit * 2, 30)]:
            title = clean_text(str(getattr(e, "title", "") or ""))
            link = str(getattr(e, "link", "") or "")
            if not title or not link:
                continue

            # RSS 常見時間欄位
            raw_dt = (
                getattr(e, "published", None)
                or getattr(e, "updated", None)
                or getattr(e, "pubDate", None)
                or getattr(e, "date", None)
            )
            dt = to_hk_dt(raw_dt)

            items.append(
                Article(
                    title=title,
                    link=link,
                    dt=dt,
                    time_str=fmt_time(dt),
                    is_new=is_new_item(dt),
                )
            )
            if len(items) >= limit:
                break

        # 由新到舊
        items.sort(key=lambda a: a.dt or dtparser.parse("1970-01-01T00:00:00+00:00"), reverse=True)
        return items[:limit], None
    except Exception as e:
        return [], f"RSS 讀取失敗：{type(e).__name__}: {e}"


# =========================
# 來源：Now API（category=119 本地/港聞）
# =========================
@st.cache_data(ttl=60, show_spinner=False)
def fetch_now_local(limit: int = 10) -> Tuple[List[Article], Optional[str]]:
    """
    Now 新聞（本地/港聞）
    - 你確認 category=119 曾 work
    - 若 API 偶發 500：內部重試
    - 清洗 title，避免「div class…」
    """
    try:
        data = safe_get_json(NOW_API, {"category": 119, "pageNo": 1}, timeout=REQUEST_TIMEOUT)

        # Now 結構可能改：保守找 list
        candidates = None
        if isinstance(data, dict):
            for k in ("data", "list", "news", "items", "result"):
                v = data.get(k)
                if isinstance(v, list):
                    candidates = v
                    break
            if candidates is None:
                for v in data.values():
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

            title = clean_text(str(it.get("newsTitle") or it.get("title") or it.get("headline") or ""))
            link = str(it.get("shareUrl") or it.get("url") or it.get("link") or "")

            if link.startswith("/"):
                link = "https://news.now.com" + link

            raw_time = it.get("publishDate") or it.get("publishTime") or it.get("publishedAt") or it.get("date")
            dt = to_hk_dt(raw_time)

            if title and link:
                out.append(
                    Article(
                        title=title,
                        link=link,
                        dt=dt,
                        time_str=fmt_time(dt),
                        is_new=is_new_item(dt),
                    )
                )

            if len(out) >= limit:
                break

        out.sort(key=lambda a: a.dt or dtparser.parse("1970-01-01T00:00:00+00:00"), reverse=True)
        return out[:limit], None

    except Exception as e:
        return [], f"Now API 讀取失敗：{type(e).__name__}: {e}"


# =========================
# UI：卡片 HTML
# =========================
def render_card(title: str, badge: str, color: str, items: List[Article], warning: Optional[str] = None):
    # 生成列表 HTML
    rows_html = []
    for a in items:
        new_badge = '<span class="new-badge">NEW</span>' if a.is_new else ""
        new_cls = "row new" if a.is_new else "row"
        # 左條：若 new 就紅；否則用媒體色
        left_color = "#E53935" if a.is_new else color

        rows_html.append(
            f"""
            <div class="{new_cls}">
              <div class="leftbar" style="background:{left_color};"></div>
              <label class="chk"><input type="checkbox" /></label>
              <div class="main">
                <div class="meta">
                  {new_badge}
                  <span class="time">{a.time_str}</span>
                </div>
                <a class="ttl" href="{a.link}" target="_blank" rel="noopener noreferrer">{a.title}</a>
              </div>
            </div>
            """
        )

    warn_html = f'<div class="warn">⚠️ {clean_text(warning)}</div>' if warning else ""
    body_html = "\n".join(rows_html) if rows_html else '<div class="empty">今日暫無新聞</div>'

    st.markdown(
        f"""
        <div class="card">
          <div class="card-head">
            <div class="card-title">
              <span class="stripe" style="background:{color};"></span>
              <span>{title}</span>
            </div>
            <span class="pill">{badge}</span>
          </div>
          {warn_html}
          <div class="card-body">
            {body_html}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def inject_css():
    st.markdown(
        """
        <style>
          /* 全局 */
          .block-container { padding-top: 18px; padding-bottom: 28px; max-width: 1400px; }
          a { text-decoration: none; }
          a:hover { text-decoration: underline; }

          /* Grid：每行 4 欄 */
          /* Streamlit columns 已控制，但卡片內做得像你張圖 */

          /* 卡片 */
          .card{
            border-radius: 14px;
            background: #ffffff;
            border: 1px solid rgba(0,0,0,0.08);
            box-shadow: 0 1px 8px rgba(0,0,0,0.06);
            overflow: hidden;
            height: 520px;               /* 你張圖類似高度，可自行改 */
            display: flex;
            flex-direction: column;
          }
          .card-head{
            padding: 12px 12px 10px 12px;
            display:flex;
            align-items:center;
            justify-content:space-between;
            border-bottom: 1px solid rgba(0,0,0,0.06);
          }
          .card-title{
            display:flex;
            align-items:center;
            gap:10px;
            font-weight: 700;
            font-size: 16px;
          }
          .stripe{
            width: 4px;
            height: 18px;
            border-radius: 4px;
            display:inline-block;
          }
          .pill{
            font-size: 12px;
            padding: 3px 8px;
            border-radius: 999px;
            border: 1px solid rgba(0,0,0,0.15);
            background: rgba(0,0,0,0.03);
          }
          .warn{
            padding: 8px 12px;
            font-size: 12px;
            color: #B71C1C;
            background: rgba(229,57,53,0.07);
            border-bottom: 1px solid rgba(0,0,0,0.06);
          }
          .card-body{
            padding: 10px 10px 12px 10px;
            overflow-y: auto;
            overflow-x: hidden;
          }

          /* 每條新聞 row */
          .row{
            display:flex;
            gap:10px;
            padding: 10px 8px;
            border-radius: 10px;
            align-items:flex-start;
          }
          .row:hover{
            background: rgba(0,0,0,0.03);
          }
          .leftbar{
            width: 4px;
            border-radius: 6px;
            min-height: 44px;
            margin-top: 2px;
            flex: 0 0 4px;
          }
          .chk{ margin-top: 2px; }
          .chk input{ width: 16px; height: 16px; }

          .main{ flex: 1; min-width: 0; }
          .meta{
            display:flex;
            gap:8px;
            align-items:center;
            margin-bottom: 4px;
          }
          .time{
            font-size: 12px;
            color: rgba(0,0,0,0.60);
          }
          .new-badge{
            font-size: 11px;
            font-weight: 700;
            color: #E53935;
            border: 1px solid rgba(229,57,53,0.5);
            padding: 1px 6px;
            border-radius: 999px;
            background: rgba(229,57,53,0.06);
          }
          .ttl{
            display:block;
            font-size: 14px;
            line-height: 1.35;
            color: rgba(0,0,0,0.88);
            word-break: break-word;
          }
          .empty{
            padding: 12px;
            font-size: 13px;
            color: rgba(0,0,0,0.55);
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =========================
# 主程式
# =========================
def main():
    st.set_page_config(page_title="香港新聞聚合中心", layout="wide")
    inject_css()

    st.title("香港新聞聚合中心")

    # 顯示最後更新（香港時間）
    updated = hk_now().astimezone(HK_TZ).strftime("%Y-%m-%d %H:%M:%S")
    st.caption(f"最後更新（香港時間）：{updated}　｜　NEW 維持 {NEW_MINUTES} 分鐘　｜　每來源顯示 10 條（可改）")

    with st.sidebar:
        st.subheader("設定")
        limit = st.slider("每個媒體顯示數量", 5, 30, 10, 1)
        st.text_input("RSSHUB_BASE（如需）", value=RSSHUB_BASE, disabled=True)
        st.caption("提示：Now API 偶發 500，本程式已內置重試。")
        st.caption("如某來源出現 HTML（div class…），會盡量清洗標籤。")

    # 來源清單（你可後加）
    sources = [
        {
            "key": "gov_zh",
            "name": "政府新聞（中文）",
            "type": "rss",
            "url": GOV_ZH,
            "color": "#B71C1C",
        },
        {
            "key": "gov_en",
            "name": "政府新聞（英文）",
            "type": "rss",
            "url": GOV_EN,
            "color": "#8E0000",
        },
        {
            "key": "rthk",
            "name": "RTHK（本地）",
            "type": "rss",
            "url": RTHK_LOCAL,
            "color": "#EF6C00",
        },
        {
            "key": "now",
            "name": "Now（本地／港聞）",
            "type": "now_api",
            "color": "#1565C0",
        },
        # 你之後可加：
        # {"key":"hk01","name":"HK01","type":"rss","url":HK01_RSS,"color":"#00897B"},
    ]

    # 固定每行 4 個
    cols_per_row = 4

    # 拉資料（先全部拉好再 render，避免 layout 抖動）
    results: Dict[str, Tuple[List[Article], Optional[str]]] = {}

    for src in sources:
        if src["type"] == "rss":
            items, warn = fetch_rss(src["url"], limit=limit)
        elif src["type"] == "now_api":
            items, warn = fetch_now_local(limit=limit)
        else:
            items, warn = [], "未支援來源類型"
        results[src["key"]] = (items, warn)

    # Render：每行 4 個
    for i in range(0, len(sources), cols_per_row):
        row = sources[i : i + cols_per_row]
        cols = st.columns(cols_per_row)
        for col_idx in range(cols_per_row):
            with cols[col_idx]:
                if col_idx >= len(row):
                    st.empty()
                    continue
                src = row[col_idx]
                items, warn = results.get(src["key"], ([], "無資料"))
                badge = str(len(items))
                render_card(src["name"], badge, src["color"], items, warning=warn)

    st.caption("如你要加 TVB／星島／i-CABLE：可以下一步逐個處理（多數要 RSSHub route 或自訂 parser）。")


if __name__ == "__main__":
    main()
