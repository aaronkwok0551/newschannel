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
import concurrent.futures
import re
import html
import urllib3

# 忽略 SSL 警告 (針對 verify=False)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 設定預設編碼
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="Tommy Sir 後援會之新聞監察系統",
    page_icon="📰",
    layout="wide"
)

# 自動刷新 (每 60 秒)
st_autorefresh(interval=60 * 1000, limit=None, key="news_autoupdate")

# --- CSS 樣式 ---
st.markdown("""
<style>
    .stApp { background-color: #f8fafc; }
    
    /* 1. 防止更新時畫面變淡 */
    .stApp, div[data-testid="stAppViewContainer"] {
        opacity: 1 !important;
        transition: none !important;
    }
    
    /* 2. 隱藏頂部彩虹載入條與 Status Widget */
    header .stDecoration { display: none !important; }
    div[data-testid="stStatusWidget"] { visibility: hidden; }

    div.block-container { min-height: 100vh; }
    div[data-testid="stAppViewContainer"] { overflow-y: scroll; }
    
    /* 閃爍特效 */
    @keyframes blinker { 50% { opacity: 0.4; } }
    .new-badge {
        color: #ef4444;
        font-weight: 800;
        animation: blinker 1.5s ease-in-out infinite;
        margin-right: 5px;
        font-size: 0.75em;
        display: inline-block;
        vertical-align: middle;
    }

    .read-text { color: #9ca3af !important; font-weight: normal !important; text-decoration: none !important; }
    a { text-decoration: none; color: #334155; font-weight: 600; transition: 0.2s; font-size: 0.95em; line-height: 1.4; }
    a:hover { color: #2563eb; }
    
    /* --- 核心優化：解決「穿孔」問題 --- */
    /* 1. 精準鎖定標題的外層容器 */
    div[data-testid="stVerticalBlock"] > div.element-container:has(.news-source-header) {
        position: sticky !important;
        top: -1px !important; /* 稍微往上一點點確保不留縫隙 */
        z-index: 1000 !important; /* 超高層級 */
        background-color: #ffffff !important; /* 確保不透明 */
        width: 100% !important;
        padding-top: 0px !important;
        margin-top: -1px !important; /* 封死 Streamlit 預設的 gap 間隙 */
    }

    /* 2. 標題本身的樣式，增加底部邊框區分感 */
    .news-source-header { 
        font-size: 1rem; 
        font-weight: bold; 
        color: #1e293b; 
        padding: 12px 10px; 
        margin: 0; 
        display: flex; 
        justify-content: space-between; 
        align-items: center;
        background-color: white !important;
        border-bottom: 2px solid #f1f5f9;
        box-shadow: 0 2px 4px -2px rgba(0,0,0,0.1); /* 增加陰影防止看起來像穿孔 */
    }
    
    .status-badge { font-size: 0.65em; padding: 2px 8px; border-radius: 12px; font-weight: 500; background-color: #f1f5f9; color: #64748b; }
    
    .header-btn {
        background: transparent;
        border: 1px solid #e2e8f0;
        color: #64748b;
        cursor: pointer;
        font-size: 0.7em;
        padding: 2px 8px;
        border-radius: 4px;
        margin-left: 8px;
    }
    
    .news-item-row { padding: 8px 5px; border-bottom: 1px solid #f1f5f9; background-color: white; }
    .news-item-row:last-child { border-bottom: none; }
    .news-time { font-size: 0.8em; color: #94a3b8; margin-top: 4px; display: block; }
    
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        border-top-left-radius: 0 !important;
        border-top-right-radius: 0 !important;
        border-color: #e2e8f0 !important;
        background-color: white;
    }

    @media (max-width: 768px) {
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalScrollArea"] {
            height: 450px !important;
        }
    }
</style>
""", unsafe_allow_html=True)

# 設定時區
HK_TZ = pytz.timezone('Asia/Hong_Kong')
UTC_TZ = pytz.timezone('UTC')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Connection': 'keep-alive'
}

# --- 2. 核心功能函式 ---

def chunked(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]

