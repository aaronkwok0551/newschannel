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

# --- 1. 頁面設定 ---
st.set_page_config(
    page_title="Tommy Sir 後援會之新聞監察系統",
    page_icon="📰",
    layout="wide"
)

# 自動刷新 (每 60 秒)
st_autorefresh(interval=60 * 1000, limit=None, key="news_autoupdate")

# --- CSS 樣式 (Clean Style - 無框線清單風格) ---
st.markdown("""
<style>
    /* 全局背景 */
    .stApp { background-color: #f8fafc; }

    /* 閃爍特效 - 針對 20 分鐘內的新聞 */
    @keyframes blinker { 50% { opacity: 0.4; } }
    .new-badge {
        color: #ef4444;
        font-weight: 800;
        animation: blinker 1.5s ease-in-out infinite;
        margin-right: 5px;
        font-size: 0.75em;
    }
    
    /* 已讀狀態 */
    .read-text {
        color: #94a3b8 !important;
        font-weight: normal !important;
        text-decoration: none !important;
    }
    
    /* 連結樣式 */
    a { text-decoration: none; color: #334155; font-weight: 600; transition: 0.2s; font-size: 0.95em; line-height: 1.4; }
    a:hover { color: #2563eb; }
    
    /* 來源標題 (卡片頭部) */
    .news-source-header { 
        font-size: 1rem; 
        font-weight: bold; 
        color: #1e293b; 
        padding: 12px 15px;
        background-color: #ffffff;
        border-bottom: 2px solid #f1f5f9;
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 1px 2px rgba(0,0,0,0.02);
    }
    
    /* 狀態標籤 */
    .status-badge {
        font-size: 0.65em;
        padding: 2px 8px;
        border-radius: 12px;
        font-weight: 500;
        background-color: #f1f5f9;
        color: #64748b;
    }
    
    /* 新聞項目列表樣式 (Clean Style) */
    .news-list-container {
        background-color: #ffffff;
        border-bottom-left-radius: 10px;
        border-bottom-right-radius: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        border: 1px solid #e2e8f0;
        border-top: none;
        padding-bottom: 5px;
        height: 100%;
    }

    .news-item-row {
        padding: 8px 12px;
        border-bottom: 1px solid #f1f5f9;
        transition: background-color 0.1s;
    }
    .news-item-row:hover {
        background-color: #f8fafc;
    }
    .news-item-row:last-child {
        border-bottom: none;
    }
    
    /* Checkbox 微調 */
    .stCheckbox { margin-bottom: 0px; margin-top: 2px; }
    div[data-testid="column"] { display: flex; align-items: start; }
    
    /* 調整 Expander/Dialog 樣式 */
    div[data-testid="stDialog"] { border-radius: 15px; }
    
    /* 生成內容區域樣式 */
    .generated-box {
        border: 2px solid #3b82f6;
        border-radius: 12px;
        padding: 20px;
        background-color: #ffffff;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
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

def chunked(lst, n):
    """將列表分割為大小為 n 的塊"""
    return [lst[i:i + n] for i in range(0, len(lst), n)]

def fetch_full_article(url):
    """ 抓取新聞正文 """
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        
        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'iframe', 'noscript']):
            tag.decompose()

        # 智慧抓取
        content_area = soup.find('div', class_=lambda x: x and ('article' in x.lower() or 'content' in x.lower() or 'news-text' in x.lower()))
        
        if content_area:
            paragraphs = content_area.find_all(['p', 'div'], recursive=False)
        else:
            paragraphs = soup.find_all('p')

        if not paragraphs:
            return "(無法自動提取全文，請點擊連結查看網頁版)"
            
        full_text = "\n".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 5])
        return full_text if len(full_text) > 30 else "(內容過短或受限)"
    except:
        return "(全文抓取失敗)"

def resolve_google_url(url):
    """ 還原 Google News 真實連結 """
    if "news.google.com" not in url:
        return url
    try:
        r = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=5)
        return r.url
    except:
        return url

def is_new_news(time_str):
    """ 判斷是否為 20 分鐘內的新聞 """
    try:
        if time_str == "最新": return True 
        pub_time = datetime.datetime.strptime(time_str, '%Y-%m-%d %H:%M')
        pub_time = HK_TZ.localize(pub_time)
        now = datetime.datetime.now(HK_TZ)
        diff = (now - pub_time).total_seconds() / 60
        return 0 <= diff <= 20
    except:
        return False

# --- 3. 雙重保險抓取機制 ---

def fetch_google_proxy(site_query, site_name, color):
    """ Plan B: Google News 代理模式 """
    query = urllib.parse.quote(site_query)
    rss_url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    
    try:
        feed = feedparser.parse(rss_url)
        news_list = []
        for entry in feed.entries[:10]:
            title = entry.title.rsplit(" - ", 1)[0]
            dt_str = "最新"
            if hasattr(entry, 'published_parsed'):
                dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
                dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
            
            news_list.append({
                'source': site_name,
                'title': title,
                'link': entry.link,
                'time': dt_str,
                'color': color,
                'method': 'Proxy' 
            })
        return news_list
    except:
        return []

def fetch_rss_or_api(config):
    data = []
    
    try:
        # 特別照料：Now 新聞 API (內部 JSON 接口)
        if config['type'] == 'now_api':
             api_url = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2?category=119&pageNo=1"
             r = requests.get(api_url, headers=HEADERS, timeout=8)
             data_list = r.json()
             
             # 處理 JSON 結構
             items_list = []
             if isinstance(data_list, list):
                 items_list = data_list
             elif isinstance(data_list, dict):
                 # 嘗試尋找常見的 key
                 for k in ['data', 'items', 'news']:
                     if k in data_list and isinstance(data_list[k], list):
                         items_list = data_list[k]
                         break
             
             for item in items_list[:10]:
                 title = item.get('newsTitle') or item.get('title')
                 news_id = item.get('newsId')
                 link = f"https://news.now.com/home/local/player?newsId={news_id}" if news_id else ""
                 
                 # 處理時間 (epoch ms)
                 pub_date = item.get('publishDate')
                 dt_str = "最新"
                 if pub_date:
                     try:
                        dt_obj = datetime.datetime.fromtimestamp(pub_date/1000, HK_TZ)
                        dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
                     except: pass

                 if title and link:
                    data.append({'source': config['name'], 'title': title, 'link': link, 'time': dt_str, 'color': config['color'], 'method': 'API'})

        # 通用 RSS 處理 (官方 RSS + RSSHub)
        elif config['type'] == 'rss':
            r = requests.get(config['url'], headers=HEADERS, timeout=8)
            feed = feedparser.parse(r.content)
            for entry in feed.entries[:10]:
                dt_str = "最新"
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
                    dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
                
                title = entry.title
                # 處理 Google News 標題後綴
                if "news.google.com" in config['url']:
                    title = title.rsplit(' - ', 1)[0]

                data.append({'source': config['name'], 'title': title, 'link': entry.link, 'time': dt_str, 'color': config['color'], 'method': 'RSS'})

    except Exception as e:
        print(f"Error fetching {config['name']}: {e}")
        data = []

    # --- Plan B (自動救援) ---
    if not data and config.get('backup_query'):
        data = fetch_google_proxy(config['backup_query'], config['name'], config['color'])
    
    return data

@st.cache_data(ttl=60)
def get_all_news_data():
    """ 定義所有新聞源 """
    
    # 您的私人 RSSHub 地址 (最重要！)
    RSSHUB_BASE = "https://rsshub-production-9dfc.up.railway.app" 
    
    # 禁毒新聞 Google RSS
    ANTIDRUG_RSS = "https://news.google.com/rss/search?q=毒品+OR+保安局+OR+鄧炳強+OR+緝毒+OR+太空油+OR+依託咪酯+OR+禁毒+OR+毒品案+OR+海關+OR+保安局+OR+鄧炳強+OR+戰時炸彈when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"

    configs = [
        # 第一行 (4個)
        {"name": "政府新聞（中文）", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_zh.xml", "color": "#E74C3C", 'backup_query': 'site:info.gov.hk'},
        {"name": "政府新聞（英文）", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_en.xml", "color": "#C0392B", 'backup_query': 'site:info.gov.hk'},
        {"name": "RTHK", "type": "rss", "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "color": "#FF9800", 'backup_query': 'site:news.rthk.hk'},
        {"name": "Now 新聞（本地）", "type": "now_api", "url": "", "color": "#16A34A", 'backup_query': 'site:news.now.com/home/local'},
        
        # 第二行 (4個)
        {"name": "HK01", "type": "rss", "url": f"{RSSHUB_BASE}/hk01/latest", "color": "#2563EB", 'backup_query': 'site:hk01.com'},
        {"name": "on.cc 東網", "type": "rss", "url": f"{RSSHUB_BASE}/oncc/zh-hant/news", "color": "#7C3AED", 'backup_query': 'site:hk.on.cc'},
        {"name": "星島即時", "type": "rss", "url": "https://www.stheadline.com/rss", "color": "#F97316", 'backup_query': 'site:stheadline.com'},
        {"name": "明報即時", "type": "rss", "url": "https://news.mingpao.com/rss/ins/all.xml", "color": "#7C3AED", 'backup_query': 'site:news.mingpao.com'},
        
        # 第三行 (4個)
        {"name": "i-CABLE 有線", "type": "rss", "url": "https://www.i-cable.com/feed", "color": "#A855F7", 'backup_query': 'site:i-cable.com'},
        {"name": "經濟日報", "type": "rss", "url": "https://www.hket.com/rss/hongkong", "color": "#7C3AED", 'backup_query': 'site:hket.com'},
        {"name": "信報即時", "type": "rss", "url": f"{RSSHUB_BASE}/hkej/index", "color": "#64748B", 'backup_query': 'site:hkej.com'},
        {"name": "巴士的報", "type": "rss", "url": "https://www.bastillepost.com/hongkong/feed", "color": "#7C3AED", 'backup_query': 'site:bastillepost.com'},
        
        # 額外加入禁毒新聞 (作為第13個，或您可以替換上面的某一個)
        # 這裡我先把它加在最後，如果您想放第一行，請自行調整順序
        {"name": "禁毒/海關新聞", "type": "rss", "url": ANTIDRUG_RSS, "color": "#D946EF"}, 
    ]

    results_map = {}
    ordered_names = []
    
    for conf in configs:
        items = fetch_rss_or_api(conf)
        results_map[conf['name']] = items
        ordered_names.append(conf)
        
    return results_map, ordered_names

# --- 4. 初始化 ---

if 'selected_links' not in st.session_state:
    st.session_state.selected_links = set()
if 'generated_text' not in st.session_state:
    st.session_state.generated_text = ""

# 抓取資料
news_data_map, source_configs = get_all_news_data()

# 扁平化列表 (供生成使用)
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
    
    # 生成按鈕
    if st.button("📄 生成 TXT 內容", type="primary", use_container_width=True):
        if select_count == 0:
            st.warning("請先勾選新聞！")
        else:
            with st.spinner("正在提取全文..."):
                final_txt = ""
                targets = [n for n in all_flat_news if n['link'] in st.session_state.selected_links]
                
                for item in targets:
                    real_link = resolve_google_url(item['link'])
                    content = fetch_full_article(real_link)
                    
                    final_txt += f"{item['source']}：{item['title']}\n"
                    final_txt += f"[{item['time']}]\n\n"
                    final_txt += f"{content}\n\n"
                    final_txt += f"{real_link}\n\n"
                    final_txt += "Ends\n\n"
                
                # 呼叫彈出視窗
                show_txt_preview(final_txt)

    # 清空按鈕
    if st.button("🗑️ 一鍵清空選擇", use_container_width=True):
        st.session_state.selected_links.clear()
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
            
            # 標題
            st.markdown(f"""
                <div class='news-source-header' style='border-left: 5px solid {conf['color']}; padding-left: 10px;'>
                    {name}
                    <span class='status-badge'>{len(items)} 則</span>
                </div>
            """, unsafe_allow_html=True)
            
            # 列表容器 (Clean Style)
            st.markdown('<div class="news-list-container">', unsafe_allow_html=True)
            
            if not items:
                st.markdown('<div style="padding:20px; text-align:center; color:#ccc;">暫無資料</div>', unsafe_allow_html=True)
            else:
                for item in items:
                    link = item['link']
                    is_new = is_new_news(item['time'])
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
                        
                        st.markdown(f"""
                            <div class="news-item-row">
                                {new_tag}
                                <a href="{link}" target="_blank" {text_style}>
                                    {item['title']}
                                </a><br>
                                <span style="font-size:0.8em; color:#888;">{item['time']}</span>
                            </div>
                        """, unsafe_allow_html=True)
            
            st.markdown('</div>', unsafe_allow_html=True)
