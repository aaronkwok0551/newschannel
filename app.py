-- coding: utf-8 --
import streamlit as st
import feedparser
import datetime
import pytz
import re
from bs4 import BeautifulSoup
import sys

設定預設編碼
try:
sys.stdout.reconfigure(encoding='utf-8')
except:
pass

--- 1. 頁面基本設定 ---
st.set_page_config(
page_title="香港新聞聚合",
layout="wide",
page_icon="📰"
)

--- 2. CSS 樣式 ---
st.markdown("""

<style> body { font-family: "Microsoft JhengHei", "PingFang TC", sans-serif; } .news-source-header { font-size: 1.1em; font-weight: bold; color: #1e293b; margin-top: 0; margin-bottom: 8px; padding: 8px 12px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 6px; display: inline-block; } .news-item { padding: 10px 12px; margin: 6px 6px; background: white; border-left: 4px solid #3498db; border-radius: 6px; transition: all 0.2s ease; box-shadow: 0 1px 3px rgba(0,0,0,0.05); } .news-item:hover { transform: translateX(4px); box-shadow: 0 3px 8px rgba(0,0,0,0.12); border-left-color: #e74c3c; } .news-title { font-size: 1rem; font-weight: 500; color: #2c3e50; text-decoration: none; line-height: 1.5; display: block; margin-bottom: 4px; } .news-title:hover { color: #e74c3c; } .news-time { font-size: 0.85rem; color: #7f8c8d; font-family: monospace; } .gov-section { background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); padding: 16px; border-radius: 12px; margin-bottom: 20px; } .media-section { background: #f8f9fa; padding: 16px; border-radius: 12px; } /* 欄位容器樣式 */ div[data-testid="column"] { background: white; padding: 12px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.05); margin: 6px; } h3 { color: #2c3e50; font-weight: 600; margin-bottom: 12px; padding-bottom: 6px; border-bottom: 3px solid #3498db; } </style>
""", unsafe_allow_html=True)

--- 3. 工具函數 ---
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

def parse_single_feed(source_name, url, color, filter_today=False, max_items=10):
"""讀取單個 RSS 來源，回傳條目字典列表"""
articles = []
now_hk = datetime.datetime.now(hk_tz)

text
try:
    feed = feedparser.parse(url)
    if not feed.entries:
        return articles

    for entry in feed.entries[:max_items]:
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

articles.sort(key=lambda x: x['timestamp'], reverse=True)
return articles
def render_news_items(articles):
"""渲染新聞項目為 HTML"""
if not articles:
return "<p style='color:#95a5a6; padding:15px; text-align:center;'>暫無新聞</p>"

text
html = ""
for art in articles:
    html += f"""
    <div class="news-item">
        <a href="{art['link']}" target="_blank" class="news-title">
            {art['title']}
        </a>
        <span class="news-time">🕐 {art['time']}</span>
    </div>
    """
return html
--- 4. 定義新聞來源 ---
gov_feeds = [
("政府新聞 (中)", "https://www.info.gov.hk/gia/rss/general_zh.xml", "#E74C3C"),
("Gov News (En)", "https://www.info.gov.hk/gia/rss/general_en.xml", "#C0392B")
]

media_feeds = [
("TVB 新聞", "https://news.tvb.com/rss/local.xml", "#2ECC71"),
("Now 新聞", "https://news.now.com/rss/local", "#3498DB"),
("商台 903", "https://news.google.com/rss/search?q=%E5%8F%B1%E5%90%92903&hl=zh-HK&gl=HK&ceid=HK:zh-Hant", "#F1C40F"),
("香港電台", "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "#FF9800"),
("有線新聞", "https://www.i-cable.com/feed/", "#c0392b"),
("HK01", "https://web-data.api.hk01.com/v2/feed/category/0", "#184587")
]

--- 5. 主程式介面 ---
st.title("🗞️ 香港新聞聚合中心")
st.caption(f"最後更新: {datetime.datetime.now(hk_tz).strftime('%Y-%m-%d %H:%M:%S')}")

自動刷新按鈕（可選，若不需要可移除）
if st.button("🔄 刷新新聞", type="primary"):
st.experimental_rerun()

st.divider()

--- 政府新聞區塊：合併顯示 ---
st.markdown('<div class="gov-section">', unsafe_allow_html=True)
st.markdown("### 🏛️ 政府新聞與公告 (實時聚合)")

with st.spinner('讀取中...'):
zh_articles = parse_single_feed(gov_feeds, gov_feeds, gov_feeds, filter_today=False, max_items=20)
en_articles = parse_single_feed(gov_feeds, gov_feeds, gov_feeds, filter_today=False, max_items=20)
merged_gov = zh_articles + en_articles
merged_gov.sort(key=lambda x: x['timestamp'], reverse=True)
st.markdown(render_news_items(merged_gov), unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)

st.divider()

--- 媒體報導區塊：緊湊網格 ---
st.markdown('<div class="media-section">', unsafe_allow_html=True)
st.markdown("### 📺 媒體報導（實時頭條）")

以三列兩排的方式緊湊排布
row1_cols = st.columns(3)
row2_cols = st.columns(3)
all_cols = [row1_cols, row1_cols, row1_cols, row2_cols, row2_cols, row2_cols]

for idx, (source_name, url, color) in enumerate(media_feeds):
with all_cols[idx]:
icon_map = {
"TVB 新聞": "📺",
"Now 新聞": "📺",
"商台 903": "📻",
"香港電台": "📻",
"有線新聞": "📺",
"HK01": "📱"
}
icon = icon_map.get(source_name, "📰")

text
    st.markdown(f'<div class="news-source-header">{icon} {source_name}</div>', unsafe_allow_html=True)
    with st.spinner('讀取中...'):
        # HK01 可能需要特殊處理；嘗試取得，若失敗顯示訊息
        try:
            articles = parse_single_feed(source_name, url, color, filter_today=False, max_items=12)
        except Exception as e:
            print(f"Error fetching {source_name}: {e}")
            articles = []
        st.markdown(render_news_items(articles), unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

