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

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="Tommy Sir 後援會之新聞監察系統",
    page_icon="📰",
    layout="wide"
)

st_autorefresh(interval=60 * 1000, limit=None, key="news_autoupdate")

# CSS 樣式 (包含置頂標題與閃爍 badge)
st.markdown("""
<style>
    .stApp { background-color: #f8fafc; }
    header .stDecoration { display: none !important; }
    div[data-testid="stStatusWidget"] { visibility: hidden; }
    
    @keyframes blinker { 50% { opacity: 0.4; } }
    .new-badge {
        color: #ef4444; font-weight: 800; animation: blinker 1.5s ease-in-out infinite;
        margin-right: 5px; font-size: 0.75em; display: inline-block;
    }
    .read-text { color: #9ca3af !important; text-decoration: none !important; }
    
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        border-top-left-radius: 10px !important; border-top-right-radius: 10px !important;
        background-color: white; border: 1px solid #e2e8f0; overflow: hidden;
    }
    
    .news-source-header { 
        position: sticky; top: 0; z-index: 999;
        font-size: 1rem; font-weight: bold; color: #1e293b; 
        padding: 12px 10px; background-color: #ffffff !important;
        display: flex; justify-content: space-between; align-items: center;
        border-bottom: 2px solid #f1f5f9; box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .news-item-row { padding: 10px 5px; border-bottom: 1px solid #f1f5f9; background-color: white; }
    .news-time { font-size: 0.8em; color: #94a3b8; margin-top: 4px; display: block; }
    a { text-decoration: none; color: #334155; font-weight: 600; font-size: 0.95em; }
    a:hover { color: #2563eb; }
</style>
""", unsafe_allow_html=True)

HK_TZ = pytz.timezone('Asia/Hong_Kong')
UTC_TZ = pytz.timezone('UTC')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# --- 2. 工具功能 ---

def clean_title(raw_title: str) -> str:
    """關鍵修正：自動剝除 HTML 標籤，解決紅色代碼問題"""
    if not raw_title: return ""
    # 使用 BeautifulSoup 剝掉所有 HTML 標籤 (例如 <a>, <span> 等)
    soup = BeautifulSoup(raw_title, "html.parser")
    text = soup.get_text()
    # 移除多餘換行與空格
    return text.replace('\n', ' ').strip()

def clean_url(url: str) -> str:
    """修正信報域名與連結去重"""
    if not url: return ""
    url = url.strip()
    if "hkej.com" in url:
        url = url.replace("m.hkej.com", "www.hkej.com") # 統一使用電腦版域名
        url = re.sub(r'\++$', '', url) # 移除末尾 ++
    if "news.now.com" in url: return urllib.parse.quote(url, safe=":/%?=&")
    return urllib.parse.quote(url.split('?')[0], safe=":/%?=&")

def is_new_news(timestamp):
    if not timestamp: return False
    diff = (datetime.datetime.now(HK_TZ) - timestamp.astimezone(HK_TZ)).total_seconds() / 60
    return 0 <= diff <= 30

# --- 3. 抓取邏輯 ---

@st.cache_data(ttl=60, show_spinner=False)
def fetch_source(config):
    data = []
    now = datetime.datetime.now(HK_TZ)
    urls = config['url'] if isinstance(config['url'], list) else [config['url']]
    
    try:
        for u in urls:
            if config['type'] == 'json_wenweipo':
                r = requests.get(u, headers=HEADERS, timeout=20, verify=False)
                for item in r.json().get('data', []):
                    dt = datetime.datetime.strptime(item.get('updated'), "%Y-%m-%dT%H:%M:%S.%f%z")
                    data.append({'source': config['name'], 'title': clean_title(item.get('title')), 'link': clean_url(item.get('url')), 'timestamp': dt})
            
            elif config['type'] == 'now_api':
                r = requests.get("https://newsapi1.now.com/pccw-news-api/api/getNewsListv2?category=119&pageNo=1", timeout=15)
                for item in r.json().get('data', []):
                    dt = datetime.datetime.fromtimestamp(item.get('publishDate')/1000, HK_TZ)
                    data.append({'source': config['name'], 'title': clean_title(item.get('newsTitle')), 'link': f"https://news.now.com/home/local/player?newsId={item.get('newsId')}", 'timestamp': dt})
            
            elif config['type'] == 'rss':
                r = requests.get(u, headers=HEADERS, timeout=20, verify=False)
                feed = feedparser.parse(r.content)
                for entry in feed.entries:
                    t_title = clean_title(getattr(entry, "title", ""))
                    t_link = getattr(entry, "link", "")
                    # 補全相對路徑
                    if t_link.startswith("/"):
                        if "4xPuKWS" in u: t_link = f"https://www.881903.com{t_link}"
                        elif "7vsPHGi" in u: t_link = f"https://www.i-cable.com{t_link}"
                        elif "tBTzOcf" in u: t_link = f"https://www.hkej.com{t_link}"
                        elif "X5o1ke3" in u: t_link = f"https://topick.hket.com{t_link}"
                    
                    time_struct = getattr(entry, 'published_parsed', None) or getattr(entry, 'updated_parsed', None)
                    dt = datetime.datetime.fromtimestamp(time.mktime(time_struct), HK_TZ) if time_struct else now
                    data.append({'source': config['name'], 'title': t_title, 'link': clean_url(t_link), 'timestamp': dt})
    except: pass
    
    # 去重與排序
    seen = set()
    final = []
    for d in sorted(data, key=lambda x: x['timestamp'], reverse=True):
        if d['link'] not in seen:
            final.append(d)
            seen.add(d['link'])
    return {'name': config['name'], 'data': final[:80]}

