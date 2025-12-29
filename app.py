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

# 設定預設編碼以防止中文亂碼
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="HK News Hub",
    page_icon="📰",
    layout="wide"
)

# --- 設定自動刷新 (每 60 秒 = 60000 毫秒) ---
count = st_autorefresh(interval=60 * 1000, limit=None, key="news_autoupdate")

# --- 自訂 CSS (優化並排顯示與 Checkbox) ---
st.markdown("""
<style>
    .stCheckbox { margin-bottom: 0px; }
    /* 來源標題樣式 */
    .news-source-header { 
        font-size: 1.1em; 
        font-weight: bold; 
        color: #2c3e50; 
        margin-top: 15px; 
        margin-bottom: 10px;
        padding-bottom: 5px;
        border-bottom: 2px solid #eee;
    }
    /* 連結樣式 */
    a { text-decoration: none; color: #2980b9; }
    a:hover { text-decoration: underline; color: #e74c3c; }
    
    /* 調整 Checkbox 與文字對齊 */
    div[data-testid="column"] { display: flex; align-items: start; }
    
    /* 微調容器樣式 */
    div.block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

# 設定時區
HK_TZ = pytz.timezone('Asia/Hong_Kong')
UTC_TZ = pytz.timezone('UTC')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

# --- 2. 核心功能函式 ---

def resolve_google_url(url):
    """還原 Google News 真實連結"""
    if "news.google.com" not in url:
        return url
    try:
        # 使用 HEAD 請求快速獲取真實網址
        r = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=5)
        return r.url
    except:
        return url

@st.cache_data(ttl=60)
def fetch_via_google_news(site_domain, site_name, color, query_suffix=""):
    """Google News 代理抓取"""
    query = f"site:{site_domain} {query_suffix}".strip()
    encoded_query = urllib.parse.quote(query)
    # when:1d 限制為過去 24 小時
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    
    try:
        feed = feedparser.parse(rss_url)
        news_list = []
        for entry in feed.entries[:10]: # 取前 10 條
            # 移除 Google News 標題後面的來源後綴 (例如 " - Source Name")
            title = entry.title.rsplit(" - ", 1)[0] if " - " in entry.title else entry.title
            
            dt_str = ""
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
                    dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
                except:
                    dt_str = "最新"

            summary = entry.get('summary', '') or entry.get('description', '無摘要內容')
            soup = BeautifulSoup(summary, "html.parser")
            clean_summary = soup.get_text().strip()

            news_list.append({
                'source': site_name,
                'title': title,
                'link': entry.link,
                'time': dt_str,
                'content': clean_summary,
                'color': color
            })
        return news_list
    except:
        return []

@st.cache_data(ttl=60)
def fetch_hk01_api():
    """HK01 API"""
    try:
        url = "https://web-data.api.hk01.com/v2/feed/category/0"
        r = requests.get(url, headers=HEADERS, timeout=5)
        items = r.json().get('items', [])[:10]
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
                'content': raw.get('description') or "無摘要內容",
                'color': "#184587"
            })
        return news_list
    except:
        return fetch_via_google_news("hk01.com", "HK01", "#184587")

@st.cache_data(ttl=60)
def fetch_direct_rss(url, name, color):
    """直接 RSS 抓取"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        feed = feedparser.parse(r.content)
        news_list = []
        for entry in feed.entries[:10]:
            dt_str = ""
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
                    dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
                except:
                    dt_str = "最新"
            
            summary = entry.get('summary', '') or entry.get('description', '無摘要內容')
            soup = BeautifulSoup(summary, "html.parser")
            clean_summary = soup.get_text().strip()

            link = entry.link
            if 'news.now.com' in url and 'news.now.com' not in link:
                link = f"https://news.now.com{link}"

            news_list.append({
                'source': name,
                'title': entry.title,
                'link': link,
                'time': dt_str,
                'content': clean_summary,
                'color': color
            })
        return news_list
    except:
        return []

# --- 3. 主程式介面 ---

st.title("🇭🇰 香港即時新聞中心")
current_time = datetime.datetime.now(HK_TZ).strftime('%H:%M:%S')
st.caption(f"自動更新中 (每 60 秒) | 最後更新: {current_time}")

# 初始化 Session State (用來記憶勾選狀態)
if 'selected_links' not in st.session_state:
    st.session_state.selected_links = set()

# 定義新聞來源
sources = [
    {"func": fetch_hk01_api, "args": [], "name": "HK01", "color": "#184587"},
    {"func": fetch_via_google_news, "args": ["news.tvb.com/tc/local", "無線新聞", "#27ae60"], "name": "無線新聞", "color": "#27ae60"},
    {"func": fetch_via_google_news, "args": ["news.now.com/home/local", "Now新聞", "#E65100"], "name": "Now 新聞", "color": "#E65100"},
    {"func": fetch_direct_rss, "args": ["https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "香港電台", "#FF9800"], "name": "香港電台", "color": "#FF9800"},
    {"func": fetch_direct_rss, "args": ["https://www.i-cable.com/feed/", "有線新聞", "#c0392b"], "name": "有線新聞", "color": "#c0392b"},
    {"func": fetch_via_google_news, "args": ["881903.com", "商台", "#F1C40F"], "name": "商台 881903", "color": "#F1C40F"},
]

# 手動刷新按鈕
if st.button("🔄 立即刷新"):
    st.cache_data.clear()
    st.rerun()

# --- 4. 顯示新聞內容 (並排版面 Grid Layout) ---
all_news_items = [] # 用來收集所有新聞資料，給下載功能使用

# 建立 3 個並排欄位
cols = st.columns(3)

# 遍歷所有來源
for i, source_conf in enumerate(sources):
    # 決定這個來源要放在哪一欄 (0, 1, 2 循環)
    col = cols[i % 3]
    
    with col:
        # 執行抓取函數
        if source_conf["func"] == fetch_hk01_api:
            items = source_conf["func"]()
        else:
            items = source_conf["func"](*source_conf["args"])
            
        # 顯示標題
        st.markdown(f"<div class='news-source-header' style='border-left: 5px solid {source_conf['color']}; padding-left: 10px;'>{source_conf['name']}</div>", unsafe_allow_html=True)
        
        if not items:
            st.info("暫無資料")
        else:
            # 顯示該來源的所有新聞
            for item in items:
                all_news_items.append(item) # 存入大列表
                
                # 使用新聞連結作為唯一 ID (避免順序變動導致勾選錯誤)
                unique_key = item['link']
                
                # 使用兩欄佈局：左邊是 Checkbox，右邊是新聞內容
                sub_col1, sub_col2 = st.columns([0.1, 0.9])
                
                with sub_col1:
                    # 檢查是否已被勾選
                    is_checked = unique_key in st.session_state.selected_links
                    
                    # 定義 Callback 函數來更新狀態
                    def update_selection(key=unique_key):
                        if key in st.session_state.selected_links:
                            st.session_state.selected_links.remove(key)
                        else:
                            st.session_state.selected_links.add(key)

                    # 顯示 Checkbox (無標籤)
                    st.checkbox("", key=f"chk_{unique_key}", value=is_checked, on_change=update_selection)
                
                with sub_col2:
                    # 顯示新聞標題、連結與時間
                    st.markdown(
                        f"**[{item['title']}]({item['link']})** <br><span style='font-size:0.8em; color:#888;'>{item['time']}</span>", 
                        unsafe_allow_html=True
                    )

# --- 5. 側邊欄：下載功能 ---
with st.sidebar:
    st.header("🗃️ 檔案生成區")
    count = len(st.session_state.selected_links)
    st.write(f"目前已選擇： **{count}** 篇新聞")
    
    if count > 0:
        if st.button("📄 生成 TXT 檔案"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            output_text = ""
            processed_count = 0
            
            # 從所有新聞中找出被勾選的項目
            selected_items_data = [item for item in all_news_items if item['link'] in st.session_state.selected_links]
            
            # 開始生成內容
            for item in selected_items_data:
                processed_count += 1
                status_text.text(f"解析連結中 ({processed_count}/{len(selected_items_data)}): {item['source']}...")
                progress_bar.progress(processed_count / len(selected_items_data))
                
                # 如果是 Google News 連結，嘗試還原真實網址
                real_link = item['link']
                if "news.google.com" in real_link:
                    real_link = resolve_google_url(real_link)
                
                # 組合 TXT 格式 (符合您的要求)
                output_text += f"{item['source']}：{item['title']}\n"
                output_text += f"[{item['time']}]\n\n"
                output_text += f"{item['content']}\n\n"
                output_text += f"{real_link}\n\n"
                output_text += "Ends\n\n"
                
            status_text.success("✅ 生成完成！")
            progress_bar.empty()
            
            # 建立下載按鈕
            current_time_str = datetime.datetime.now(HK_TZ).strftime('%Y%m%d_%H%M')
            st.download_button(
                label="📥 下載 .txt 檔案",
                data=output_text,
                file_name=f"news_digest_{current_time_str}.txt",
                mime="text/plain"
            )
    else:
        st.info("請在右側勾選新聞以生成摘要。")
        if st.button("清除所有選擇"):
            st.session_state.selected_links.clear()
            st.rerun()