def resolve_google_url(url):
    if "news.google.com" not in url: return url
    try:
        r = requests.get(url, allow_redirects=True, timeout=15, headers=HEADERS)
        if "news.google.com" not in r.url: return r.url
        soup = BeautifulSoup(r.text, 'html.parser')
        link_with_data = soup.find('a', attrs={'data-n-url': True})
        if link_with_data: return link_with_data['data-n-url']
        return r.url 
    except: return url

def fetch_full_article(url, summary_fallback=""):
    try:
        session = requests.Session()
        r = session.get(url, timeout=20, headers=HEADERS)
        r.encoding = r.apparent_encoding 
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 移除干擾元素
        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside']): tag.decompose()

        content_area = soup.find('div', class_=re.compile(r'content|article|body|news-text|post-body', re.I))
        paragraphs = content_area.find_all('p') if content_area else soup.find_all('p')
        
        clean_text = [p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 10]
        return "\n\n".join(clean_text) if clean_text else summary_fallback, None
    except Exception as e:
        return summary_fallback, None

def is_new_news(timestamp):
    if not timestamp: return False
    try:
        now = datetime.datetime.now(HK_TZ)
        diff = (now - timestamp.astimezone(HK_TZ)).total_seconds() / 60
        return 0 <= diff <= 30
    except: return False

# --- 3. 抓取邏輯 ---

@st.cache_data(ttl=60, show_spinner=False)
def fetch_google_proxy(site_query, site_name, color, limit=100):
    query = urllib.parse.quote(site_query)
    rss_url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    try:
        feed = feedparser.parse(rss_url)
        news_list = []
        now = datetime.datetime.now(HK_TZ)
        for entry in feed.entries: 
            dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
            if (now - dt_obj).total_seconds() > 86400 * 7: continue
            news_list.append({
                'source': site_name, 'title': entry.title.rsplit(" - ", 1)[0], 'link': entry.link, 
                'time_str': dt_obj.strftime('%Y-%m-%d %H:%M'), 'timestamp': dt_obj, 'color': color, 'method': 'Proxy'
            })
        return sorted(news_list, key=lambda x: x['timestamp'], reverse=True)[:limit]
    except: return []

@st.cache_data(ttl=60, show_spinner=False)
def fetch_single_source(config, limit=100):
    data = []
    now = datetime.datetime.now(HK_TZ)
    try:
        if config['type'] == 'json_wenweipo':
             r = requests.get(config['url'], headers=HEADERS, timeout=30, verify=False)
             items_list = r.json().get('data') or []
             for item in items_list:
                 title, link = item.get('title', '').strip(), item.get('url')
                 date_str = item.get('updated') or item.get('publishTime')
                 if not date_str: continue
                 try: dt_obj = datetime.datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f%z")
                 except: dt_obj = datetime.datetime.now(HK_TZ)
                 if (now - dt_obj.astimezone(HK_TZ)).total_seconds() > 86400 * 7: continue
                 data.append({
                    'source': config['name'], 'title': title, 'link': link, 
                    'time_str': dt_obj.strftime('%Y-%m-%d %H:%M'), 'timestamp': dt_obj, 'color': config['color']
                 })
        elif config['type'] == 'rss':
            r = requests.get(config['url'], headers=HEADERS, timeout=30, verify=False)
            feed = feedparser.parse(r.content)
            for entry in feed.entries:
                time_struct = getattr(entry, 'updated_parsed', None) or getattr(entry, 'published_parsed', None)
                dt_obj = datetime.datetime.fromtimestamp(time.mktime(time_struct), UTC_TZ).astimezone(HK_TZ)
                if config['name'] == "信報即時": dt_obj = dt_obj + datetime.timedelta(days=7)
                if (now - dt_obj).total_seconds() > 86400 * 7: continue
                data.append({
                    'source': config['name'], 'title': entry.title.rsplit(' - ', 1)[0], 'link': entry.link, 
                    'time_str': dt_obj.strftime('%Y-%m-%d %H:%M'), 'timestamp': dt_obj, 'color': config['color']
                })
    except: pass
    return {'name': config['name'], 'data': sorted(data, key=lambda x: x['timestamp'], reverse=True)[:limit]}

