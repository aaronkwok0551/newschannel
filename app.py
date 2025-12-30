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

# 設定預設編碼，避免輸出中文亂碼
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

# --- CSS 樣式 (移植自您的 HTML 模擬版) ---
st.markdown("""
<style>
    /* 閃爍特效 - 針對 20 分鐘內的新聞 */
    @keyframes blinker {
        50% { opacity: 0.4; }
    }
    .new-badge {
        color: #ef4444;
        font-weight: 800;
        animation: blinker 1.5s ease-in-out infinite;
        margin-right: 5px;
        font-size: 0.8em;
    }
    
    /* 已讀狀態 (灰色) */
    .read-text {
        color: #9ca3af !important;
        font-weight: normal !important;
        text-decoration: none !important;
    }
    
    /* 標題連結 */
    a { text-decoration: none; color: #1e293b; transition: 0.2s; }
    a:hover { color: #ef4444; }
    
    /* 卡片標題 */
    .news-source-header { 
        font-size: 1.1em; 
        font-weight: bold; 
        color: #2c3e50; 
        margin-top: 10px; 
        margin-bottom: 10px;
        padding-bottom: 5px;
        border-bottom: 1px solid #e2e8f0;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    
    /* 狀態標籤 (顯示是直連還是代理) */
    .status-badge {
        font-size: 0.6em;
        padding: 2px 6px;
        border-radius: 4px;
        font-weight: normal;
        background-color: #f1f5f9;
        color: #64748b;
    }
    
    /* 調整 Checkbox 對齊 */
    .stCheckbox { margin-bottom: 0px; }
    div[data-testid="column"] { display: flex; align-items: start; }
    
    /* 生成內容區域樣式 */
    .generated-box {
        border: 2px solid #3b82f6;
        border-radius: 10px;
        padding: 20px;
        background-color: #eff6ff;
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

def fetch_full_article(url):
    """ 抓取新聞正文 (用於生成 TXT) """
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 移除干擾元素
        for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'iframe', 'noscript']):
            tag.decompose()

        # 智慧抓取：優先尋找常見的文章容器 class
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
    """ 還原 Google News 的轉址連結為真實連結 """
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
        pub_time = datetime.datetime.strptime(time_str, '%Y-%m-%d %H:%M')
        pub_time = HK_TZ.localize(pub_time)
        now = datetime.datetime.now(HK_TZ)
        diff = (now - pub_time).total_seconds() / 60
        return 0 <= diff <= 20
    except:
        return False

# --- 3. 雙重保險抓取機制 (Plan A: RSS/API -> Plan B: Google Proxy) ---

def fetch_google_proxy(site_query, site_name, color):
    """ Plan B: Google News 代理模式 (救援用) """
    query = urllib.parse.quote(site_query)
    rss_url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    
    try:
        feed = feedparser.parse(rss_url)
        news_list = []
        for entry in feed.entries[:10]: # 取前 10 條
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
    """ 
    智能分配器：
    優先嘗試官方 API 或 RSSHub，若失敗則自動切換至 Google Proxy
    """
    data = []
    
    try:
        # --- Plan A: 官方源或 RSSHub ---
        if config['type'] == 'api_hk01':
            r = requests.get("https://web-data.api.hk01.com/v2/feed/category/0", headers=HEADERS, timeout=5)
            items = r.json().get('items', [])[:10]
            for item in items:
                raw = item.get('data', {})
                dt_str = datetime.datetime.fromtimestamp(raw.get('publishTime'), HK_TZ).strftime('%Y-%m-%d %H:%M')
                data.append({'source': config['name'], 'title': raw.get('title'), 'link': raw.get('publishUrl'), 'time': dt_str, 'color': config['color'], 'method': 'API'})
                
        elif config['type'] == 'api_now':
             r = requests.get("https://news.now.com/home/local", headers=HEADERS, timeout=5)
             soup = BeautifulSoup(r.text, 'html.parser')
             items = soup.select('.newsLeading') + soup.select('.news-list-item')
             for item in items[:10]:
                 link_tag = item.select_one('a')
                 if link_tag:
                     link = "https://news.now.com" + link_tag['href']
                     title = link_tag.get_text(strip=True)
                     data.append({'source': config['name'], 'title': title, 'link': link, 'time': "最新", 'color': config['color'], 'method': 'Web'})

        elif config['type'] == 'rss':
            r = requests.get(config['url'], headers=HEADERS, timeout=5)
            feed = feedparser.parse(r.content)
            for entry in feed.entries[:10]:
                dt_str = "最新"
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    dt_obj = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), UTC_TZ).astimezone(HK_TZ)
                    dt_str = dt_obj.strftime('%Y-%m-%d %H:%M')
                data.append({'source': config['name'], 'title': entry.title, 'link': entry.link, 'time': dt_str, 'color': config['color'], 'method': 'RSS'})

    except Exception:
        data = []

    # --- Plan B: 救援模式 ---
    if not data:
        data = fetch_google_proxy(config['backup_query'], config['name'], config['color'])
    
    return data

@st.cache_data(ttl=60)
def get_all_news_data():
    """ 獲取所有新聞並快取 """
    # 這是您的完整新聞源清單
    configs = [
        # Row 1
        {'name': '政府新聞(中)', 'type': 'rss', 'url': 'https://www.info.gov.hk/gia/rss/general_zh.xml', 'color': '#E74C3C', 'backup_query': 'site:info.gov.hk'},
        {'name': '政府新聞(英)', 'type': 'rss', 'url': 'https://www.info.gov.hk/gia/rss/general_en.xml', 'color': '#C0392B', 'backup_query': 'site:info.gov.hk'},
        {'name': '香港電台', 'type': 'rss', 'url': 'https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml', 'color': '#FF9800', 'backup_query': 'site:news.rthk.hk'},
        {'name': 'Now 新聞', 'type': 'api_now', 'color': '#2563EB', 'backup_query': 'site:news.now.com/home/local'},
        # Row 2
        {'name': 'HK01', 'type': 'api_hk01', 'color': '#0ea5e9', 'backup_query': 'site:hk01.com'},
        {'name': '東網 on.cc', 'type': 'rss', 'url': 'https://rsshub.app/oncc/zh-hant/news', 'color': '#111827', 'backup_query': 'site:hk.on.cc'},
        {'name': '無線新聞', 'type': 'rss', 'url': 'https://rsshub.app/tvb/news/tc', 'color': '#16a34a', 'backup_query': 'site:news.tvb.com/tc/local'},
        {'name': '信報', 'type': 'rss', 'url': 'https://rsshub.app/hkej/index', 'color': '#7c3aed', 'backup_query': 'site:hkej.com'},
        # Row 3
        {'name': '星島日報', 'type': 'rss', 'url': 'https://rsshub.app/stheadline/std/realtime', 'color': '#f97316', 'backup_query': 'site:stheadline.com'},
        {'name': '有線新聞', 'type': 'rss', 'url': 'https://rsshub.app/icable/all', 'color': '#dc2626', 'backup_query': 'site:i-cable.com'},
        {'name': '商台 881903', 'type': 'google_only', 'color': '#F1C40F', 'backup_query': 'site:881903.com'},
    ]

    results_map = {}
    ordered_names = []
    
    for conf in configs:
        if conf.get('type') == 'google_only':
            items = fetch_google_proxy(conf['backup_query'], conf['name'], conf['color'])
        else:
            items = fetch_rss_or_api(conf)
        
        results_map[conf['name']] = items
        ordered_names.append(conf) # 保存順序配置
        
    return results_map, ordered_names

# --- 4. 初始化 Session ---

if 'selected_links' not in st.session_state:
    st.session_state.selected_links = set()
if 'generated_text' not in st.session_state:
    st.session_state.generated_text = ""

# 執行資料抓取
news_data_map, source_configs = get_all_news_data()

# 建立扁平化新聞列表 (用於生成 TXT 時查找)
all_flat_news = []
for name, items in news_data_map.items():
    all_flat_news.extend(items)

# --- 5. UI 佈局 ---

# 左側側邊欄 (Sidebar)
with st.sidebar:
    st.header("⚙️ 控制台")
    
    # 顯示時鐘
    st.caption(f"最後更新: {datetime.datetime.now(HK_TZ).strftime('%H:%M:%S')}")
    
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
            with st.spinner("正在智能提取全文..."):
                final_txt = ""
                # 找出被勾選的新聞
                targets = [n for n in all_flat_news if n['link'] in st.session_state.selected_links]
                
                for item in targets:
                    real_link = resolve_google_url(item['link'])
                    content = fetch_full_article(real_link)
                    
                    final_txt += f"{item['source']}：{item['title']}\n"
                    final_txt += f"[{item['time']}]\n\n"
                    final_txt += f"{content}\n\n"
                    final_txt += f"{real_link}\n\n"
                    final_txt += "Ends\n\n"
                
                st.session_state.generated_text = final_txt
                st.rerun() # 觸發彈窗顯示

    if st.button("🗑️ 一鍵清空選擇", use_container_width=True):
        st.session_state.selected_links.clear()
        st.session_state.generated_text = ""
        st.rerun()

# 主標題
st.title("Tommy Sir 後援會之新聞監察系統")

# 生成內容顯示 (模擬 Popup)
if st.session_state.generated_text:
    st.markdown('<div class="generated-box">', unsafe_allow_html=True)
    st.success("✅ 生成完成！請複製下方內容：")
    st.text_area("", value=st.session_state.generated_text, height=400)
    if st.button("❌ 關閉預覽"):
        st.session_state.generated_text = ""
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# 新聞網格 (4 欄佈局)
grid_cols = st.columns(4)

for idx, conf in enumerate(source_configs):
    with grid_cols[idx % 4]:
        name = conf['name']
        items = news_data_map.get(name, [])
        
        # 標題區
        method = items[0]['method'] if items else "N/A"
        badge_text = "G-Proxy" if method == "Proxy" else "Direct"
        st.markdown(f"""
            <div class='news-source-header' style='border-left: 5px solid {conf['color']}; padding-left: 10px;'>
                {name}
                <span class='status-badge'>{badge_text}</span>
            </div>
        """, unsafe_allow_html=True)
        
        if not items:
            st.caption("暫無資料 (連線重試中...)")
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
                        {new_tag}
                        <a href="{link}" target="_blank" {text_style}>
                            <b>{item['title']}</b>
                        </a><br>
                        <span style="font-size:0.8em; color:#888;">{item['time']}</span>
                    """, unsafe_allow_html=True)
