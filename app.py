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

# --- 1. 頁面與樣式設定 ---
st.set_page_config(
    page_title="HK News Hub",
    page_icon="📰",
    layout="wide"
)

# 自動刷新 (每 60 秒)
st_autorefresh(interval=60 * 1000, limit=None, key="news_autoupdate")

st.markdown("""
<style>
    .stCheckbox { margin-bottom: 0px; }
    .news-source-header { 
        font-size: 1.1em; 
        font-weight: bold; 
        color: #2c3e50; 
        margin-top: 15px; 
        margin-bottom: 10px;
        padding-bottom: 5px;
        border-bottom: 2px solid #eee;
    }
    a { text-decoration: none; color: #2980b9; }
    div[data-testid="column"] { display: flex; align-items: start; }
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
    """ 進入網頁抓取完整的正文內容 """
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 抓取多個 <p> 標籤並組合
        paragraphs = soup.find_all('p')
        if not paragraphs:
            return "無法抓取全文，請點擊連結查看。"
            
        full_text = "\n".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 10])
        return full_text if len(full_text) > 20 else "內容過短或抓取受限。"
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

@st.cache_data(ttl=60)
def fetch_via_google_news(site_domain, site_name, color, query_suffix=""):
    query = f"site:{site_domain} {query_suffix}".strip()
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    
    try:
        feed = feedparser.parse(rss_url)
        news_list = []
        for entry in feed.entries[:8]:
            title = entry.title.rsplit(" - ", 1)[0] if " - " in entry.title else entry.title
            dt_str = ""
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
                    dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
                except:
                    dt_str = "最新"

            news_list.append({
                'source': site_name,
                'title': title,
                'link': entry.link,
                'time': dt_str,
                'color': color
            })
        return news_list
    except:
        return []

@st.cache_data(ttl=60)
def fetch_hk01_api():
    try:
        url = "https://web-data.api.hk01.com/v2/feed/category/0"
        r = requests.get(url, headers=HEADERS, timeout=5)
        items = r.json().get('items', [])[:8]
        news_list = []
        for item in items:
            raw = item.get('data', {})
            ts = raw.get('publishTime')
            dt_str = datetime.datetime.fromtimestamp(ts, HK_TZ).strftime('%Y-%m-%d %H:%M') if ts else ""
            news_list.append({
                'source': "HK01",
                'title': raw.get('title'),
                'link': raw.get('publishUrl'),
                'time': dt_str,
                'color': "#184587"
            })
        return news_list
    except:
        return fetch_via_google_news("hk01.com", "HK01", "#184587")

@st.cache_data(ttl=60)
def fetch_direct_rss(url, name, color):
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        feed = feedparser.parse(r.content)
        news_list = []
        for entry in feed.entries[:8]:
            dt_str = ""
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
                    dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
                except:
                    dt_str = "最新"
            link = entry.link
            if 'news.now.com' in url and 'news.now.com' not in link:
                link = f"https://news.now.com{link}"
            news_list.append({
                'source': name,
                'title': entry.title,
                'link': link,
                'time': dt_str,
                'color': color
            })
        return news_list
    except:
        return []

# --- 3. 主程式邏輯 ---

st.title("Tommy Sir 後援會之新聞監察系統")
current_time = datetime.datetime.now(HK_TZ).strftime('%H:%M:%S')
st.caption(f"最後更新: {current_time}")

if 'selected_links' not in st.session_state:
    st.session_state.selected_links = set()
if 'generated_output' not in st.session_state:
    st.session_state.generated_output = ""

sources = [
    {"func": fetch_hk01_api, "args": [], "name": "HK01", "color": "#184587"},
    {"func": fetch_via_google_news, "args": ["news.tvb.com/tc/local", "無線新聞", "#27ae60"], "name": "無線新聞", "color": "#27ae60"},
    {"func": fetch_via_google_news, "args": ["news.now.com/home/local", "Now新聞", "#E65100"], "name": "Now 新聞", "color": "#E65100"},
    {"func": fetch_direct_rss, "args": ["https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "香港電台", "#FF9800"], "name": "香港電台", "color": "#FF9800"},
    {"func": fetch_direct_rss, "args": ["https://www.i-cable.com/feed/", "有線新聞", "#c0392b"], "name": "有線新聞", "color": "#c0392b"},
    {"func": fetch_via_google_news, "args": ["881903.com", "商台", "#F1C40F"], "name": "商台 881903", "color": "#F1C40F"},
]

# 頂部控制
t_col1, t_col2 = st.columns([1, 5])
with t_col1:
    if st.button("🔄 立即刷新"):
        st.cache_data.clear()
        st.session_state.generated_output = ""
        st.rerun()

# 顯示並排新聞
cols = st.columns(3)
all_news_items = []

for i, source_conf in enumerate(sources):
    col = cols[i % 3]
    with col:
        if source_conf["func"] == fetch_hk01_api:
            items = source_conf["func"]()
        else:
            items = source_conf["func"](*source_conf["args"])
        
        st.markdown(f"<div class='news-source-header' style='border-left: 5px solid {source_conf['color']}; padding-left: 10px;'>{source_conf['name']}</div>", unsafe_allow_html=True)
        
        if not items:
            st.info("暫無資料")
        else:
            for item in items:
                all_news_items.append(item)
                unique_key = item['link']
                sub_col1, sub_col2 = st.columns([0.15, 0.85])
                with sub_col1:
                    is_checked = unique_key in st.session_state.selected_links
                    def on_change(key=unique_key):
                        if key in st.session_state.selected_links:
                            st.session_state.selected_links.remove(key)
                        else:
                            st.session_state.selected_links.add(key)
                        st.session_state.generated_output = ""
                    st.checkbox("", key=f"chk_{unique_key}", value=is_checked, on_change=on_change)
                with sub_col2:
                    st.markdown(f"**[{item['title']}]({item['link']})**<br><span style='font-size:0.8em; color:#888;'>{item['time']}</span>", unsafe_allow_html=True)

# 側邊欄控制與預覽
with st.sidebar:
    st.header("🗃️ 生成區域")
    count = len(st.session_state.selected_links)
    st.write(f"目前已選擇： **{count}** 篇")
    
    if count > 0:
        if st.button("📄 顯示生成內容"):
            with st.spinner("正在抓取全文並解析連結..."):
                output_text = ""
                selected_data = [item for item in all_news_items if item['link'] in st.session_state.selected_links]
                
                for item in selected_data:
                    real_link = resolve_google_url(item['link'])
                    # 抓取全文
                    full_content = fetch_full_article(real_link)
                    
                    output_text += f"{item['source']}：{item['title']}\n"
                    output_text += f"[{item['time']}]\n\n"
                    output_text += f"{full_content}\n\n"
                    output_text += f"{real_link}\n\n"
                    output_text += "Ends\n\n"
                
                st.session_state.generated_output = output_text
        
        if st.button("🗑️ 清空選擇"):
            st.session_state.selected_links.clear()
            st.session_state.generated_output = ""
            st.rerun()

# 顯示生成結果在主畫面上
if st.session_state.generated_output:
    st.divider()
    st.subheader("📝 生成內容預覽")
    st.text_area("您可以直接複製下方內容：", value=st.session_state.generated_output, height=400)
    st.download_button("📥 仍然下載為 TXT", data=st.session_state.generated_output, file_name=f"news_digest_{datetime.datetime.now(HK_TZ).strftime('%Y%m%d_%H%M')}.txt")

