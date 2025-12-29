# -*- coding: utf-8 -*-
import streamlit as st
import requests
import feedparser
import datetime
import pytz
import urllib.parse
import time
from bs4 import BeautifulSoup
import sys
from streamlit_autorefresh import st_autorefresh

# 設定預設編碼
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

# --- 1. 頁面與自定義樣式 (含閃爍特效) ---
st.set_page_config(
    page_title="Tommy Sir 後援會之新聞監察系統",
    page_icon="📰",
    layout="wide"
)

# 自動刷新 (每 60 秒)
st_autorefresh(interval=60 * 1000, limit=None, key="news_autoupdate")

st.markdown("""
<style>
    /* 閃爍特效 */
    @keyframes blinker {
        50% { opacity: 0; }
    }
    .new-badge {
        color: #ff4b4b;
        font-weight: bold;
        animation: blinker 1s linear infinite;
        margin-right: 5px;
    }
    .read-text {
        color: #a0a0a0 !important;
    }
    .stCheckbox { margin-bottom: 0px; }
    .news-source-header { 
        font-size: 1.2em; 
        font-weight: bold; 
        color: #1e293b; 
        margin-top: 15px; 
        margin-bottom: 10px;
        padding-bottom: 5px;
        border-bottom: 2px solid #ddd;
    }
    a { text-decoration: none; color: #2980b9; }
    div[data-testid="column"] { display: flex; align-items: start; }
    .generated-box {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #dcdfe6;
    }
</style>
""", unsafe_allow_html=True)

# 設定時區
HK_TZ = pytz.timezone('Asia/Hong_Kong')
UTC_TZ = pytz.timezone('UTC')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

# --- 2. 核心功能函式 ---

def fetch_full_article(url):
    """ 抓取完整的正文內容 """
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        paragraphs = soup.find_all('p')
        if not paragraphs:
            return "無法抓取全文，請點擊連結查看原文。"
        full_text = "\n".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 10])
        return full_text if len(full_text) > 20 else "內容抓取受限，請點擊連結。"
    except Exception as e:
        return f"全文抓取失敗: {str(e)}"

def resolve_google_url(url):
    if "news.google.com" not in url:
        return url
    try:
        r = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=5)
        return r.url
    except:
        return url

def is_new_news(published_time_str):
    """ 判斷是否為 15 分鐘內的新聞 """
    try:
        pub_time = datetime.datetime.strptime(published_time_str, '%Y-%m-%d %H:%M')
        pub_time = HK_TZ.localize(pub_time)
        now = datetime.datetime.now(HK_TZ)
        diff = (now - pub_time).total_seconds() / 60
        return diff <= 15
    except:
        return False

@st.cache_data(ttl=60)
def fetch_news_data(func, *args):
    return func(*args)

# 抓取邏輯 (封裝原本的 fetch 函數)
def fetch_google_rss(site_domain, site_name, color):
    query = urllib.parse.quote(f"site:{site_domain}")
    rss_url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    feed = feedparser.parse(rss_url)
    news = []
    for entry in feed.entries[:8]:
        title = entry.title.rsplit(" - ", 1)[0] if " - " in entry.title else entry.title
        dt_str = ""
        if hasattr(entry, 'published_parsed'):
            dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
            dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
        news.append({'source': site_name, 'title': title, 'link': entry.link, 'time': dt_str, 'color': color})
    return news

def fetch_hk01():
    try:
        r = requests.get("https://web-data.api.hk01.com/v2/feed/category/0", headers=HEADERS, timeout=5)
        items = r.json().get('items', [])[:8]
        news = []
        for item in items:
            raw = item.get('data', {})
            dt_str = datetime.datetime.fromtimestamp(raw.get('publishTime'), HK_TZ).strftime('%Y-%m-%d %H:%M')
            news.append({'source': "HK01", 'title': raw.get('title'), 'link': raw.get('publishUrl'), 'time': dt_str, 'color': "#184587"})
        return news
    except: return []

# --- 3. 初始化狀態 ---

if 'selected_links' not in st.session_state:
    st.session_state.selected_links = set()
if 'generated_text' not in st.session_state:
    st.session_state.generated_text = ""

# --- 4. UI 介面 ---

st.title("Tommy Sir 後援會之新聞監察系統")
st.caption(f"目前時間: {datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S')}")

# 生成內容顯示區域
if st.session_state.generated_text:
    with st.expander("📄 已生成的 TXT 內容預覽 (可直接複製)", expanded=True):
        st.text_area("內容:", value=st.session_state.generated_text, height=300)
        if st.button("關閉預覽"):
            st.session_state.generated_text = ""
            st.rerun()

# 側邊欄控制
with st.sidebar:
    st.header("⚙️ 系統控制")
    if st.button("🔄 立即刷新所有新聞"):
        st.cache_data.clear()
        st.rerun()
    
    st.divider()
    st.write(f"目前已選擇: **{len(st.session_state.selected_links)}** 篇")
    
    if st.button("📄 生成 TXT 內容", type="primary"):
        if not st.session_state.selected_links:
            st.warning("請先勾選新聞")
        else:
            with st.spinner("正在整理全文中..."):
                final_txt = ""
                # 這裡需要從快取中比對資料
                # 簡單起見，我們在主迴圈中收集所有當前抓取的新聞
                for item in st.session_state.all_current_news:
                    if item['link'] in st.session_state.selected_links:
                        real_url = resolve_google_url(item['link'])
                        content = fetch_full_article(real_url)
                        final_txt += f"{item['source']}：{item['title']}\n"
                        final_txt += f"[{item['time']}]\n\n"
                        final_txt += f"{content}\n\n"
                        final_txt += f"{real_url}\n\n"
                        final_txt += "Ends\n\n"
                st.session_state.generated_text = final_txt
    
    if st.button("🗑️ 清空所有選擇"):
        st.session_state.selected_links.clear()
        st.session_state.generated_text = ""
        st.rerun()

# --- 5. 新聞抓取與顯示 ---

sources = [
    ("HK01", fetch_hk01, []),
    ("無線新聞", fetch_google_rss, ["news.tvb.com/tc/local", "無線新聞", "#27ae60"]),
    ("Now 新聞", fetch_google_rss, ["news.now.com/home/local", "Now 新聞", "#E65100"]),
]

cols = st.columns(3)
st.session_state.all_current_news = [] # 用於生成時比對

for i, (name, func, args) in enumerate(sources):
    with cols[i % 3]:
        news_items = fetch_news_data(func, *args)
        st.session_state.all_current_news.extend(news_items)
        
        st.markdown(f"<div class='news-source-header'>{name}</div>", unsafe_allow_html=True)
        
        if not news_items:
            st.write("暫無更新")
        else:
            for item in news_items:
                link = item['link']
                is_new = is_new_news(item['time'])
                is_selected = link in st.session_state.selected_links
                
                # UI 排版
                c1, c2 = st.columns([0.15, 0.85])
                with c1:
                    # 勾選框
                    if st.checkbox("", key=f"chk_{link}", value=is_selected):
                        st.session_state.selected_links.add(link)
                    else:
                        st.session_state.selected_links.discard(link)
                
                with c2:
                    new_tag = '<span class="new-badge">NEW!</span>' if is_new else ''
                    text_class = "read-text" if is_selected else ""
                    st.markdown(f"""
                        {new_tag}
                        <a href="{link}" target="_blank" class="{text_class}">
                            <b>{item['title']}</b>
                        </a><br>
                        <small style="color:gray;">{item['time']}</small>
                    """, unsafe_allow_html=True)
