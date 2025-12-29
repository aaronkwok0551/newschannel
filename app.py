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
    /* 修正 HTML 原始碼外洩問題，強制隱藏可能的 Raw Code */
    code { display: none; }
</style>
""", unsafe_allow_html=True)

# 設定時區
HK_TZ = pytz.timezone('Asia/Hong_Kong')
UTC_TZ = pytz.timezone('UTC')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}

# --- 2. 核心功能函式 ---

def get_real_url(url):
    """
    嘗試解析 Google News 的重定向網址，還原成原始網址。
    主要用於生成 TXT 時，因為這需要網路請求，不建議在列表顯示時對每條都做。
    """
    if "news.google.com" not in url:
        return url
    try:
        # allow_redirects=True 會自動跟隨跳轉直到最後的真實網址
        r = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=5)
        return r.url
    except:
        # 如果 HEAD 請求失敗，嘗試 GET
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            return r.url
        except:
            return url

def fetch_full_article(url):
    """ 抓取內文，並在此處確保網址是真實網址 """
    
    # 1. 先把網址還原成真實網址 (針對 Google 連結)
    real_url = get_real_url(url)
    
    try:
        r = requests.get(real_url, headers=HEADERS, timeout=10)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 移除干擾元素
        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'iframe', 'noscript', 'meta', 'svg', 'button']):
            tag.decompose()

        paragraphs = []

        # --- 針對不同網站的特定解析邏輯 ---
        
        # 1. 無線新聞 (TVB)
        if "news.tvb.com" in real_url:
            content_div = soup.find('div', class_='content-node-details') or soup.find('div', class_='desc')
            if content_div: paragraphs = content_div.find_all(['p', 'div'], recursive=False)

        # 2. Now 新聞
        elif "news.now.com" in real_url:
            leading = soup.find('div', class_='newsLeading')
            content = soup.find('div', class_='newsContent')
            if leading: paragraphs.append(leading)
            if content: paragraphs.append(content)

        # 3. 商業電台 (881903)
        elif "881903.com" in real_url:
            content_div = soup.find('div', class_='news-content')
            if content_div: paragraphs = content_div.find_all('p')

        # 4. 香港 01
        elif "hk01.com" in real_url:
            content_div = soup.find('article')
            if content_div: paragraphs = content_div.find_all('p')

        # 5. 通用後備方案
        if not paragraphs:
            main_div = soup.find('div', class_=lambda x: x and ('article' in x.lower() or 'content' in x.lower()))
            if main_div:
                paragraphs = main_div.find_all('p')
            else:
                paragraphs = soup.find_all('p')

        full_text_list = []
        for p in paragraphs:
            text = p.get_text().strip()
            if len(text) > 5 and "請按此" not in text and "原文網址" not in text:
                full_text_list.append(text)
        
        content_text = "\n\n".join(full_text_list)
        if len(content_text) < 20: content_text = "（無法自動提取詳細內文，請點擊連結查看）"
        
        return content_text, real_url # 回傳內文和真實網址

    except Exception as e:
        return f"抓取失敗 ({str(e)})", real_url

def is_new_news(published_time_str):
    try:
        pub_time = datetime.datetime.strptime(published_time_str, '%Y-%m-%d %H:%M')
        pub_time = HK_TZ.localize(pub_time)
        now = datetime.datetime.now(HK_TZ)
        diff = (now - pub_time).total_seconds() / 60
        return 0 <= diff <= 30
    except:
        return False

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
    """
    注意：Google RSS 返回的是跳轉連結。
    為了頁面加載速度，我們在列表頁暫時顯示 Google 連結，
    但在生成 TXT 時會進行還原。
    """
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
    """ 
    直接抓取媒體的 RSS，這樣可以得到真實網址。
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        feed = feedparser.parse(r.content)
        news = []
        for entry in feed.entries[:8]:
            dt_str = ""
            if hasattr(entry, 'published_parsed'):
                dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
                dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
            elif hasattr(entry, 'updated_parsed'): # 部分 RSS 使用 updated
                 dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.updated_parsed), UTC_TZ).astimezone(HK_TZ)
                 dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
            
            link = entry.link
            # Now 新聞特殊處理：如果連結是相對路徑或不完整
            if 'news.now.com' in url and 'http' not in link:
                 # Now RSS 有時會給出 weird 的 link，嘗試修復
                 pass 
            
            news.append({'source': name, 'title': entry.title, 'link': link, 'time': dt_str, 'color': color})
        return news
    except Exception as e:
        return []

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
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 刷新新聞"):
            st.cache_data.clear()
            st.session_state.all_current_news = []
            st.rerun()
    with col_btn2:
        if st.button("🗑️ 清空選擇"):
            st.session_state.selected_links = set()
            st.session_state.generated_text = ""
            st.rerun()

    st.divider()
    st.write(f"已選新聞: **{len(st.session_state.selected_links)}** 篇")

    if st.button("📄 生成 TXT 內容", type="primary", use_container_width=True):
        if not st.session_state.selected_links:
            st.warning("請先在右側勾選新聞！")
        else:
            with st.spinner("正在抓取內文並解析真實網址..."):
                final_txt = ""
                selected_items = [
                    item for item in st.session_state.all_current_news 
                    if item['link'] in st.session_state.selected_links
                ]
                
                count = 1
                total = len(selected_items)
                progress_bar = st.progress(0)

                for idx, item in enumerate(selected_items):
                    # 在這裡同時獲取 內文 和 真實網址
                    content, real_url = fetch_full_article(item['link'])
                    
                    final_txt += f"【新聞 {idx+1}】{item['source']}：{item['title']}\n"
                    final_txt += f"發布時間：{item['time']}\n"
                    final_txt += "-" * 20 + "\n"
                    final_txt += f"{content}\n\n"
                    # 使用還原後的 real_url
                    final_txt += f"連結：{real_url}\n"
                    final_txt += "Ends\n\n" + "="*30 + "\n\n"
                    progress_bar.progress((idx + 1) / total)

                st.session_state.generated_text = final_txt
                progress_bar.empty()

    if st.session_state.generated_text:
        st.markdown("---")
        st.success("✅ 生成完成！連結已還原為原始網址。")
        st.text_area("TXT 內容預覽", value=st.session_state.generated_text, height=600)