def get_data():
    RSSHUB = "https://rsshub-production-9dfc.up.railway.app"
    configs = [
        # 第一排
        {"name": "💊 禁毒/海關", "type": "rss", "url": "https://news.google.com/rss/search?q=毒品+OR+海關+when:1d&hl=zh-HK&gl=HK", "color": "#D946EF"},
        {"name": "🏛 政府新聞", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_zh.xml", "color": "#E74C3C"},
        {"name": "📻 RTHK 電台", "type": "rss", "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "color": "#FF9800"},
        {"name": "🎙️ 商業電台", "type": "rss", "url": "https://politepaul.com/fd/4xPuKWS07tJs.xml", "color": "#334155"},
        # 第二排
        {"name": "💡 on.cc 東網", "type": "rss", "url": f"{RSSHUB}/oncc/zh-hant/news", "color": "#7C3AED"},
        {"name": "📰 HK01 即時", "type": "rss", "url": f"{RSSHUB}/hk01/hot", "color": "#2563EB"},
        {"name": "🐯 星島頭條", "type": "rss", "url": "https://www.stheadline.com/rss", "color": "#F97316"},
        {"name": "📝 明報即時", "type": "rss", "url": "https://news.mingpao.com/rss/ins/all.xml", "color": "#7C3AED"},
        # 第三排
        {"name": "🐯 Now 新聞", "type": "now_api", "url": "", "color": "#16A34A"},
        {"name": "📺 有線新聞", "type": "rss", "url": "https://politepaul.com/fd/7vsPHGi1tzC9.xml", "color": "#A855F7"},
        {"name": "🟢 經濟/TOPick", "type": "rss", "url": "https://politepaul.com/fd/X5o1ke3uTiH3.xml", "color": "#0D9488"},
        {"name": "📜 信報新聞", "type": "rss", "url": "https://politepaul.com/fd/tBTzOcfkQWzF.xml", "color": "#64748B"},
        # 第四排
        {"name": "🍊 橙新聞(合)", "type": "rss", "url": ["https://politepaul.com/fd/KZGhqIiTnOCq.xml", "https://politepaul.com/fd/8fzf6zRfoy6H.xml"], "color": "#EA580C"},
        {"name": "📜 文匯(合)", "type": "rss", "url": ["https://politepaul.com/fd/C499xnjIBdRm.xml", "https://politepaul.com/fd/6oljXv2E75Pp.xml"], "color": "#BE123C"},
        {"name": "🔵 點新聞(合)", "type": "rss", "url": ["https://politepaul.com/fd/xbfGvXWovqfk.xml", "https://politepaul.com/fd/59PndwU1mb82.xml"], "color": "#0369A1"},
        {"name": "📜 文匯(JSON)", "type": "json_wenweipo", "url": "https://www.wenweipo.com/channels/wenweipo/hotlist/hours/24/stories.json", "color": "#BE123C"},
    ]
    res_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as exe:
        futures = {exe.submit(fetch_source, c): c for c in configs}
        for f in concurrent.futures.as_completed(futures):
            r = f.result()
            res_map[r['name']] = r['data']
    return res_map, configs

# --- 4. UI 介面 ---
if 'selected_links' not in st.session_state: st.session_state.selected_links = set()

with st.sidebar:
    st.header("⚙️ 控制台")
    if st.button("🔄 刷新新聞", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.metric("已選篇數", f"{len(st.session_state.selected_links)}")
    if st.button("🗑️ 清空", use_container_width=True):
        st.session_state.selected_links.clear()
        st.rerun()

data_map, configs = get_data()
st.title("Tommy Sir 後援會之新聞監察系統")

rows = [configs[i:i + 4] for i in range(0, len(configs), 4)]
for row in rows:
    cols = st.columns(4)
    for col, conf in zip(cols, row):
        with col:
            items = data_map.get(conf['name'], [])
            with st.container(height=800, border=True):
                st.markdown(f"<div class='news-source-header' style='border-left: 5px solid {conf['color']}'><div>{conf['name']}</div><span class='status-badge'>{len(items)} 則</span></div>", unsafe_allow_html=True)
                for item in items:
                    lk = item['link']
                    is_sel = lk in st.session_state.selected_links
                    c1, c2 = st.columns([0.15, 0.85])
                    with c1:
                        if st.checkbox("", key=f"c_{lk}", value=is_sel): st.session_state.selected_links.add(lk)
                        else: st.session_state.selected_links.discard(lk)
                    with c2:
                        badge = '<span class="new-badge">NEW!</span>' if is_new_news(item['timestamp']) else ''
                        t_style = 'class="read-text"' if is_sel else ""
                        row_html = f'''<div class="news-item-row">{badge}<a href="{lk}" target="_blank" {t_style}>{html.escape(item["title"])}</a><div class="news-time">{item["timestamp"].strftime("%H:%M")}</div></div>'''
                        st.markdown(row_html, unsafe_allow_html=True)
