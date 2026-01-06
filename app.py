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
    
    /* 1. 強制主容器不透明度永遠為 1，取消過渡動畫 */
    .stApp, div[data-testid="stAppViewContainer"] {
        opacity: 1 !important;
        transition: none !important;
    }
    
    /* 2. 隱藏頂部彩虹載入條 */
    header .stDecoration {
        display: none !important;
    }
    
    /* 3. 隱藏右上角 Running 動畫 */
    div[data-testid="stStatusWidget"] {
        visibility: hidden;
    }

    div.block-container { min-height: 100vh; }
    div[data-testid="stAppViewContainer"] { overflow-y: scroll; }
    
    @keyframes blinker { 50% { opacity: 0.4; } }
    .new-badge {
        color: #ef4444;
        font-weight: 800;
        animation: blinker 1.5s ease-in-out infinite;
        margin-right: 5px;
        font-size: 0.75em;
        display: inline-block;
        vertical-align: middle;
        opacity: 1;
        transition: opacity 0.3s ease;
    }

    .news-item-row:hover .new-badge {
        opacity: 0;
    }
    
    .read-text { color: #9ca3af !important; font-weight: normal !important; text-decoration: none !important; }
    a { text-decoration: none; color: #334155; font-weight: 600; transition: 0.2s; font-size: 0.95em; line-height: 1.4; display: inline; }
    a:hover { color: #2563eb; }
    
    .news-source-header { 
        font-size: 1rem; 
        font-weight: bold; 
        color: #1e293b; 
        padding: 15px 10px; 
        margin: 0; 
        border-bottom: 2px solid #f1f5f9;
        display: flex; 
        justify-content: space-between; 
        align-items: center;
        background-color: white; 
        position: sticky;
        top: 0;
        z-index: 50; 
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
        transition: all 0.2s;
    }
    .header-btn:hover { background-color: #e0e7ff; color: #2563eb; border-color: #2563eb; }
    
    .news-item-row { padding: 8px 5px; border-bottom: 1px solid #f1f5f9; }
    .news-item-row:last-child { border-bottom: none; }
    .news-time { font-size: 0.8em; color: #94a3b8; margin-top: 4px; display: block; }
    
    .stCheckbox { margin-bottom: 0px; margin-top: 2px; }
    div[data-testid="column"] { display: flex; align-items: start; }
    
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        border-top-left-radius: 0 !important;
        border-top-right-radius: 0 !important;
        border-color: #e2e8f0 !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        background-color: white;
    }
    
    div[data-testid="stVerticalScrollArea"] > div[data-testid="stVerticalBlock"] { padding-top: 0rem; }

    div[data-testid="stDialog"] { border-radius: 15px; }
    .generated-box { border: 2px solid #3b82f6; border-radius: 12px; padding: 20px; background-color: #ffffff; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); margin-bottom: 20px; }
    
    .error-msg {
        font-size: 0.8em;
        color: #dc2626;
        background-color: #fee2e2;
        padding: 8px;
        border-radius: 4px;
        margin: 10px;
        word-break: break-all;
    }

    @media (max-width: 768px) {
        div[data-testid="stVerticalBlockBorderWrapper"] > div > div[data-testid="stVerticalScrollArea"] {
            height: 450px !important;
            max-height: 450px !important;
            overflow-y: auto !important;
        }
        div[data-testid="column"] { margin-bottom: 20px !important; }
        .header-btn { display: inline-block !important; }
    }
    .stApp, div[data-testid="stAppViewContainer"] { opacity: 1 !important; transition: none !important; }
    header .stDecoration { display: none !important; }
    div[data-testid="stStatusWidget"] { visibility: hidden; }
    div.block-container { min-height: 100vh; }
</style>
""", unsafe_allow_html=True)

# 設定時區
HK_TZ = pytz.timezone('Asia/Hong_Kong')
UTC_TZ = pytz.timezone('UTC')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-HK,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Referer': 'https://www-d-google-d-com-s-gmn.tuangouai.com/'
}

# --- 2. 核心功能函式 ---

def chunked(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]

def resolve_google_url(url):
    if "news.google.com" not in url:
        return url
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        r = session.get(url, allow_redirects=True, timeout=15)
        
        if "news.google.com" not in r.url and "google.com" not in r.url:
            return r.url
            
        html_content = r.text
        soup = BeautifulSoup(html_content, 'html.parser')
        
        link_with_data = soup.find('a', attrs={'data-n-url': True})
        if link_with_data: return link_with_data['data-n-url']

        match = re.search(r'window\.location\.replace\("(.+?)"\)', html_content)
        if match: return match.group(1).encode('utf-8').decode('unicode_escape')
            
        links = soup.find_all('a', href=True)
        for link in links:
            href = link['href']
            if href.startswith('http') and 'google.com' not in href and 'google.co' not in href:
                return href
        return r.url 
    except:
        return url

def extract_time_from_html(soup):
    try:
        meta_tags = [
            {'property': 'article:published_time'}, {'property': 'og:updated_time'},
            {'name': 'pubdate'}, {'name': 'publish-date'}, {'name': 'date'},
            {'itemprop': 'datePublished'}
        ]
        for tag in meta_tags:
            meta = soup.find('meta', attrs=tag)
            if meta and meta.get('content'):
                dt_str = meta['content']
                if 'T' in dt_str: return dt_str.replace('T', ' ').split('+')[0][:16]
                return dt_str[:16]
        return None
    except:
        return None

def fetch_full_article(url, summary_fallback=""):
    if "news.google.com" in url or "google.com" in url:
        return summary_fallback if summary_fallback else "(連結還原失敗，請點擊連結查看)", None

    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        r = session.get(url, timeout=20)
        r.encoding = r.apparent_encoding 
        soup = BeautifulSoup(r.text, 'html.parser')
        
        real_time = extract_time_from_html(soup)
        
        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'iframe', 'noscript', 'aside', 'form', 'button', 'input', '.ad', '.advertisement', '.related-news', '.hidden', '.copyright', '.share-bar', '.video-player', '.recommendation']):
            tag.decompose()

        paragraphs = []
        
        if "info.gov.hk" in url:
            content_div = soup.find(id="pressrelease") or soup.find(class_="content") or soup.find(id="content")
            if content_div:
                text_spans = content_div.find_all('span', style=lambda x: x and 'font-size' in x)
                if text_spans: raw_text = "\n".join([s.get_text() for s in text_spans])
                else: raw_text = content_div.get_text(separator="\n")
                lines = [line.strip() for line in raw_text.splitlines() if len(line.strip()) > 0]
                return "\n\n".join(lines), real_time

        elif "stheadline.com" in url:
            content_div = soup.find('div', class_='paragraph') or soup.find('div', class_='article-content') or soup.find('section', class_='article-body')
            if content_div:
                paragraphs = content_div.find_all(['p', 'div'], recursive=False)
                paragraphs = [p for p in paragraphs if len(p.get_text(strip=True)) > 0]

        elif "hk01.com" in url:
            content_div = soup.find('div', class_=re.compile(r'article-content|article_content'))
            if content_div: paragraphs = content_div.find_all(['p', 'div.text-paragraph'], recursive=True)

        elif "on.cc" in url:
            content_div = soup.find(class_="breakingNewsContent") or soup.find(class_="news_content")
            if content_div:
                paragraphs = content_div.find_all('p')
                if not paragraphs:
                    raw_text = content_div.get_text(separator="\n")
                    lines = [line.strip() for line in raw_text.splitlines() if len(line.strip()) > 0]
                    return "\n\n".join(lines), real_time

        elif "mingpao.com" in url:
            content_div = soup.find(class_="txt4") 
            if content_div: paragraphs = content_div.find_all('p')

        elif "hkej.com" in url:
            content_div = soup.find(id="article-content")
            if content_div: paragraphs = content_div.find_all('p')

        elif "rthk.hk" in url:
            content_div = soup.find(class_="itemFullText")
            if content_div:
                paragraphs = content_div.find_all('p')
                if not paragraphs:
                    raw_text = content_div.get_text(separator="\n")
                    lines = [line.strip() for line in raw_text.splitlines() if len(line.strip()) > 0]
                    return "\n\n".join(lines), real_time
        
        elif "wenweipo.com" in url:
            content_div = soup.find('div', class_='content-box') or soup.find('div', class_='article-content')
            if content_div:
                paragraphs = content_div.find_all('p')

        if not paragraphs:
            content_area = soup.find('div', class_=lambda x: x and any(term in x.lower() for term in ['article', 'content', 'news-text', 'story', 'post-body', 'main-text', 'detail', 'entry-content', 'body']))
            if content_area:
                paragraphs = content_area.find_all(['p', 'div'], recursive=False)
                if not paragraphs: paragraphs = content_area.find_all('p')
        
        if not paragraphs: paragraphs = soup.find_all('p')

        clean_text = []
        for p in paragraphs:
            text = p.get_text().strip()
            if len(text) > 5 and "Copyright" not in text and "版權所有" not in text:
                clean_text.append(text)

        if not clean_text:
            return summary_fallback if summary_fallback else "(無法自動提取全文，可能受限於付費牆或動態載入)", real_time
            
        full_text = "\n\n".join(clean_text)
        return full_text, real_time

    except Exception as e:
        return summary_fallback if summary_fallback else f"(抓取錯誤: {str(e)})", None

def is_new_news(timestamp):
    if not timestamp: return False
    try:
        now = datetime.datetime.now(HK_TZ)
        if timestamp.tzinfo is None: timestamp = HK_TZ.localize(timestamp)
        else: timestamp = timestamp.astimezone(HK_TZ)
        diff = (now - timestamp).total_seconds() / 60
        return 0 <= diff <= 30
    except:
        return False

# --- 3. 抓取邏輯 (並行處理) ---

@st.cache_data(ttl=60, show_spinner=False)
def fetch_google_proxy(site_query, site_name, color, limit=100):
    query = urllib.parse.quote(site_query)
    rss_url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    try:
        feed = feedparser.parse(rss_url)
        news_list = []
        now = datetime.datetime.now(HK_TZ)

        for entry in feed.entries: 
            title = entry.title.rsplit(" - ", 1)[0].strip()
            dt_obj = datetime.datetime.now(HK_TZ)
            if hasattr(entry, 'published_parsed'):
                dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
            
            # 放寬到 7 天內新聞
            age_seconds = (now - dt_obj).total_seconds()
            if age_seconds > 86400 * 7 or age_seconds < -3600: 
                continue

            dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
            summary = ""
            if hasattr(entry, 'summary'): summary = BeautifulSoup(entry.summary, "html.parser").get_text()
            elif hasattr(entry, 'description'): summary = BeautifulSoup(entry.description, "html.parser").get_text()

            news_list.append({
                'source': site_name, 'title': title, 'link': entry.link, 
                'time_str': dt_str, 'timestamp': dt_obj, 'color': color, 'method': 'Proxy', 'summary': summary
            })
        
        news_list.sort(key=lambda x: x['timestamp'], reverse=True)
        return news_list[:limit]
    except:
        return []

@st.cache_data(ttl=60, show_spinner=False)
def fetch_single_source(config, limit=100):
    data = []
    now = datetime.datetime.now(HK_TZ)
    error_msg = None

    try:
        if config['type'] == 'now_api':
             api_url = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2?category=119&pageNo=1"
             r = requests.get(api_url, headers=HEADERS, timeout=20)
             if r.status_code != 200:
                 error_msg = f"API Error: {r.status_code}"
             else:
                 data_list = r.json()
                 items_list = []
                 if isinstance(data_list, list): items_list = data_list
                 elif isinstance(data_list, dict):
                     for k in ['data', 'items', 'news']:
                         if k in data_list and isinstance(data_list[k], list): items_list = data_list[k]; break
                 
                 for item in items_list:
                     title = (item.get('newsTitle') or item.get('title') or "").strip()
                     news_id = item.get('newsId')
                     link = f"https://news.now.com/home/local/player?newsId={news_id}" if news_id else ""
                     
                     pub_date = item.get('publishDate')
                     if pub_date:
                         dt_obj = datetime.datetime.fromtimestamp(pub_date/1000, HK_TZ)
                     else:
                         dt_obj = datetime.datetime.now(HK_TZ)
                     
                     if (now - dt_obj).total_seconds() > 86400 * 7: continue
                     
                     if title and link:
                        data.append({
                            'source': config['name'], 'title': title, 'link': link, 
                            'time_str': dt_obj.strftime('%Y-%m-%d %H:%M'), 
                            'timestamp': dt_obj, 'color': config['color'], 'method': 'API', 'summary': "" 
                        })
        
        elif config['type'] == 'api_hk01':
             r = requests.get(config['url'], headers=HEADERS, params={"limit": 200}, timeout=20)
             if r.status_code != 200:
                 error_msg = f"API Error: {r.status_code}"
             else:
                 items_list = r.json().get('items', [])
                 for item in items_list:
                     data_obj = item.get('data', {})
                     title = data_obj.get('title')
                     link = data_obj.get('publishUrl')
                     publish_time = data_obj.get('publishTime')
                     dt_obj = datetime.datetime.now(HK_TZ)
                     if publish_time: dt_obj = datetime.datetime.fromtimestamp(publish_time, HK_TZ)
                     
                     if (now - dt_obj).total_seconds() > 86400 * 7: continue

                     if title and link:
                         data.append({
                            'source': config['name'], 'title': title, 'link': link, 
                            'time_str': dt_obj.strftime('%Y-%m-%d %H:%M'), 
                            'timestamp': dt_obj, 'color': config['color'], 'method': 'API', 'summary': "" 
                         })
        
        # 文匯報 JSON (支援優先顯示更新時間)
        elif config['type'] == 'json_wenweipo':
             r = requests.get(config['url'], headers=HEADERS, timeout=30, verify=False)
             if r.status_code != 200:
                 error_msg = f"API Error: {r.status_code}"
             else:
                 data_json = r.json()
                 items_list = data_json.get('data') or []
                 
                 for item in items_list:
                     title = item.get('title', '').strip()
                     link = item.get('url')
                     
                     # 優先獲取更新時間 'updated'，沒有才用 'publishTime'
                     date_str = item.get('updated')
                     if not date_str:
                         date_str = item.get('publishTime')
                     
                     # 解析時間
                     dt_obj = datetime.datetime.now(HK_TZ) # 預設
                     if date_str:
                         try:
                             # 嘗試多種時間格式
                             dt_obj = datetime.datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f%z")
                         except ValueError:
                             try:
                                 dt_obj = datetime.datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S%z")
                             except:
                                 pass
                         
                         if dt_obj.tzinfo:
                             dt_obj = dt_obj.astimezone(HK_TZ)
                     
                     # 放寬檢查到 7 天
                     if (now - dt_obj).total_seconds() > 86400 * 7: continue
                     
                     if title and link:
                        data.append({
                            'source': config['name'], 
                            'title': title, 
                            'link': link, 
                            'time_str': dt_obj.strftime('%Y-%m-%d %H:%M'), 
                            'timestamp': dt_obj, 
                            'color': config['color'], 
                            'method': 'API', 
                            'summary': item.get('summary', '') 
                        })

        elif config['type'] == 'rss':
            # 增加 timeout 到 30 秒，並忽略 SSL 驗證
            r = requests.get(config['url'], headers=HEADERS, timeout=30, verify=False)
            
            if r.status_code != 200:
                error_msg = f"HTTP Error: {r.status_code}"
            else:
                feed = feedparser.parse(r.content)
                
                if not feed.entries:
                    if hasattr(feed, 'bozo') and feed.bozo:
                         error_msg = f"RSS Parse Error: {feed.bozo_exception}"
                    elif r.text.strip().startswith("<!DOCTYPE html") or "<html" in r.text[:100].lower():
                         error_msg = "Content is HTML not RSS (Cloudflare/Error Page?)"
                    else:
                         error_msg = "No entries found in feed"
                
                for entry in feed.entries:
                    # RSS 優先讀取 updated_parsed (更新時間)，沒有才讀 published_parsed (發布時間)
                    time_struct = getattr(entry, 'updated_parsed', None) or getattr(entry, 'published_parsed', None)
                    
                    if time_struct:
                        dt_obj = datetime.datetime.fromtimestamp(time.mktime(time_struct), UTC_TZ).astimezone(HK_TZ)
                    else:
                        dt_obj = datetime.datetime.now(HK_TZ)
                    
                    # --- 特別修正：信報來源日期錯誤 (RSSHub 落後 7 天)，手動校正 ---
                    if config['name'] == "信報即時":
                        dt_obj = dt_obj + datetime.timedelta(days=7)

                    age_seconds = (now - dt_obj).total_seconds()
                    
                    if age_seconds > 86400 * 7 or age_seconds < -86400: continue

                    title = entry.title.strip()
                    if "news.google.com" in config['url']:
                        title = title.rsplit(' - ', 1)[0].strip()

                    summary = ""
                    if hasattr(entry, 'summary'): summary = BeautifulSoup(entry.summary, "html.parser").get_text()
                    elif hasattr(entry, 'description'): summary = BeautifulSoup(entry.description, "html.parser").get_text()

                    data.append({
                        'source': config['name'], 'title': title, 'link': entry.link, 
                        'time_str': dt_obj.strftime('%Y-%m-%d %H:%M'), 
                        'timestamp': dt_obj, 'color': config['color'], 'method': 'RSS', 'summary': summary
                    })

    except Exception as e:
        error_msg = f"Exception: {str(e)}"
        data = []

    if not data and config.get('backup_query'):
        data = fetch_google_proxy(config['backup_query'], config['name'], config['color'], limit)
        error_msg = None # Clear error if backup worked
    
    data.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return {'name': config['name'], 'data': data[:limit], 'error': error_msg}

@st.cache_data(ttl=60, show_spinner=False)
def get_all_news_data_parallel(limit=300):
    RSSHUB_BASE = "https://rsshub-production-9dfc.up.railway.app" 
    ANTIDRUG_RSS = "https://news.google.com/rss/search?q=毒品+OR+保安局+OR+鄧炳強+OR+緝毒+OR+太空油+OR+依託咪酯+OR+禁毒+OR+毒品案+OR+海關+OR+保安局+OR+鄧炳強+OR+戰時炸彈+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"

    configs = [
        # 第一行 (4個)
        {"name": "禁毒/海關新聞", "type": "rss", "url": ANTIDRUG_RSS, "color": "#D946EF", 'backup_query': 'site:news.google.com 毒品'},
        {"name": "政府新聞（中文）", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_zh.xml", "color": "#E74C3C", 'backup_query': 'site:info.gov.hk'},
        {"name": "政府新聞（英文）", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_en.xml", "color": "#C0392B", 'backup_query': 'site:info.gov.hk'},
        {"name": "RTHK", "type": "rss", "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "color": "#FF9800", 'backup_query': 'site:news.rthk.hk'},
        
        # 第二行 (4個)
        {"name": "on.cc 東網", "type": "rss", "url": f"{RSSHUB_BASE}/oncc/zh-hant/news?limit=300", "color": "#7C3AED", 'backup_query': 'site:hk.on.cc'},
        {"name": "HK01", "type": "api_hk01", "url": "https://web-data.api.hk01.com/v2/feed/category/0", "color": "#2563EB", 'backup_query': 'site:hk01.com'},
        {"name": "星島即時", "type": "rss", "url": "https://www.stheadline.com/rss", "color": "#F97316", 'backup_query': 'site:stheadline.com'},
        {"name": "Now 新聞（本地）", "type": "now_api", "url": "", "color": "#16A34A", 'backup_query': 'site:news.now.com/home/local'},
        
        # 第三行 (4個)
        {"name": "明報即時", "type": "rss", "url": "https://news.mingpao.com/rss/ins/all.xml", "color": "#7C3AED", 'backup_query': 'site:news.mingpao.com'},
        {"name": "i-CABLE 有線", "type": "rss", "url": "https://www.i-cable.com/feed", "color": "#A855F7", 'backup_query': 'site:i-cable.com'},
        {"name": "信報即時", "type": "rss", "url": f"{RSSHUB_BASE}/hkej/index", "color": "#64748B"},
        # 新增文匯報 (使用官方 API)
        {"name": "文匯報", "type": "json_wenweipo", "url": "https://www.wenweipo.com/channels/wenweipo/hotlist/hours/24/stories.json", "color": "#BE123C"},
    ]

    results_map = {}
    error_map = {}
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        future_to_source = {executor.submit(fetch_single_source, conf, limit): conf for conf in configs}
        for future in concurrent.futures.as_completed(future_to_source):
            try:
                result = future.result()
                name = result['name']
                results_map[name] = result['data']
                error_map[name] = result.get('error')
            except Exception as e:
                pass 

    return results_map, error_map, configs

# --- 4. 初始化 ---

if 'selected_links' not in st.session_state:
    st.session_state.selected_links = set()
if 'show_preview' not in st.session_state:
    st.session_state.show_preview = False
if 'generated_text' not in st.session_state:
    st.session_state.generated_text = ""

# --- 5. UI 佈局 ---

def clear_all_selections():
    st.session_state.selected_links.clear()
    st.session_state.generated_text = ""
    st.session_state.show_preview = False
    for key in list(st.session_state.keys()):
        if key.startswith("chk_"):
            st.session_state[key] = False

@st.dialog("📄 生成結果預覽")
def show_txt_preview(txt_content):
    st.text_area("內容 (可全選複製)：", value=txt_content, height=500)
    if st.button("關閉視窗"):
        st.session_state.show_preview = False
        st.rerun()

with st.sidebar:
    st.header("⚙️ 控制台")
    st.caption(f"更新時間: {datetime.datetime.now(HK_TZ).strftime('%H:%M:%S')}")
    if st.button("🔄 立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    st.divider()
    
    select_count = len(st.session_state.selected_links)
    st.metric("已選新聞", f"{select_count} 篇")
    
    if st.button("📄 生成 TXT 內容", type="primary", use_container_width=True):
        if select_count == 0:
            st.warning("請先勾選新聞！")
        else:
            # 這裡只設置狀態，不進行耗時操作
            st.session_state.show_preview = True
            st.rerun()

    st.button("🗑️ 一鍵清空選擇", use_container_width=True, on_click=clear_all_selections)

# 抓取資料
news_data_map, error_map, source_configs = get_all_news_data_parallel(300)

all_flat_news = []
for name, items in news_data_map.items():
    all_flat_news.extend(items)

# 處理生成邏輯
if st.session_state.show_preview:
    if not st.session_state.generated_text:
        with st.spinner("正在提取全文..."):
            final_txt = ""
            targets = [n for n in all_flat_news if n['link'] in st.session_state.selected_links]
            targets.sort(key=lambda x: x['timestamp'], reverse=True)
            
            for item in targets:
                real_link = resolve_google_url(item['link'])
                content, real_time = fetch_full_article(real_link, item.get('summary', ''))
                display_time = real_time if real_time else item['time_str']
                
                final_txt += f"{item['source']}：{item['title']}\n"
                final_txt += f"[{display_time}]\n\n"
                final_txt += f"{content}\n\n"
                final_txt += f"{real_link}\n\n"
                final_txt += "Ends\n\n"
            st.session_state.generated_text = final_txt
    
    show_txt_preview(st.session_state.generated_text)

st.title("Tommy Sir 後援會之新聞監察系統")

cols_per_row = 4
rows = chunked(source_configs, cols_per_row)

for row in rows:
    cols = st.columns(len(row))
    for col, conf in zip(cols, row):
        with col:
            name = conf['name']
            items = news_data_map.get(name, [])
            error_msg = error_map.get(name)
            
            # 卡片容器
            with st.container(height=600, border=True):
                # 將 Header 移入 Container 內部，並透過 CSS 進行 Sticky 定位
                st.markdown(f"""
                    <div class='news-source-header' style='border-left: 5px solid {conf['color']}'>
                        <div style="display:flex; align-items:center;">
                            <span>{name}</span>
                            <button class="header-btn" onclick="var el=this.closest('[data-testid=\\'stVerticalBlock\\']').querySelector('[data-testid=\\'stVerticalScrollArea\\']'); if(el) el.scrollTop = 0;" title="回到最新">
                                ⬆
                            </button>
                        </div>
                        <span class='status-badge'>{len(items)} 則</span>
                    </div>
                """, unsafe_allow_html=True)

                if not items:
                    st.caption("暫無資料")
                    if error_msg:
                        st.markdown(f"<div class='error-msg'>⚠️ {error_msg}</div>", unsafe_allow_html=True)
                else:
                    for item in items:
                        link = item['link']
                        is_new = is_new_news(item['timestamp'])
                        is_selected = link in st.session_state.selected_links
                        
                        c1, c2 = st.columns([0.15, 0.85])
                        with c1:
                            def update_state(k=link):
                                if k in st.session_state.selected_links:
                                    st.session_state.selected_links.remove(k)
                                else:
                                    st.session_state.selected_links.add(k)
                            st.checkbox("", key=f"chk_{link}", value=is_selected, on_change=update_state)
                        with c2:
                            new_badge_html = f'<span class="new-badge">NEW!</span>' if is_new else ''
                            title_esc = html.escape(item['title'])
                            text_style = 'class="read-text"' if is_selected else ""
                            
                            item_html = f'<div class="news-item-row">{new_badge_html}<a href="{link}" target="_blank" {text_style}>{title_esc}</a><div class="news-time">{item["time_str"]}</div></div>'
                            st.markdown(item_html, unsafe_allow_html=True)