# --- 5. 主介面：新聞顯示區 ---

st.title("Tommy Sir 後援會之新聞監察系統")
st.caption(f"最後同步時間: {datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S')}")

# 重點修改：Now 新聞改用 fetch_direct_rss
sources_config = [
    # 第一欄
    [
        ("HK01", "fetch_hk01", []),
        ("香港電台", "fetch_direct_rss", ["https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "香港電台", "#FF9800"]),
    ],
    # 第二欄
    [
        # TVB 沒有官方 RSS，只能用 Google，但在生成 TXT 時我們會還原網址
        ("無線新聞 (TVB)", "fetch_google_rss", ["news.tvb.com/tc/local", "無線新聞", "#27ae60"]),
        ("有線新聞", "fetch_direct_rss", ["https://www.i-cable.com/feed/", "有線新聞", "#c0392b"]),
    ],
    # 第三欄
    [
        # Now 新聞改用官方 RSS，這樣網址就是 news.now.com 了
        ("Now 新聞", "fetch_direct_rss", ["https://news.now.com/home/local/rss.xml", "Now 新聞", "#E65100"]),
        # 商台沒有官方 RSS，只能用 Google
        ("商業電台", "fetch_google_rss", ["881903.com", "商台", "#F1C40F"]),
    ]
]

cols = st.columns(3)
temp_all_news = []

for col_idx, column_sources in enumerate(sources_config):
    with cols[col_idx]:
        for name, func_name, args in column_sources:
            st.markdown(f"<div class='news-source-header'>{name}</div>", unsafe_allow_html=True)
            news_items = fetch_news_data(func_name, *args)
            temp_all_news.extend(news_items)
            
            if not news_items:
                st.info("暫無更新")
            else:
                for item in news_items:
                    link = item['link']
                    is_new = is_new_news(item['time'])
                    is_selected = link in st.session_state.selected_links
                    
                    c1, c2 = st.columns([0.1, 0.9])
                    with c1:
                        if st.checkbox("", key=f"chk_{link}", value=is_selected):
                            st.session_state.selected_links.add(link)
                        else:
                            st.session_state.selected_links.discard(link)
                    
                    with c2:
                        new_tag = '<span class="new-badge">NEW!</span>' if is_new else ''
                        text_style = 'class="read-text"' if is_selected else ""
                        
                        # 這裡使用 HTML 渲染，確保引號和結構正確
                        # 即使列表頁 TVB 顯示的是 google 網址，生成 TXT 時會變成真實網址
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

st.session_state.all_current_news = temp_all_news

