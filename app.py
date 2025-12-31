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

# --- CSS 樣式 (Clean Style) ---
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
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

# --- 2. 核心功能函式 ---

def chunked(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]

def fetch_full_article(url):
    """ 
    直接去新聞媒體網站攫取內容 
    """
    # 如果網址還是 Google 的轉址連結，表示還原失敗，這時無法抓取內容
    if "news.google.com" in url:
        return "(無法還原真實網址，無法抓取內文)"

    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        r.encoding = 'utf-8' # 大部分港台網站是 utf-8，若有亂碼可嘗試 r.apparent_encoding
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 移除干擾元素
        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'iframe', 'noscript', 'aside']):
            tag.decompose()

        # 智慧抓取：優先尋找常見的文章容器
        # 這些 class 是各大新聞網常見的內文容器名稱
        content_area = soup.find('div', class_=lambda x: x and any(term in x.lower() for term in ['article', 'content', 'news-text', 'story', 'post-body', 'main']))
        
        if content_area:
            paragraphs = content_area.find_all(['p', 'div'], recursive=False)
        else:
            # 備用方案：抓取所有 p 標籤
            paragraphs = soup.find_all('p')

        if not paragraphs:
            return "(無法自動提取全文，請點擊連結查看網頁版)"
            
        # 過濾太短的段落，並組合文字
        full_text = "\n\n".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 5])
        
        if len(full_text) < 30:
             return "(抓取到的內容過短，可能受限於付費牆或動態加載)"
             
        return full_text
    except Exception as e:
        return f"(全文抓取失敗: {str(e)})"

def resolve_google_url(url):
    """ 強力還原 Google News 真實連結 """
    if "news.google.com" not in url:
        return url
    try:
        # 使用 GET 請求並允許跳轉，這通常能拿到最終網址
        r = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=8)
        return r.url
    except:
        return url

def is_new_news(timestamp):
    """ 判斷是否為 20 分鐘內的新聞 (傳入 datetime object) """
    if not timestamp: return False
    try:
        now = datetime.datetime.now(HK_TZ)
        # 確保 timestamp 有時區資訊
        if timestamp.tzinfo is None:
            timestamp = HK_TZ.localize(timestamp)
        else:
            timestamp = timestamp.astimezone(HK_TZ)
            
        diff = (now - timestamp).total_seconds() / 60
        return 0 <= diff <= 20
    except:
        return False

# --- 3. 抓取邏輯 (含強制排序) ---

def fetch_google_proxy(site_query, site_name, color):
    """ Plan B: Google News 代理模式 """
    query = urllib.parse.quote(site_query)
    rss_url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    try:
        feed = feedparser.parse(rss_url)
        news_list = []
        for entry in feed.entries[:15]: # 抓多一點再來排序
            title = entry.title.rsplit(" - ", 1)[0].strip()
            
            # 解析時間
            dt_obj = datetime.datetime.now(HK_TZ) # 預設當前時間
            if hasattr(entry, 'published_parsed'):
                dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
            
            dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
            
            news_list.append({
                'source': site_name, 
                'title': title, 
                'link': entry.link, 
                'time_str': dt_str,
                'timestamp': dt_obj, # 用於排序
                'color': color, 
                'method': 'Proxy'
            })
            
        # 強制按時間排序 (新 -> 舊)
        news_list.sort(key=lambda x: x['timestamp'], reverse=True)
        return news_list[:10] # 只回傳前 10 條
    except:
        return []

def fetch_rss_or_api(config):
    data = []
    try:
        if config['type'] == 'now_api':
             api_url = "https://newsapi1.now.com/pccw-news-api/api/getNewsListv2?category=119&pageNo=1"
             r = requests.get(api_url, headers=HEADERS, timeout=8)
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
                 
                 # 解析時間
                 pub_date = item.get('publishDate')
                 if pub_date:
                     dt_obj = datetime.datetime.fromtimestamp(pub_date/1000, HK_TZ)
                 else:
                     dt_obj = datetime.datetime.now(HK_TZ)
                     
                 dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')

                 if title and link:
                    data.append({
                        'source': config['name'], 
                        'title': title, 
                        'link': link, 
                        'time_str': dt_str,
                        'timestamp': dt_obj, # 用於排序
                        'color': config['color'], 
                        'method': 'API'
                    })

        elif config['type'] == 'rss':
            r = requests.get(config['url'], headers=HEADERS, timeout=8)
            feed = feedparser.parse(r.content)
            for entry in feed.entries:
                # 解析時間
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
                else:
                    dt_obj = datetime.datetime.now(HK_TZ) # 若無時間則視為最新
                
                dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
                
                title = entry.title.strip()
                if "news.google.com" in config['url']:
                    title = title.rsplit(' - ', 1)[0].strip()

                data.append({
                    'source': config['name'], 
                    'title': title, 
                    'link': entry.link, 
                    'time_str': dt_str, 
                    'timestamp': dt_obj, # 用於排序
                    'color': config['color'], 
                    'method': 'RSS'
                })

    except Exception as e:
        data = []

    # 如果 Plan A 失敗，切換 Plan B
    if not data and config.get('backup_query'):
        data = fetch_google_proxy(config['backup_query'], config['name'], config['color'])
    
    # 統一強制排序：由新到舊
    data.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return data[:10] # 限制回傳 10 條

