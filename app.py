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
    
    @keyframes blinker { 50% { opacity: 0.4; } }
    .new-badge {
        color: #ef4444;
        font-weight: 800;
        animation: blinker 1.5s ease-in-out infinite;
        margin-right: 5px;
        font-size: 0.75em;
    }
    
    .read-text { color: #9ca3af !important; font-weight: normal !important; text-decoration: none !important; }
    a { text-decoration: none; color: #334155; font-weight: 600; transition: 0.2s; font-size: 0.95em; line-height: 1.4; }
    a:hover { color: #2563eb; }
    
    .news-source-header { 
        font-size: 1rem; font-weight: bold; color: #1e293b; padding: 12px 15px;
        background-color: #ffffff; border-bottom: 2px solid #f1f5f9;
        border-top-left-radius: 10px; border-top-right-radius: 10px;
        display: flex; justify-content: space-between; align-items: center;
        box-shadow: 0 1px 2px rgba(0,0,0,0.02);
    }
    
    .status-badge { font-size: 0.65em; padding: 2px 8px; border-radius: 12px; font-weight: 500; background-color: #f1f5f9; color: #64748b; }
    
    .news-list-container {
        background-color: #ffffff; border-bottom-left-radius: 10px; border-bottom-right-radius: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; border-top: none;
        padding-bottom: 5px; height: 100%;
    }

    .news-item-row { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; transition: background-color 0.1s; }
    .news-item-row:hover { background-color: #f8fafc; }
    .news-item-row:last-child { border-bottom: none; }
    
    .stCheckbox { margin-bottom: 0px; margin-top: 2px; }
    div[data-testid="column"] { display: flex; align-items: start; }
    div[data-testid="stDialog"] { border-radius: 15px; }
    .generated-box { border: 2px solid #3b82f6; border-radius: 12px; padding: 20px; background-color: #ffffff; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); margin-bottom: 20px; }
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

# --- 2. 核心功能函式 ---

def chunked(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]

def resolve_google_url(url):
    """ 強力還原 Google News 真實連結 """
    if "news.google.com" not in url:
        return url
    
    try:
        # Google News 需要 Cookies 才能正確跳轉
        session = requests.Session()
        session.headers.update(HEADERS)
        # 訪問頁面，允許跳轉
        r = session.get(url, allow_redirects=True, timeout=8)
        return r.url
    except:
        return url

def fetch_full_article(url):
    """ 抓取新聞正文 (針對不同網站優化) """
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        r.encoding = 'utf-8' # 自動檢測編碼通常比較好，但中文網頁utf-8居多
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 移除干擾元素
        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'iframe', 'noscript', 'aside', 'form', 'button']):
            tag.decompose()

        # --- 針對特定網站的抓取邏輯 ---
        paragraphs = []
        
        # 1. 政府新聞網 (Info.gov.hk)
        if "info.gov.hk" in url:
            # 政府新聞稿通常在 id="pressrelease" 或 class="content"
            content_div = soup.find(id="pressrelease") or soup.find(class_="content")
            if content_div:
                paragraphs = content_div.find_all('p')
        
        # 2. 一般新聞網站 (智慧判斷)
        if not paragraphs:
            content_area = soup.find('div', class_=lambda x: x and any(term in x.lower() for term in ['article', 'content', 'news-text', 'story', 'post-body', 'main-text']))
            if content_area:
                paragraphs = content_area.find_all(['p'], recursive=False)
                # 如果第一層沒 p，找下一層
                if not paragraphs:
                    paragraphs = content_area.find_all('p')
        
        # 3. 兜底方案
        if not paragraphs:
            paragraphs = soup.find_all('p')

        # 過濾垃圾內容
        clean_text = []
        for p in paragraphs:
            text = p.get_text().strip()
            # 排除太短的行、版權聲明等
            if len(text) > 10 and "Copyright" not in text and "版權所有" not in text:
                clean_text.append(text)

        if not clean_text:
            return "(無法自動提取全文，請點擊連結查看網頁版)"
            
        full_text = "\n\n".join(clean_text)
        return full_text
    except Exception as e:
        return f"(全文抓取失敗: {str(e)})"

def is_new_news(timestamp):
    """ 判斷是否為 20 分鐘內的新聞 """
    if not timestamp: return False
    try:
        now = datetime.datetime.now(HK_TZ)
        if timestamp.tzinfo is None:
            timestamp = HK_TZ.localize(timestamp)
        else:
            timestamp = timestamp.astimezone(HK_TZ)
        diff = (now - timestamp).total_seconds() / 60
        return 0 <= diff <= 20
    except:
        return False

# --- 3. 抓取邏輯 (並行處理版) ---

def fetch_google_proxy(site_query, site_name, color):
    """ Plan B: Google News 代理 """
    query = urllib.parse.quote(site_query)
    rss_url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    try:
        feed = feedparser.parse(rss_url)
        news_list = []
        for entry in feed.entries[:15]:
            title = entry.title.rsplit(" - ", 1)[0].strip()
            # 解析時間
            dt_obj = datetime.datetime.now(HK_TZ)
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
            
            dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
            
            news_list.append({
                'source': site_name, 
                'title': title, 
                'link': entry.link, 
                'time_str': dt_str,
                'timestamp': dt_obj,
                'color': color, 
                'method': 'Proxy'
            })
        news_list.sort(key=lambda x: x['timestamp'], reverse=True)
        return news_list[:10]
    except:
        return []

def fetch_single_source(config):
    """ 單一來源抓取函數 (用於並行) """
    data = []
    try:
        # Now API
        if config['type'] == 'now_api':
             api_url = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2?category=119&pageNo=1"
             r = requests.get(api_url, headers=HEADERS, timeout=10)
             data_list = r.json()
             items_list = []
             if isinstance(data_list, list): items_list = data_list
             elif isinstance(data_list, dict):
                 for k in ['data', 'items', 'news']:
                     if k in data_list and isinstance(data_list[k], list):
                         items_list = data_list[k]; break
             
             for item in items_list:
                 title = (item.get('newsTitle') or item.get('title') or "").strip()
                 news_id = item.get('newsId')
                 link = f"https://news.now.com/home/local/player?newsId={news_id}" if news_id else ""
                 pub_date = item.get('publishDate')
                 if pub_date:
                     dt_obj = datetime.datetime.fromtimestamp(pub_date/1000, HK_TZ)
                 else:
                     dt_obj = datetime.datetime.now(HK_TZ)
                 
                 if title and link:
                    data.append({
                        'source': config['name'], 'title': title, 'link': link, 
                        'time_str': dt_obj.strftime('%Y-%m-%d %H:%M'), 
                        'timestamp': dt_obj, 
                        'color': config['color'], 'method': 'API'
                    })

        # RSS
        elif config['type'] == 'rss':
            r = requests.get(config['url'], headers=HEADERS, timeout=10)
            feed = feedparser.parse(r.content)
            for entry in feed.entries:
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
                else:
                    dt_obj = datetime.datetime.now(HK_TZ)
                
                title = entry.title.strip()
                if "news.google.com" in config['url']:
                    title = title.rsplit(' - ', 1)[0].strip()

                data.append({
                    'source': config['name'], 'title': title, 'link': entry.link, 
                    'time_str': dt_obj.strftime('%Y-%m-%d %H:%M'), 
                    'timestamp': dt_obj, 
                    'color': config['color'], 'method': 'RSS'
                })

    except Exception:
        data = []

    # Failover
    if not data and config.get('backup_query'):
        data = fetch_google_proxy(config['backup_query'], config['name'], config['color'])
    
    # Sort
    data.sort(key=lambda x: x['timestamp'], reverse=True)
    return config['name'], data[:10]

@st.cache_data(ttl=60)
def get_all_news_data_parallel():
    """ 並行抓取所有新聞 (大幅提升速度) """
    RSSHUB_BASE = "https://rsshub-production-9dfc.up.railway.app" 
    ANTIDRUG_RSS = "https://news.google.com/rss/search?q=毒品+OR+保安局+OR+鄧炳強+OR+緝毒+OR+太空油+OR+依託咪酯+OR+禁毒+OR+毒品案+OR+海關+OR+保安局+OR+鄧炳強+OR+戰時炸彈+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"

    configs = [
        # Row 1
        {"name": "禁毒/海關新聞", "type": "rss", "url": ANTIDRUG_RSS, "color": "#D946EF", 'backup_query': 'site:news.google.com 毒品'},
        {"name": "政府新聞（中文）", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_zh.xml", "color": "#E74C3C", 'backup_query': 'site:info.gov.hk'},
        {"name": "政府新聞（英文）", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_en.xml", "color": "#C0392B", 'backup_query': 'site:info.gov.hk'},
        {"name": "RTHK", "type": "rss", "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "color": "#FF9800", 'backup_query': 'site:news.rthk.hk'},
        # Row 2
        {"name": "Now 新聞（本地）", "type": "now_api", "url": "", "color": "#16A34A", 'backup_query': 'site:news.now.com/home/local'},
        {"name": "HK01", "type": "rss", "url": f"{RSSHUB_BASE}/hk01/latest", "color": "#2563EB", 'backup_query': 'site:hk01.com'},
        {"name": "on.cc 東網", "type": "rss", "url": f"{RSSHUB_BASE}/oncc/zh-hant/news", "color": "#7C3AED", 'backup_query': 'site:hk.on.cc'},
        {"name": "星島即時", "type": "rss", "url": "https://www.stheadline.com/rss", "color": "#F97316", 'backup_query': 'site:stheadline.com'},
        # Row 3
        {"name": "明報即時", "type": "rss", "url": "https://news.mingpao.com/rss/ins/all.xml", "color": "#7C3AED", 'backup_query': 'site:news.mingpao.com'},
        {"name": "i-CABLE 有線", "type": "rss", "url": "https://www.i-cable.com/feed", "color": "#A855F7", 'backup_query': 'site:i-cable.com'},
        {"name": "經濟日報", "type": "rss", "url": "https://www.hket.com/rss/hongkong", "color": "#7C3AED", 'backup_query': 'site:hket.com'},
        {"name": "信報即時", "type": "rss", "url": f"{RSSHUB_BASE}/hkej/index", "color": "#64748B", 'backup_query': 'site:hkej.com'},
        # Extra
        {"name": "巴士的報", "type": "rss", "url": "https://www.bastillepost.com/hongkong/feed", "color": "#7C3AED", 'backup_query': 'site:bastillepost.com'},
    ]

    results_map = {}
    
    # 使用 ThreadPoolExecutor 進行並行抓取
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_source = {executor.submit(fetch_single_source, conf): conf for conf in configs}
        for future in concurrent.futures.as_completed(future_to_source):
            try:
                name, data = future.result()
                results_map[name] = data
            except Exception as e:
                print(f"Parallel fetch error: {e}")

    return results_map, configs

# --- 4. 初始化 ---

if 'selected_links' not in st.session_state:
    st.session_state.selected_links = set()

# 執行並行抓取
news_data_map, source_configs = get_all_news_data_parallel()

# 扁平化列表
all_flat_news = []
for name, items in news_data_map.items():
    all_flat_news.extend(items)

# --- 5. UI 佈局 ---

# Popup Dialog
@st.dialog("📄 生成結果預覽")
def show_txt_preview(txt_content):
    st.text_area("內容 (可全選複製)：", value=txt_content, height=500)
    if st.button("關閉視窗"):
        st.rerun()

# 側邊欄
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
            with st.spinner("正在提取全文..."):
                final_txt = ""
                # 排序選中的新聞 (按時間)
                targets = [n for n in all_flat_news if n['link'] in st.session_state.selected_links]
                targets.sort(key=lambda x: x['timestamp'], reverse=True)
                
                for item in targets:
                    real_link = resolve_google_url(item['link'])
                    content = fetch_full_article(real_link)
                    
                    final_txt += f"{item['source']}：{item['title']}\n"
                    final_txt += f"[{item['time_str']}]\n\n"
                    final_txt += f"{content}\n\n"
                    final_txt += f"{real_link}\n\n"
                    final_txt += "Ends\n\n"
                show_txt_preview(final_txt)

    if st.button("🗑️ 一鍵清空選擇", use_container_width=True):
        st.session_state.selected_links.clear()
        # 強制重置所有 Checkbox
        keys_to_clear = [key for key in st.session_state.keys() if key.startswith("chk_")]
        for key in keys_to_clear:
            st.session_state[key] = False
        st.rerun()

# 主畫面
st.title("Tommy Sir 後援會之新聞監察系統")

# 新聞網格 (4 欄)
cols_per_row = 4
rows = chunked(source_configs, cols_per_row)

for row in rows:
    cols = st.columns(len(row))
    for col, conf in zip(cols, row):
        with col:
            name = conf['name']
            items = news_data_map.get(name, [])
            st.markdown(f"""
                <div class='news-source-header' style='border-left: 5px solid {conf['color']}; padding-left: 10px;'>
                    {name}
                    <span class='status-badge'>{len(items)} 則</span>
                </div>
            """, unsafe_allow_html=True)
            st.markdown('<div class="news-list-container">', unsafe_allow_html=True)
            if not items:
                st.markdown('<div style="padding:20px; text-align:center; color:#ccc;">暫無資料</div>', unsafe_allow_html=True)
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
                        new_tag = '<span class="new-badge">NEW!</span>' if is_new else ''
                        text_style = 'class="read-text"' if is_selected else ""
                        item_html = f'<div class="news-item-row">{new_tag}<a href="{link}" target="_blank" {text_style}>{item["title"]}</a><div class="news-time">{item["time_str"]}</div></div>'
                        st.markdown(item_html, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
