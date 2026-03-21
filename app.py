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

# 忽略 SSL 警告
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
    .stApp, div[data-testid="stAppViewContainer"] { opacity: 1 !important; transition: none !important; }
    header .stDecoration { display: none !important; }
    div[data-testid="stStatusWidget"] { visibility: hidden; }
    div.block-container { min-height: 100vh; padding-top: 2rem; }

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
    a { text-decoration: none; color: #334155; font-weight: 600; transition: 0.2s; font-size: 0.95em; line-height: 1.4; display: inline; }
    a:hover { color: #2563eb; }

    div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalScrollArea"] { padding-top: 0px !important; }
    div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalScrollArea"] > div[data-testid="stVerticalBlock"] { gap: 0px !important; padding-top: 0px !important; }

    div[data-testid="stVerticalBlock"] > div.element-container:has(.news-source-header) {
        position: sticky !important;
        top: 0 !important;
        z-index: 99999 !important;
        background-color: #ffffff !important;
        margin: 0 !important;
        padding: 0 !important;
        width: 100% !important;
        box-shadow: 0 4px 10px -2px rgba(0,0,0,0.1); 
        border-bottom: 2px solid #f1f5f9;
        opacity: 1 !important;
    }
    
    .news-source-header { 
        font-size: 1rem; 
        font-weight: bold; 
        color: #1e293b; 
        padding: 15px 10px;
        margin: 0; 
        display: flex; 
        justify-content: space-between; 
        align-items: center;
        background-color: #ffffff !important;
    }

    .news-item-row { padding: 10px 5px; border-bottom: 1px solid #f1f5f9; background-color: white; }
    .news-time { font-size: 0.8em; color: #94a3b8; margin-top: 4px; display: block; }
    
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        border-top-left-radius: 10px !important;
        border-top-right-radius: 10px !important;
        background-color: white;
        overflow: hidden;
        border: 1px solid #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

HK_TZ = pytz.timezone('Asia/Hong_Kong')
UTC_TZ = pytz.timezone('UTC')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

# --- 2. 工具功能 ---

def clean_url(url: str) -> str:
    """處理網址：修正信報域名、NowTV參數與去重"""
    if not url: return ""
    url = url.strip()
    
    # 修正信報連結：將 m.hkej.com 替換為 www.hkej.com 避免 404
    if "hkej.com" in url:
        url = url.replace("m.hkej.com", "www.hkej.com")
        url = url.replace("++", "").strip()
        
    if "news.now.com" in url:
        return urllib.parse.quote(url, safe=":/%?=&")
    
    url = url.split('?')[0] 
    return urllib.parse.quote(url, safe=":/%?=&")

def fetch_full_article(url, summary_fallback=""):
    try:
        r = requests.get(url, timeout=12, headers=HEADERS, verify=False)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, 'html.parser')
        for s in soup(['script', 'style', 'header', 'footer', 'nav', 'aside']): s.decompose()
        paragraphs = soup.find_all('p')
        clean_text = [p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 30]
        return '\n\n'.join(clean_text[:20]) if clean_text else summary_fallback, None
    except: return summary_fallback, None

def is_new_news(timestamp):
    if not timestamp: return False
    now = datetime.datetime.now(HK_TZ)
    diff = (now - timestamp.astimezone(HK_TZ)).total_seconds() / 60
    return 0 <= diff <= 30

# --- 3. 抓取主邏輯 ---

@st.cache_data(ttl=60, show_spinner=False)
def fetch_single_source(config, limit=100):
    data = []
    now = datetime.datetime.now(HK_TZ)
    urls = config['url'] if isinstance(config['url'], list) else [config['url']]
    
    try:
        for target_url in urls:
            if config['type'] == 'json_wenweipo':
                r = requests.get(target_url, headers=HEADERS, timeout=25, verify=False)
                items = r.json().get('data') or []
                for item in items:
                    title, link = item.get('title', '').strip(), item.get('url')
                    date_str = item.get('updated') or item.get('publishTime')
                    dt_obj = datetime.datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f%z") if date_str else now
                    data.append({'source': config['name'], 'title': title, 'link': clean_url(link), 'time_str': dt_obj.strftime('%m-%d %H:%M'), 'timestamp': dt_obj, 'color': config['color']})
            
            elif config['type'] == 'now_api':
                api_url = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2?category=119&pageNo=1"
                r = requests.get(api_url, headers=HEADERS, timeout=20)
                items = r.json().get('data') or []
                for item in items:
                    title = item.get('newsTitle', '').strip()
                    link = f"https://news.now.com/home/local/player?newsId={item.get('newsId')}"
                    dt_obj = datetime.datetime.fromtimestamp(item.get('publishDate')/1000, HK_TZ)
                    data.append({'source': config['name'], 'title': title, 'link': clean_url(link), 'time_str': dt_obj.strftime('%m-%d %H:%M'), 'timestamp': dt_obj, 'color': config['color']})
            
            elif config['type'] == 'api_hk01':
                r = requests.get(target_url, headers=HEADERS, params={"limit": 40}, timeout=20)
                items = r.json().get('items', [])
                for item in items:
                    d = item.get('data', {})
                    dt_obj = datetime.datetime.fromtimestamp(d.get('publishTime'), HK_TZ)
                    data.append({'source': config['name'], 'title': d.get('title'), 'link': clean_url(d.get('publishUrl')), 'time_str': dt_obj.strftime('%m-%d %H:%M'), 'timestamp': dt_obj, 'color': config['color']})
            
            elif config['type'] == 'rss':
                r = requests.get(target_url, headers=HEADERS, timeout=25, verify=False)
                feed = feedparser.parse(r.content)
                for entry in feed.entries:
                    title = entry.title.rsplit(' - ', 1)[0]
                    link = entry.link
                    # 處理 PolitePol 的相對連結補全
                    if link.startswith("/"):
                        if "4xPuKWS07tJs" in target_url: link = f"https://www.881903.com{link}"
                        elif "7vsPHGi1tzC9" in target_url: link = f"https://www.i-cable.com{link}"
                        elif "tBTzOcfkQWzF" in target_url: link = f"https://www.hkej.com{link}"
                        elif "X5o1ke3uTiH3" in target_url: link = f"https://topick.hket.com{link}"
                        elif "KZGhq" in target_url or "8fzf6zR" in target_url: link = f"https://www.orangenews.hk{link}"
                        elif "C499xnj" in target_url or "6oljXv" in target_url: link = f"https://www.wenweipo.com{link}"
                        elif "xbfGvXW" in target_url or "59Pndw" in target_url: link = f"https://www.dotdotnews.com{link}"

                    time_struct = getattr(entry, 'updated_parsed', None) or getattr(entry, 'published_parsed', None)
                    dt_obj = datetime.datetime.fromtimestamp(time.mktime(time_struct), UTC_TZ).astimezone(HK_TZ) if time_struct else now
                    data.append({'source': config['name'], 'title': title, 'link': clean_url(link), 'time_str': dt_obj.strftime('%m-%d %H:%M'), 'timestamp': dt_obj, 'color': config['color']})
    except Exception: pass
    
    seen_links = set()
    unique_data = []
    for d in sorted(data, key=lambda x: x['timestamp'], reverse=True):
        if d['link'] not in seen_links:
            unique_data.append(d)
            seen_links.add(d['link'])
    return {'name': config['name'], 'data': unique_data[:limit]}

def get_all_news_data_parallel():
    RSSHUB = "https://rsshub-production-9dfc.up.railway.app"
    configs = [
        # 第一排
        {"name": "💊 禁毒/海關新聞", "type": "rss", "url": "https://news.google.com/rss/search?q=毒品+OR+海關+OR+太空油+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant", "color": "#D946EF"},
        {"name": "🏛 政府新聞稿", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_zh.xml", "color": "#E74C3C"},
        {"name": "📻 RTHK 香港電台", "type": "rss", "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "color": "#FF9800"},
        {"name": "🎙️ 商業電台", "type": "rss", "url": "https://politepaul.com/fd/4xPuKWS07tJs.xml", "color": "#334155"},
        
        # 第二排
        {"name": "💡 on.cc 東網", "type": "rss", "url": f"{RSSHUB}/oncc/zh-hant/news", "color": "#7C3AED"},
        {"name": "📰 HK01 即時", "type": "api_hk01", "url": "https://web-data.api.hk01.com/v2/feed/category/0", "color": "#2563EB"},
        {"name": "🐯 星島頭條", "type": "rss", "url": "https://www.stheadline.com/rss", "color": "#F97316"},
        {"name": "📝 明報即時", "type": "rss", "url": "https://news.mingpao.com/rss/ins/all.xml", "color": "#7C3AED"},
        
        # 第三排
        {"name": "🐯 Now 新聞", "type": "now_api", "url": "", "color": "#16A34A"},
        {"name": "📺 有線新聞", "type": "rss", "url": "https://politepaul.com/fd/7vsPHGi1tzC9.xml", "color": "#A855F7"},
        {"name": "🟢 經濟日報 TOPick", "type": "rss", "url": "https://politepaul.com/fd/X5o1ke3uTiH3.xml", "color": "#0D9488"},
        {"name": "📜 信報新聞", "type": "rss", "url": "https://politepaul.com/fd/tBTzOcfkQWzF.xml", "color": "#64748B"},

        # 第四排
        {"name": "🍊 橙新聞(整合)", "type": "rss", "url": ["https://politepaul.com/fd/KZGhqIiTnOCq.xml", "https://politepaul.com/fd/8fzf6zRfoy6H.xml"], "color": "#EA580C"},
        {"name": "📜 文匯報(整合)", "type": "rss", "url": ["https://politepaul.com/fd/C499xnjIBdRm.xml", "https://politepaul.com/fd/6oljXv2E75Pp.xml"], "color": "#BE123C"},
        {"name": "🔵 點新聞(整合)", "type": "rss", "url": ["https://politepaul.com/fd/xbfGvXWovqfk.xml", "https://politepaul.com/fd/59PndwU1mb82.xml"], "color": "#0369A1"},
        {"name": "📜 文匯(JSON精選)", "type": "json_wenweipo", "url": "https://www.wenweipo.com/channels/wenweipo/hotlist/hours/24/stories.json", "color": "#BE123C"},
    ]
    
    results_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(fetch_single_source, conf): conf for conf in configs}
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            results_map[res['name']] = res['data']
    return results_map, configs

# --- 4. UI 介面 ---

if 'selected_links' not in st.session_state: st.session_state.selected_links = set()
if 'show_preview' not in st.session_state: st.session_state.show_preview = False

with st.sidebar:
    st.header("⚙️ 控制台")
    if st.button("🔄 立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.metric("已勾選", f"{len(st.session_state.selected_links)} 篇")
    if st.button("📄 生成文本", type="primary", use_container_width=True):
        st.session_state.show_preview = True
        st.rerun()
    if st.button("🗑️ 清空選擇", use_container_width=True):
        st.session_state.selected_links.clear()
        st.rerun()

news_data_map, source_configs = get_all_news_data_parallel()

@st.dialog("📄 生成結果預覽")
def show_txt_preview():
    all_flat = [n for items_list in news_data_map.values() for n in items_list]
    targets = [n for n in all_flat if n['link'] in st.session_state.selected_links]
    targets.sort(key=lambda x: x['timestamp'], reverse=True)
    final_text = ""
    with st.spinner("正在提取全文..."):
        for item in targets:
            content, _ = fetch_full_article(item['link'])
            final_text += f"{item['source']}：{item['title']}\n[{item['time_str']}]\n\n{content}\n\n{item['link']}\n\nEnds\n\n"
    st.text_area("內容：", value=final_text, height=500)
    if st.button("關閉"):
        st.session_state.show_preview = False
        st.rerun()

if st.session_state.show_preview: show_txt_preview()

st.title("Tommy Sir 後援會之新聞監察系統")
rows = [source_configs[i:i + 4] for i in range(0, len(source_configs), 4)]

for row in rows:
    cols = st.columns(4)
    for col, conf in zip(cols, row):
        with col:
            # 獲取當前媒體的數據
            current_items = news_data_map.get(conf['name'], [])
            with st.container(height=800, border=True):
                # 標題區
                st.markdown(f"""
                    <div class='news-source-header' style='border-left: 5px solid {conf['color']}'>
                        <div>{conf['name']}</div>
                        <span class='status-badge'>{len(current_items)} 則</span>
                    </div>
                """, unsafe_allow_html=True)
                
                if not current_items:
                    st.caption("暫無資料")
                else:
                    for item in current_items:
                        link = item['link']
                        is_selected = link in st.session_state.selected_links
                        
                        c1, c2 = st.columns([0.15, 0.85])
                        with c1:
                            # checkbox 邏輯
                            if st.checkbox("", key=f"chk_{link}", value=is_selected):
                                st.session_state.selected_links.add(link)
                            else:
                                if link in st.session_state.selected_links:
                                    st.session_state.selected_links.remove(link)
                        
                        with c2:
                            # 組合 HTML，避免 f-string 內的反斜線
                            is_new = is_new_news(item['timestamp'])
                            badge = '<span class="new-badge">NEW!</span>' if is_new else ''
                            title_class = 'class="read-text"' if is_selected else ""
                            safe_title = html.escape(item["title"])
                            
                            item_html = f'''
                                <div class="news-item-row">
                                    {badge}
                                    <a href="{link}" target="_blank" {title_class}>{safe_title}</a>
                                    <div class="news-time">{item["time_str"]}</div>
                                </div>
                            '''
                            st.markdown(item_html, unsafe_allow_html=True)