@st.cache_data(ttl=60)
def get_all_news_data():
    RSSHUB_BASE = "https://rsshub-production-9dfc.up.railway.app" 
    ANTIDRUG_RSS = "https://news.google.com/rss/search?q=毒品+OR+保安局+OR+鄧炳強+OR+緝毒+OR+太空油+OR+依託咪酯+OR+禁毒+OR+毒品案+OR+海關+OR+保安局+OR+鄧炳強+OR+戰時炸彈+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"

    configs = [
        {"name": "禁毒/海關新聞", "type": "rss", "url": ANTIDRUG_RSS, "color": "#D946EF", 'backup_query': 'site:news.google.com 毒品'},
        {"name": "政府新聞（中文）", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_zh.xml", "color": "#E74C3C", 'backup_query': 'site:info.gov.hk'},
        {"name": "政府新聞（英文）", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_en.xml", "color": "#C0392B", 'backup_query': 'site:info.gov.hk'},
        {"name": "RTHK", "type": "rss", "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "color": "#FF9800", 'backup_query': 'site:news.rthk.hk'},
        
        {"name": "Now 新聞（本地）", "type": "now_api", "url": "", "color": "#16A34A", 'backup_query': 'site:news.now.com/home/local'},
        {"name": "HK01", "type": "rss", "url": f"{RSSHUB_BASE}/hk01/latest", "color": "#2563EB", 'backup_query': 'site:hk01.com'},
        {"name": "on.cc 東網", "type": "rss", "url": f"{RSSHUB_BASE}/oncc/zh-hant/news", "color": "#7C3AED", 'backup_query': 'site:hk.on.cc'},
        {"name": "星島即時", "type": "rss", "url": "https://www.stheadline.com/rss", "color": "#F97316", 'backup_query': 'site:stheadline.com'},
        
        {"name": "明報即時", "type": "rss", "url": "https://news.mingpao.com/rss/ins/all.xml", "color": "#7C3AED", 'backup_query': 'site:news.mingpao.com'},
        {"name": "i-CABLE 有線", "type": "rss", "url": "https://www.i-cable.com/feed", "color": "#A855F7", 'backup_query': 'site:i-cable.com'},
        {"name": "經濟日報", "type": "rss", "url": "https://www.hket.com/rss/hongkong", "color": "#7C3AED", 'backup_query': 'site:hket.com'},
        {"name": "信報即時", "type": "rss", "url": f"{RSSHUB_BASE}/hkej/index", "color": "#64748B", 'backup_query': 'site:hkej.com'},
        
        {"name": "巴士的報", "type": "rss", "url": "https://www.bastillepost.com/hongkong/feed", "color": "#7C3AED", 'backup_query': 'site:bastillepost.com'},
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
            with st.spinner("正在前往媒體網站抓取全文..."):
                final_txt = ""
                targets = [n for n in all_flat_news if n['link'] in st.session_state.selected_links]
                
                # 再次確保生成順序也是按時間排序 (可選)
                targets.sort(key=lambda x: x['timestamp'], reverse=True)
                
                for item in targets:
                    # 1. 強制還原 Google 連結到真實媒體網站
                    real_link = resolve_google_url(item['link'])
                    
                    # 2. 進入真實網站抓取內文 (不使用 RSS 摘要)
                    content = fetch_full_article(real_link)
                    
                    final_txt += f"{item['source']}：{item['title']}\n"
                    final_txt += f"[{item['time_str']}]\n\n"
                    final_txt += f"{content}\n\n"
                    final_txt += f"{real_link}\n\n"
                    final_txt += "Ends\n\n"
                show_txt_preview(final_txt)

    if st.button("🗑️ 一鍵清空選擇", use_container_width=True):
        st.session_state.selected_links.clear()
        keys_to_clear = [key for key in st.session_state.keys() if key.startswith("chk_")]
        for key in keys_to_clear:
            del st.session_state[key]
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
