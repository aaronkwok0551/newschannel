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

# --- 1. 頁面與自定義樣式 ---
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
    @keyframes blinker { 50% { opacity: 0; } }
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
        margin-top: 5px; 
        margin-bottom: 15px;
        padding-bottom: 5px;
        border-bottom: 2px solid #ddd;
    }
    a { text-decoration: none; color: #2980b9; transition: 0.3s; }
    a:hover { color: #e74c3c; }
    
    /* 調整列的對齊 */
    div[data-testid="column"] {
        background-color: #ffffff;
        padding: 10px;
        border-radius: 5px;
    }
</style>
""", unsafe_allow_html=True)

# 設定時區
HK_TZ = pytz.timezone('Asia/Hong_Kong')
UTC_TZ = pytz.timezone('UTC')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
}

# --- 2. 核心功能函式 (針對特定網站優化) ---

def fetch_full_article(url):
    """ 針對不同平台優化抓取邏輯 """
    # 預處理 Google News 連結
    if "news.google.com" in url:
        url = resolve_google_url(url)

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = 'utf-8' # 大部分港媒是 utf-8
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 移除干擾元素
        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'iframe', 'noscript', 'meta']):
            tag.decompose()

        paragraphs = []

        # --- 針對不同網站的特定解析邏輯 ---
        
        # 1. 無線新聞 (TVB)
        if "news.tvb.com" in url:
            # TVB 通常在 div class="content-node-details" 或 generic content 中
            content_div = soup.find('div', class_='content-node-details')
            if not content_div:
                content_div = soup.find('div', class_='desc')
            if content_div:
                paragraphs = content_div.find_all(['p', 'div'], recursive=False)

        # 2. Now 新聞
        elif "news.now.com" in url:
            # Now 新聞通常結構： .newsLeading (導語) + .newsContent (內文)
            leading = soup.find('div', class_='newsLeading')
            content = soup.find('div', class_='newsContent')
            if leading: paragraphs.append(leading)
            if content: paragraphs.append(content)

        # 3. 商業電台 (881903)
        elif "881903.com" in url:
            # 商台結構較亂，通常在 div.news-content
            content_div = soup.find('div', class_='news-content')
            if content_div:
                paragraphs = content_div.find_all('p')

        # 4. 香港 01
        elif "hk01.com" in url:
            content_div = soup.find('article')
            if content_div:
                paragraphs = content_div.find_all('p')

        # 5. 通用後備方案 (Fallback)
        if not paragraphs:
            # 尋找含有大量文字的 div
            main_div = soup.find('div', class_=lambda x: x and ('article' in x.lower() or 'content' in x.lower()))
            if main_div:
                paragraphs = main_div.find_all('p')
            else:
                paragraphs = soup.find_all('p')

        # 提取文字
        full_text_list = []
        for p in paragraphs:
            text = p.get_text().strip()
            if len(text) > 5 and "請按此" not in text and "原文網址" not in text:
                full_text_list.append(text)
        
        full_text = "\n\n".join(full_text_list)
        
        if len(full_text) < 30:
            return f"內容抓取過短，請直接查看網頁：{url}"
        
        return full_text

    except Exception as e:
        return f"抓取失敗 ({str(e)}) - 請手動查看: {url}"

def resolve_google_url(url):
    """ 解析 Google Redirect URL """
    try:
        # allow_redirects=True 會自動跳轉到最終網址
        r = requests.get(url, headers=HEADERS, timeout=5, stream=True)
        return r.url
    except:
        return url

def is_new_news(published_time_str):
    try:
        pub_time = datetime.datetime.strptime(published_time_str, '%Y-%m-%d %H:%M')
        pub_time = HK_TZ.localize(pub_time)
        now = datetime.datetime.now(HK_TZ)
        diff = (now - pub_time).total_seconds() / 60
        return 0 <= diff <= 30 # 放寬到 30 分鐘內
    except:
        return False

# 快取數據抓取
@st.cache_data(ttl=60)
def fetch_news_data(func_name, *args):
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
        title = entry.title.rsplit(" - ", 1)[0]
        dt_str = ""
        if hasattr(entry, 'published_parsed'):
            dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
            dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
        news.append({'source': site_name, 'title': title, 'link': entry.link, 'time': dt_str, 'color': color})
    return news

def fetch_direct_rss(url, name, color):
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        feed = feedparser.parse(r.content)
        news = []
        for entry in feed.entries[:8]:
            dt_str = ""
            if hasattr(entry, 'published_parsed'):
                dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
                dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
            link = entry.link
            # Now 新聞的 RSS 連結有時需要補全
            if 'news.now.com' in url and 'http' not in link:
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

# --- 4. 側邊欄控制與顯示 ---

with st.sidebar:
    st.title("⚙️ 控制台")
    
    # 按鈕區 (放在最上方)
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if st.button("🔄 刷新新聞"):
            st.cache_data.clear()
            st.session_state.all_current_news = []
            st.rerun()

    with col_btn2:
        if st.button("🗑️ 清空選擇"):
            st.session_state.selected_links = set() # 直接重置 Set
            st.session_state.generated_text = ""
            st.rerun()

    st.divider()
    
    # 統計
    st.write(f"已選新聞: **{len(st.session_state.selected_links)}** 篇")

    # 生成按鈕
    if st.button("📄 生成 TXT 內容", type="primary", use_container_width=True):
        if not st.session_state.selected_links:
            st.warning("請先在右側勾選新聞！")
        else:
            with st.spinner("正在前往各大網站抓取內文..."):
                final_txt = ""
                # 從緩存的新聞列表中過濾
                selected_items = [
                    item for item in st.session_state.all_current_news 
                    if item['link'] in st.session_state.selected_links
                ]
                
                count = 1
                total = len(selected_items)
                progress_bar = st.progress(0)

                for idx, item in enumerate(selected_items):
                    content = fetch_full_article(item['link'])
                    final_txt += f"【新聞 {idx+1}】{item['source']}：{item['title']}\n"
                    final_txt += f"發布時間：{item['time']}\n"
                    final_txt += "-" * 20 + "\n"
                    final_txt += f"{content}\n\n"
                    final_txt += f"連結：{item['link']}\n"
                    final_txt += "Ends\n\n" + "="*30 + "\n\n"
                    progress_bar.progress((idx + 1) / total)

                st.session_state.generated_text = final_txt
                progress_bar.empty()

    # --- 生成結果顯示區 (移至 Sidebar) ---
    if st.session_state.generated_text:
        st.markdown("---")
        st.success("✅ 生成完成！")
        st.text_area("TXT 內容預覽 (Ctrl+A 全選複製)", 
                     value=st.session_state.generated_text, 
                     height=600)

# --- 5. 主介面：新聞顯示區 (對齊優化版) ---

st.title("Tommy Sir 後援會之新聞監察系統")
st.caption(f"最後同步時間: {datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S')} (每 60 秒自動更新)")

# 定義新聞源配置
# 注意：Now 新聞改用 fetch_direct_rss 嘗試更穩定抓取，如果 RSS 失敗會自動退回
sources_config = [
    # 第一欄
    [
        ("HK01", "fetch_hk01", []),
        ("香港電台", "fetch_direct_rss", ["https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "香港電台", "#FF9800"]),
    ],
    # 第二欄
    [
        ("無線新聞 (TVB)", "fetch_google_rss", ["news.tvb.com/tc/local", "無線新聞", "#27ae60"]),
        ("有線新聞", "fetch_direct_rss", ["https://www.i-cable.com/feed/", "有線新聞", "#c0392b"]),
    ],
    # 第三欄
    [
        ("Now 新聞", "fetch_google_rss", ["news.now.com/home/local", "Now 新聞", "#E65100"]),
        ("商業電台", "fetch_google_rss", ["881903.com", "商台", "#F1C40F"]),
    ]
]

# 創建固定的三欄佈局 (解決鋸齒問題)
cols = st.columns(3)
temp_all_news = []

# 遍歷三欄配置
for col_idx, column_sources in enumerate(sources_config):
    with cols[col_idx]:
        for name, func_name, args in column_sources:
            # 顯示來源標題
            st.markdown(f"<div class='news-source-header'>{name}</div>", unsafe_allow_html=True)
            
            # 抓取數據
            news_items = fetch_news_data(func_name, *args)
            temp_all_news.extend(news_items)
            
            if not news_items:
                st.info("暫無更新")
            else:
                for item in news_items:
                    link = item['link']
                    is_new = is_new_news(item['time'])
                    
                    # 確保按鈕狀態正確
                    is_selected = link in st.session_state.selected_links
                    
                    # 佈局：Checkbox + 標題
                    c1, c2 = st.columns([0.1, 0.9])
                    with c1:
                        # 這裡的關鍵是 key 必須唯一，且狀態要跟 session_state 同步
                        checked = st.checkbox(
                            "", 
                            key=f"chk_{link}", 
                            value=is_selected
                        )
                        # 更新狀態邏輯
                        if checked:
                            st.session_state.selected_links.add(link)
                        else:
                            st.session_state.selected_links.discard(link)
                            
                    with c2:
                        new_tag = '<span class="new-badge">NEW!</span>' if is_new else ''
                        # 根據是否選中改變文字樣式
                        text_style = 'class="read-text"' if is_selected else ""
                        
                        st.markdown(f"""
                            <div style="line-height:1.4; margin-bottom:10px;">
                                {new_tag}
                                <a href="{link}" target="_blank" {text_style}>
                                    {item['title']}
                                </a>
                                <br>
                                <span style="font-size:0.8em; color:#888;">{item['time']}</span>
                            </div>
                        """, unsafe_allow_html=True)

# 更新所有新聞緩存
st.session_state.all_current_news = temp_all_news