@st.cache_data(ttl=60, show_spinner=False)
def get_all_news_data_parallel(limit=300):
    RSSHUB_BASE = "https://rsshub-production-9dfc.up.railway.app"
    configs = [
        {"name": "政府新聞（中）", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_zh.xml", "color": "#E74C3C"},
        {"name": "政府新聞（英）", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_en.xml", "color": "#C0392B"},
        {"name": "RTHK 本地", "type": "rss", "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "color": "#FF9800"},
        {"name": "Now 新聞", "type": "rss", "url": f"{RSSHUB_BASE}/now/news/local", "color": "#16A34A"},
        {"name": "on.cc 東網", "type": "rss", "url": f"{RSSHUB_BASE}/oncc/zh-hant/news", "color": "#7C3AED"},
        {"name": "星島即時", "type": "rss", "url": "https://www.stheadline.com/rss", "color": "#F97316"},
        {"name": "明報即時", "type": "rss", "url": "https://news.mingpao.com/rss/ins/all.xml", "color": "#2563EB"},
        {"name": "文匯報", "type": "json_wenweipo", "url": "https://www.wenweipo.com/channels/wenweipo/hotlist/hours/24/stories.json", "color": "#BE123C"},
        {"name": "信報即時", "type": "rss", "url": f"{RSSHUB_BASE}/hkej/index", "color": "#64748B"},
    ]
    results_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_single_source, conf, limit): conf for conf in configs}
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            results_map[res['name']] = res['data']
    return results_map, configs

# --- 4. UI 介面 ---

if 'selected_links' not in st.session_state: st.session_state.selected_links = set()
if 'show_preview' not in st.session_state: st.session_state.show_preview = False

with st.sidebar:
    st.header("⚙️ 控制台")
    if st.button("🔄 刷新新聞", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.metric("已選新聞", f"{len(st.session_state.selected_links)} 篇")
    if st.button("📄 生成文本", type="primary", use_container_width=True):
        st.session_state.show_preview = True
        st.rerun()

news_data_map, source_configs = get_all_news_data_parallel(300)

@st.dialog("📄 文本預覽")
def show_txt_preview():
    all_news = [n for items in news_data_map.values() for n in items if n['link'] in st.session_state.selected_links]
    all_news.sort(key=lambda x: x['timestamp'], reverse=True)
    text = ""
    for item in all_news:
        content, _ = fetch_full_article(item['link'])
        text += f"{item['source']}：{item['title']}\n[{item['time_str']}]\n\n{content}\n\n{item['link']}\n\nEnds\n\n"
    st.text_area("全選複製：", value=text, height=500)

if st.session_state.show_preview: show_txt_preview()

st.title("新聞監察系統")
rows = chunked(source_configs, 4)

for row in rows:
    cols = st.columns(len(row))
    for col, conf in zip(cols, row):
        with col:
            items = news_data_map.get(conf['name'], [])
            with st.container(height=600, border=True):
                # 標題區 (會被 CSS 釘選)
                st.markdown(f"""
                    <div class='news-source-header' style='border-left: 5px solid {conf['color']}'>
                        <div>{conf['name']}</div>
                        <span class='status-badge'>{len(items)} 則</span>
                    </div>
                """, unsafe_allow_html=True)
                
                if not items:
                    st.caption("暫無資料")
                else:
                    for item in items:
                        link = item['link']
                        is_new = is_new_news(item['timestamp'])
                        is_selected = link in st.session_state.selected_links
                        
                        c1, c2 = st.columns([0.15, 0.85])
                        with c1:
                            if st.checkbox("", key=f"c_{link}", value=is_selected):
                                st.session_state.selected_links.add(link)
                            else:
                                st.session_state.selected_links.discard(link)
                        with c2:
                            badge = '<span class="new-badge">NEW!</span>' if is_new else ''
                            style = 'class="read-text"' if is_selected else ""
                            st.markdown(f'<div class="news-item-row">{badge}<a href="{link}" target="_blank" {style}>{html.escape(item["title"])}</a><div class="news-time">{item["time_str"]}</div></div>', unsafe_allow_html=True)
