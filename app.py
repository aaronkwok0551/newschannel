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
        font-size: 0.8em;
    }
    .read-text {
        color: #a0a0a0 !important;
        text-decoration: none;
        font-weight: normal !important;
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
    a { text-decoration: none; color: #2980b9; transition: 0.3s; }
    a:hover { color: #e74c3c; }
    div[data-testid="column"] { display: flex; align-items: start; }
    .generated-box {
        background-color: #f8fafc;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #e2e8f0;
        margin-bottom: 20px;
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
    """ 抓取完整的正文內容，針對不同平台優化 """
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 移除不必要的元素
        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'iframe']):
            tag.decompose()

        # 嘗試抓取正文區域 (針對 TVB/Now/HK01 等常見結構)
        # 1. 優先嘗試常見的文章容器
        content_area = soup.find('div', class_=lambda x: x and ('article' in x.lower() or 'content' in x.lower() or 'news-text' in x.lower()))
        
        if content_area:
            paragraphs = content_area.find_all(['p', 'div'], recursive=False)
        else:
            paragraphs = soup.find_all('p')

        if not paragraphs:
            return "無法自動提取全文內容，請點擊連結查看網頁版。"
            
        full_text = "\n".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 10])
        return full_text if len(full_text) > 30 else "抓取內容過短，可能受限於網頁權限或動態載入。"
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
        return 0 <= diff <= 15
    except:
        return False

@st.cache_data(ttl=60)
def fetch_news_data(func_name, *args):
    """ 集中處理抓取數據並快取 """
    if func_name == "fetch_hk01":
        return fetch_hk01()
    elif func_name == "fetch_google_rss":
        return fetch_google_rss(*args)
    elif func_name == "fetch_direct_rss":
        return fetch_direct_rss(*args)
    return []

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

def fetch_direct_rss(url, name, color):
    try:
        r = requests.get(url, headers=HEADERS, timeout=5)
        feed = feedparser.parse(r.content)
        news = []
        for entry in feed.entries[:8]:
            dt_str = ""
            if hasattr(entry, 'published_parsed'):
                dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
                dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
            link = entry.link
            # 修正 Now 連結
            if 'news.now.com' in url and 'news.now.com' not in link:
                link = f"https://news.now.com{link}"
            news.append({'source': name, 'title': entry.title, 'link': link, 'time': dt_str, 'color': color})
        return news
    except: return []

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
if 'all_current_news' not in st.session_state:
    st.session_state.all_current_news = []

# --- 4. 側邊欄控制 ---

with st.sidebar:
    st.header("⚙️ 系統控制")
    if st.button("🔄 立即刷新所有新聞"):
        st.cache_data.clear()
        st.session_state.all_current_news = []
        st.rerun()
    
    st.divider()
    st.write(f"目前已選擇: **{len(st.session_state.selected_links)}** 篇")
    
    if st.button("📄 生成 TXT 內容", type="primary"):
        if not st.session_state.selected_links:
            st.warning("請先勾選新聞")
        else:
            with st.spinner("正在逐一抓取全文中，請稍候..."):
                final_txt = ""
                # 使用存儲在 session_state 中的數據進行生成
                selected_news = [item for item in st.session_state.all_current_news if item['link'] in st.session_state.selected_links]
                
                for item in selected_news:
                    real_url = resolve_google_url(item['link'])
                    content = fetch_full_article(real_url)
                    final_txt += f"{item['source']}：{item['title']}\n"
                    final_txt += f"[{item['time']}]\n\n"
                    final_txt += f"{content}\n\n"
                    final_txt += f"{real_url}\n\n"
                    final_txt += "Ends\n\n"
                st.session_state.generated_text = final_txt
    
    if st.button("🗑️ 取消所有選擇 / 清空"):
        st.session_state.selected_links.clear()
        st.session_state.generated_text = ""
        st.rerun()

# --- 5. UI 介面與內容顯示 ---

st.title("Tommy Sir 後援會之新聞監察系統")
st.caption(f"最後同步時間: {datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S')}")

# 生成內容顯示區域 (直接顯示在主網頁)
if st.session_state.generated_text:
    st.markdown("### 📄 生成內容預覽")
    st.text_area("您可以直接複製下方內容：", value=st.session_state.generated_text, height=450)
    if st.button("❌ 關閉預覽"):
        st.session_state.generated_text = ""
        st.rerun()
    st.divider()

# 新聞抓取來源配置 (完整 6 個平台)
sources_config = [
    ("HK01", "fetch_hk01", []),
    ("無線新聞", "fetch_google_rss", ["news.tvb.com/tc/local", "無線新聞", "#27ae60"]),
    ("Now 新聞", "fetch_google_rss", ["news.now.com/home/local", "Now 新聞", "#E65100"]),
    ("香港電台", "fetch_direct_rss", ["https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "香港電台", "#FF9800"]),
    ("有線新聞", "fetch_direct_rss", ["https://www.i-cable.com/feed/", "有線新聞", "#c0392b"]),
    ("商台 881903", "fetch_google_rss", ["881903.com", "商台", "#F1C40F"]),
]

cols = st.columns(3)
temp_all_news = [] # 暫存本次抓取的數據

for i, (name, func_name, args) in enumerate(sources_config):
    with cols[i % 3]:
        news_items = fetch_news_data(func_name, *args)
        temp_all_news.extend(news_items)
        
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
                    text_style = 'class="read-text"' if is_selected else ""
                    st.markdown(f"""
                        {new_tag}
                        <a href="{link}" target="_blank" {text_style}>
                            <b>{item['title']}</b>
                        </a><br>
                        <small style="color:gray;">{item['time']}</small>
                    """, unsafe_allow_html=True)

# 將本次抓取的數據存入 session_state，供 sidebar 生成按鈕使用
st.session_state.all_current_news = temp_all_news
