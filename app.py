import streamlit as st
import feedparser
import datetime
import pytz
import re
from bs4 import BeautifulSoup

# --- 1. 頁面基本設定 ---
st.set_page_config(page_title="香港新聞聚合", layout="wide", page_icon="📰")

# --- 2. CSS 樣式 ---
st.markdown("""
<style>
    body { font-family: "Microsoft JhengHei", "PingFang TC", sans-serif; }
    table { width: 100%; border-collapse: collapse; margin-bottom: 25px; }
    tr { border-bottom: 1px solid #eee; transition: background-color 0.2s; }
    tr:hover { background-color: #f9f9f9; }
    td { padding: 10px 12px; vertical-align: middle; }
    .col-time { 
        width: 85px; 
        min-width: 85px; 
        color: #666; 
        font-size: 0.9em; 
        white-space: nowrap; 
        font-family: monospace;
    }
    .col-source { 
        width: 110px; 
        min-width: 110px; 
        font-weight: bold; 
        white-space: nowrap; 
    }
    .col-title { width: auto; }
    .badge { 
        display: inline-block; 
        padding: 4px 0; 
        border-radius: 4px; 
        color: white; 
        font-size: 0.85rem; 
        text-align: center;
        width: 90px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.1);
    }
    a.news-link { 
        text-decoration: none; 
        color: #262730; 
        font-size: 1.05rem; 
        line-height: 1.4;
        transition: 0.2s; 
    }
    a.news-link:hover { 
        color: #ff4b4b; 
        text-decoration: underline; 
    }
    h3 { 
        margin-top: 25px; 
        border-left: 5px solid #ff4b4b; 
        padding-left: 12px; 
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. 工具函數 ---
hk_tz = pytz.timezone('Asia/Hong_Kong')

def clean_html_title(raw_html):
    """清除標題中的 HTML 標籤"""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text()
    cleanr = re.compile('<.*?>')
    text = re.sub(cleanr, '', text)
    return " ".join(text.split())

def parse_feeds(feed_list, filter_today=False):
    """讀取並解析 RSS"""
    articles = []
    now_hk = datetime.datetime.now(hk_tz)

    for source_name, url, color in feed_list:
        try:
            feed = feedparser.parse(url)
            if not feed.entries:
                continue

            for entry in feed.entries:
                dt_obj = None
                time_str = ""
                
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    dt_utc = datetime.datetime(*entry.published_parsed[:6], tzinfo=pytz.utc)
                    dt_hk = dt_utc.astimezone(hk_tz)
                    dt_obj = dt_hk
                    time_str = dt_hk.strftime('%H:%M')
                else:
                    dt_obj = now_hk
                    time_str = "--:--"

                if filter_today:
                    if dt_obj.date() != now_hk.date():
                        continue

                title_clean = clean_html_title(entry.title)
                
                articles.append({
                    'source': source_name,
                    'title': title_clean,
                    'link': entry.link,
                    'time': time_str,
                    'timestamp': dt_obj,
                    'color': color
                })
        except Exception as e:
            print(f"Error fetching {source_name}: {e}")
            continue

    articles.sort(key=lambda x: x['timestamp'], reverse=True)
    return articles

def render_news_table(articles):
    """將新聞渲染為 HTML 表格"""
    if not articles:
        return "<p style='color:#666; padding:10px;'>暫無相關新聞 (或是今日尚無更新)</p>"

    html = "<table>"
    for art in articles:
        html += f"""
        <tr>
            <td class="col-time">{art['time']}</td>
            <td class="col-source">
                <span class="badge" style="background-color: {art['color']}">{art['source']}</span>
            </td>
            <td class="col-title">
                <a class="news-link" href="{art['link']}" target="_blank">{art['title']}</a>
            </td>
        </tr>
        """
    html += "</table>"
    return html

# --- 4. 定義新聞來源 ---
gov_feeds = [
    ("政府新聞 (中)", "https://www.info.gov.hk/gia/rss/general_zh.xml", "#E74C3C"),
    ("Gov News (En)", "https://www.info.gov.hk/gia/rss/general_en.xml", "#C0392B")
]

other_feeds = [
    ("商台 903", "https://news.google.com/rss/search?q=%E5%8F%B1%E5%90%92903&hl=zh-HK&gl=HK&ceid=HK:zh-Hant", "#F1C40F"), 
    ("TVB 新聞", "https://news.tvb.com/rss/local.xml", "#2ECC71"), 
    ("Now 新聞", "https://news.now.com/rss/local", "#3498DB")      
]

# --- 5. 主程式介面 ---
st.title("🗞️ 香港新聞聚合中心")
st.caption(f"最後更新: {datetime.datetime.now(hk_tz).strftime('%Y-%m-%d %H:%M:%S')}")

if st.button("🔄 刷新新聞"):
    st.rerun()

st.markdown("### 🏛️ 政府新聞稿 (僅限今日)")
st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)

with st.spinner('正在讀取政府新聞...'):
    gov_articles = parse_feeds(gov_feeds, filter_today=True)
    st.markdown(render_news_table(gov_articles), unsafe_allow_html=True)

st.markdown("### 📺 媒體報導 (TVB / Now / 903)")
st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)

with st.spinner('正在讀取媒體新聞...'):
    other_articles = parse_feeds(other_feeds, filter_today=False) 
    st.markdown(render_news_table(other_articles), unsafe_allow_html=True)
