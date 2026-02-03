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
    
    /* 2. 隱藏頂部載入條與狀態元件 */
    header .stDecoration { display: none !important; }
    div[data-testid="stStatusWidget"] { visibility: hidden; }

    div.block-container { min-height: 100vh; padding-top: 2rem; }
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
    a { text-decoration: none; color: #334155; font-weight: 600; transition: 0.2s; font-size: 0.95em; line-height: 1.4; display: inline; }
    a:hover { color: #2563eb; }
    
    /* --- 核心修正：徹底解決固定標題「穿孔」問題 --- */
    
    /* 1. 針對滾動區域：強制移除頂部內距，讓標題能完全貼頂 */
    div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalScrollArea"] {
        padding-top: 0px !important;
    }
    
    div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalScrollArea"] > div[data-testid="stVerticalBlock"] {
        gap: 0px !important;
        padding-top: 0px !important;
    }

    /* 2. 針對標題容器：強制置頂、純白背景、高層級 */
    div[data-testid="stVerticalBlock"] > div.element-container:has(.news-source-header) {
        position: sticky !important;
        top: 0 !important;
        z-index: 99999 !important; /* 極高層級 */
        background-color: #ffffff !important;
        margin: 0 !important;
        padding: 0 !important;
        width: 100% !important;
        /* 視覺遮罩：防止 1px 縫隙穿孔，並加入明顯陰影 */
        box-shadow: 0 4px 10px -2px rgba(0,0,0,0.1); 
        border-bottom: 2px solid #f1f5f9;
        /* 確保不透明 */
        opacity: 1 !important;
    }
    
    /* 3. 標題文字區域樣式 */
    .news-source-header { 
        font-size: 1rem; 
        font-weight: bold; 
        color: #1e293b; 
        padding: 15px 10px; /* 增加一點高度 */
        margin: 0; 
        display: flex; 
        justify-content: space-between; 
        align-items: center;
        background-color: #ffffff !important; /* 雙重確保背景純白 */
    }

    /* 4. 針對內容區域：確保層級低於標題 */
    div.element-container:has(.news-item-row), 
    div[data-testid="stHorizontalBlock"] {
        position: relative;
        z-index: 1 !important;
        background-color: #ffffff;
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
    
    .news-item-row { padding: 10px 5px; border-bottom: 1px solid #f1f5f9; background-color: white; }
    .news-item-row:last-child { border-bottom: none; }
    .news-time { font-size: 0.8em; color: #94a3b8; margin-top: 4px; display: block; }
    
    /* 卡片容器樣式 */
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        border-top-left-radius: 10px !important;
        border-top-right-radius: 10px !important;
        background-color: white;
        overflow: hidden; /* 確保圓角內內容不溢出 */
        border: 1px solid #e2e8f0;
    }
    
    div[data-testid="column"] { display: flex; align-items: start; }
    .stCheckbox { margin-bottom: 0px; margin-top: 2px; }

    @media (max-width: 768px) {
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalScrollArea"] {
            height: 550px !important; /* 手機版高度 */
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
    """
    優化版：支援更多網站結構的content extraction
    """
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh-HK,zh-CN,en-US,en',
        })
        r = session.get(url, timeout=20)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 移除noise elements
        noise_selectors = ['script', 'style', 'header', 'footer', 'nav', 'aside', 'iframe',
            '[class*="ad"]', '[class*="advertisement"]', '[class*="ads"]',
            '[class*="comment"]', '[class*="sidebar"]', '.nav', '.header', '.footer',
            '.social-share', '.share-buttons', '.related-posts']
        for selector in noise_selectors:
            for tag in soup.select(selector): tag.decompose()
        
        # Content selectors (23個pattern)
        content_selectors = [r'article', r'[role="main"]', r'main',
            r'[class*="content"]', r'[class*="article"]', r'[class*="news-text"]',
            r'[class*="post-body"]', r'[class*="story-body"]', r'[id*="content"]',
            r'[id*="article"]', r'[id*="news"]', '.post-content', '.article-content',
            '.news-content', '.entry-content', '.td-post-content', '.story-body',
            '#article', '#content', '#main', '#news-content', '.blog-post', '.single-post']
        
        content_area = None
        for selector in content_selectors:
            try:
                if selector.startswith('r'):
                    pattern = selector[1:]
                    content_area = soup.find('div', class_=re.compile(pattern, re.I)) or soup.find('article')
                else:
                    content_area = soup.select_one(selector)
                if content_area: break
            except: continue
        
        # Fallback: largest text block
        if not content_area:
            paragraphs = soup.find_all('p')
            if paragraphs:
                parent_counts = {}
                for p in paragraphs[:20]:
                    parent = p.find_parent(['div', 'article', 'section', 'main'])
                    if parent:
                        parent_html = str(parent)
                        parent_counts[parent_html] = parent_counts.get(parent_html, 0) + 1
                if parent_counts:
                    best_parent_html = max(parent_counts, key=parent_counts.get)
                    content_area = BeautifulSoup(best_parent_html, 'html.parser')
        
        if content_area:
            for ad in content_area.find_all(['aside', 'div']):
                ad_classes = ad.get('class', [])
                if any(x in ad_classes for x in ['ad', 'ads', 'advertisement', 'comment', 'share']):
                    ad.decompose()
            paragraphs = content_area.find_all('p')
        else:
            paragraphs = soup.find_all('p')
        
        clean_text = []
        skip_patterns = ['廣告', '廣告贊助', '分享此文', '分享到', '讚好此文章', '按讚', '訂閱', 'advertisement', 'sponsored']
        
        for p in paragraphs:
            text = p.get_text().strip()
            if len(text) < 30: continue
            if any(pattern in text.lower() for pattern in skip_patterns): continue
            clean_text.append(text)
        
        if clean_text:
            return '\n\n'.join(clean_text[:30]), None
        return summary_fallback, None
        
    except Exception as e:
        return summary_fallback, None


def summarize_with_ai(articles_text):
    """用MiniMax API綜合多條新聞"""
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=st.secrets.get("MINIMAX_API_KEY", "sk-cp-P9ZBga8GlZWhLCT4ffhD4VxZkpRbHgKIVLXA8ZJsKDqSuVoAI66yaKtsQsIEhxIu9BUZ28N4qJp_NEaDdjMSMOD0D_-2pq2z_Ii3X1Bb7-g9NR24Mpi8ooE"),
            base_url="https://api.minimax.chat/v1"
        )
        
        prompt = f"""請將以下香港新聞整理成呢個格式：

媒體名稱: 標題 [發佈日期及時間]
正文內容
連結
Ends

規則：
1. 每條新聞用以上格式輸出
2. 媒體名稱: 標題 (用冒號分隔)
3. 發佈日期時間格式：【DD/MM H:MM】
4. 正文不要修改新聞內容，不要做任何修飾，不要photo caption
5. 連結直接放正文下面，有一個空行
6. 每條新聞以 "Ends" 結束
7. 多條新聞用空行分隔

新聞內容：
{articles_text}
"""

        response = client.chat.completions.create(
            model="MiniMax-M2.1",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
            temperature=0.3
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        return f"AI綜合失敗: {str(e)}"

def get_ai_summary_for_selected(selected_links, news_data_map):
    """為selected既新聞生成AI綜合"""
    all_flat = [n for items in news_data_map.values() for n in items]
    targets = [n for n in all_flat if n['link'] in selected_links]
    targets.sort(key=lambda x: x['timestamp'], reverse=True)
    
    if not targets:
        return None, "請先選擇新聞"
    
    with st.spinner("正在fetch新聞內容..."):
        articles = []
        for item in targets:
            content, _ = fetch_full_article(item['link'], summary_fallback=item['title'])
            articles.append(f"【{item['source']}】 {item['title']} [{item['time_str']}]\n{content[:2000]}")
        
        combined_text = "\n\n---\n\n".join(articles)
    
    with st.spinner("正在AI綜合分析..."):
        summary = summarize_with_ai(combined_text)
    
    return summary, None


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
            time_struct = getattr(entry, 'published_parsed', None)
            if not time_struct: continue
            dt_obj = datetime.datetime.fromtimestamp(time.mktime(time_struct), UTC_TZ).astimezone(HK_TZ)
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
        elif config['type'] == 'now_api':
             api_url = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2?category=119&pageNo=1"
             r = requests.get(api_url, headers=HEADERS, timeout=20)
             items_list = r.json().get('data') or r.json().get('items') or []
             for item in items_list:
                 title = (item.get('newsTitle') or item.get('title') or "").strip()
                 news_id = item.get('newsId')
                 link = f"https://news.now.com/home/local/player?newsId={news_id}"
                 pub_date = item.get('publishDate')
                 dt_obj = datetime.datetime.fromtimestamp(pub_date/1000, HK_TZ) if pub_date else now
                 if (now - dt_obj).total_seconds() > 86400 * 7: continue
                 data.append({
                    'source': config['name'], 'title': title, 'link': link, 
                    'time_str': dt_obj.strftime('%Y-%m-%d %H:%M'), 'timestamp': dt_obj, 'color': config['color']
                 })
        elif config['type'] == 'api_hk01':
             r = requests.get(config['url'], headers=HEADERS, params={"limit": 50}, timeout=20)
             items_list = r.json().get('items', [])
             for item in items_list:
                 data_obj = item.get('data', {})
                 title, link = data_obj.get('title'), data_obj.get('publishUrl')
                 publish_time = data_obj.get('publishTime')
                 dt_obj = datetime.datetime.fromtimestamp(publish_time, HK_TZ) if publish_time else now
                 if (now - dt_obj).total_seconds() > 86400 * 7: continue
                 data.append({'source': config['name'], 'title': title, 'link': link, 'time_str': dt_obj.strftime('%Y-%m-%d %H:%M'), 'timestamp': dt_obj, 'color': config['color']})
        elif config['type'] == 'rss':
            r = requests.get(config['url'], headers=HEADERS, timeout=30, verify=False)
            feed = feedparser.parse(r.content)
            for entry in feed.entries:
                time_struct = getattr(entry, 'updated_parsed', None) or getattr(entry, 'published_parsed', None)
                if not time_struct: continue
                dt_obj = datetime.datetime.fromtimestamp(time.mktime(time_struct), UTC_TZ).astimezone(HK_TZ)
                if config['name'] == "信報即時": dt_obj = dt_obj + datetime.timedelta(days=7)
                if (now - dt_obj).total_seconds() > 86400 * 7: continue
                data.append({
                    'source': config['name'], 'title': entry.title.rsplit(' - ', 1)[0], 'link': entry.link, 
                    'time_str': dt_obj.strftime('%Y-%m-%d %H:%M'), 'timestamp': dt_obj, 'color': config['color']
                })
    except: pass
    if not data and config.get('backup_query'):
        data = fetch_google_proxy(config['backup_query'], config['name'], config['color'])
    return {'name': config['name'], 'data': sorted(data, key=lambda x: x['timestamp'], reverse=True)[:limit]}

@st.cache_data(ttl=60, show_spinner=False)
def get_all_news_data_parallel(limit=300):
    RSSHUB_BASE = "https://rsshub-production-9dfc.up.railway.app"
    ANTIDRUG_RSS = "https://news.google.com/rss/search?q=毒品+OR+保安局+OR+鄧炳強+OR+緝毒+OR+太空油+OR+依託咪酯+OR+禁毒+OR+毒品案+OR+海關+OR+戰時炸彈+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    
    configs = [
        # 第一排
        {"name": "禁毒/海關新聞", "type": "rss", "url": ANTIDRUG_RSS, "color": "#D946EF", 'backup_query': 'site:news.google.com 毒品'},
        {"name": "政府新聞（中文）", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_zh.xml", "color": "#E74C3C", 'backup_query': 'site:info.gov.hk'},
        {"name": "政府新聞（英文）", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_en.xml", "color": "#C0392B", 'backup_query': 'site:info.gov.hk'},
        {"name": "RTHK", "type": "rss", "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "color": "#FF9800", 'backup_query': 'site:news.rthk.hk'},
        
        # 第二排
        {"name": "on.cc 東網", "type": "rss", "url": f"{RSSHUB_BASE}/oncc/zh-hant/news", "color": "#7C3AED", 'backup_query': 'site:hk.on.cc'},
        {"name": "HK01", "type": "api_hk01", "url": "https://web-data.api.hk01.com/v2/feed/category/0", "color": "#2563EB", 'backup_query': 'site:hk01.com'},
        {"name": "星島即時", "type": "rss", "url": "https://www.stheadline.com/rss", "color": "#F97316", 'backup_query': 'site:stheadline.com'},
        {"name": "Now 新聞（本地）", "type": "now_api", "url": "", "color": "#16A34A", 'backup_query': 'site:news.now.com/home/local'},
        
        # 第三排
        {"name": "明報即時", "type": "rss", "url": "https://news.mingpao.com/rss/ins/all.xml", "color": "#7C3AED", 'backup_query': 'site:news.mingpao.com'},
        {"name": "i-CABLE 有線", "type": "rss", "url": "https://www.i-cable.com/feed", "color": "#A855F7", 'backup_query': 'site:i-cable.com'},
        {"name": "信報即時", "type": "rss", "url": f"{RSSHUB_BASE}/hkej/index", "color": "#64748B"},
        {"name": "文匯報", "type": "json_wenweipo", "url": "https://www.wenweipo.com/channels/wenweipo/hotlist/hours/24/stories.json", "color": "#BE123C"},
    ]
    results_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(fetch_single_source, conf, limit): conf for conf in configs}
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            results_map[res['name']] = res['data']
    return results_map, configs

# --- 4. UI 介面 ---

if 'selected_links' not in st.session_state: st.session_state.selected_links = set()
if 'show_preview' not in st.session_state: st.session_state.show_preview = False
if 'show_ai_summary' not in st.session_state: st.session_state.show_ai_summary = False

with st.sidebar:
    st.header("⚙️ 控制台")
    if st.button("🔄 立即刷新新聞", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.metric("已勾選新聞", f"{len(st.session_state.selected_links)} 篇")
    if st.button("🤖 AI綜合摘要", type="primary", use_container_width=True):
        if not st.session_state.selected_links:
            st.warning("請先勾選新聞！")
        else:
            st.session_state.show_ai_summary = True
            st.rerun()
    if st.button("📄 生成 TXT 文本", type="primary", use_container_width=True):
        if not st.session_state.selected_links:
            st.warning("請先勾選新聞！")
        else:
            st.session_state.show_preview = True
            st.rerun()
    if st.button("🗑️ 清空所有選擇", use_container_width=True):
        st.session_state.selected_links.clear()
        st.rerun()

news_data_map, source_configs = get_all_news_data_parallel(300)

@st.dialog("📄 生成結果預覽")
def show_txt_preview():
    all_flat = [n for items in news_data_map.values() for n in items]
    targets = [n for n in all_flat if n['link'] in st.session_state.selected_links]
    targets.sort(key=lambda x: x['timestamp'], reverse=True)
    
    final_text = ""
    with st.spinner("正在提取全文..."):
        for item in targets:
            content, _ = fetch_full_article(item['link'])
            final_text += f"{item['source']}：{item['title']}\n[{item['time_str']}]\n\n{content}\n\n{item['link']}\n\nEnds\n\n"
    
    st.text_area("內容 (可全選複製)：", value=final_text, height=500)
    if st.button("關閉視窗"):
        st.session_state.show_preview = False
        st.rerun()

if st.session_state.show_preview:
    show_txt_preview()


@st.dialog("🤖 AI綜合摘要")
def show_ai_summary():
    summary, error = get_ai_summary_for_selected(
        st.session_state.selected_links, 
        news_data_map
    )
    
    if error:
        st.error(error)
    else:
        st.markdown("### 📊 新聞綜合摘要")
        st.markdown(summary)
        st.divider()
        st.caption(f"綜合了 {len(st.session_state.selected_links)} 條新聞")
        
    if st.button("關閉"):
        st.session_state.show_ai_summary = False
        st.rerun()

if st.session_state.get('show_ai_summary'):
    show_ai_summary()


st.title("Tommy Sir 後援會之新聞監察系統")
rows = chunked(source_configs, 4)

for row in rows:
    cols = st.columns(len(row))
    for col, conf in zip(cols, row):
        with col:
            items = news_data_map.get(conf['name'], [])
            # 增加容器高度至 800px，減少滾動頻率
            with st.container(height=800, border=True):
                # 標題區 (由 CSS 控制 Sticky 固定，並確保不穿孔)
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
                            def update_selection(url=link):
                                if url in st.session_state.selected_links:
                                    st.session_state.selected_links.remove(url)
                                else:
                                    st.session_state.selected_links.add(url)
                            st.checkbox("", key=f"chk_{link}", value=is_selected, on_change=update_selection)
                        with c2:
                            badge = '<span class="new-badge">NEW!</span>' if is_new else ''
                            title_style = 'class="read-text"' if is_selected else ""
                            st.markdown(f'<div class="news-item-row">{badge}<a href="{link}" target="_blank" {title_style}>{html.escape(item["title"])}</a><div class="news-time">{item["time_str"]}</div></div>', unsafe_allow_html=True)
