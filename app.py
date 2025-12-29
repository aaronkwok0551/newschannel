import streamlit as st
import feedparser
import datetime
import pytz
import re
from bs4 import BeautifulSoup

# --- 1. 頁面基本設定 ---
st.set_page_config(page_title="香港新聞聚合", layout="wide", page_icon="📰")

# --- 2. CSS 樣式 (解決鋸齒問題的核心) ---
# 使用 HTML Table 強制對齊：時間欄固定 85px，來源欄固定 110px
st.markdown("""
<style>
    /* 全局字體優化 */
    body { font-family: "Microsoft JhengHei", "PingFang TC", sans-serif; }
    
    /* 表格樣式 */
    table { width: 100%; border-collapse: collapse; margin-bottom: 25px; }
    
    /* 表格行樣式 */
    tr { border-bottom: 1px solid #eee; transition: background-color 0.2s; }
    tr:hover { background-color: #f9f9f9; }
    
    /* 儲存格樣式 */
    td { padding: 10px 12px; vertical-align: middle; }
    
    /* 強制對齊的關鍵：固定寬度 */
    .col-time { 
        width: 85px; 
        min-width: 85px; 
        color: #666; 
        font-size: 0.9em; 
        white-space: nowrap; 
        font-family: monospace; /* 等寬字體讓數字對齊更整齊 */
    }
    .col-source { 
        width: 110px; 
        min-width: 110px; 
        font-weight: bold; 
        white-space: nowrap; 
    }
    .col-title { 
        width: auto; 
    }
    
    /* 來源標籤樣式 */
    .badge { 
        display: inline-block; 
        padding: 4px 0; 
        border-radius: 4px; 
        color: white; 
        font-size: 0.85rem; 
        text-align: center;
        width: 90px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.1);
    }
    
    /* 連結樣式 */
    a.news-link { 
        text-decoration: none; 
        color: #262730; 
        font-size: 1.05rem; 
        line-height: 1.4;
        transition: 0.2s; 
    }
    a.news-link:hover { 
        color: #ff4b4b; 
        text-decoration: underline; 
    }
    
    /* 標題裝飾 */
    h3 { 
        margin-top: 25px; 
        border-left: 5px solid #ff4b4b; 
        padding-left: 12px; 
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. 工具函數 ---

# 設定香港時區
hk_tz = pytz.timezone('Asia/Hong_Kong')

def clean_html_title(raw_html):
    """強力清除標題中的 HTML 標籤 (解決 <a href...> 顯示問題)"""
    if not raw_html:
        return ""
    # 使用 BeautifulSoup 清除標籤
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text()
    # 再次確保沒有遺留的 tags
    cleanr = re.compile('<.*?>')
    text = re.sub(cleanr, '', text)
    # 移除多餘的空白
    return " ".join(text.split())

def parse_feeds(feed_list, filter_today=False):
    """讀取並解析 RSS"""
    articles = []
    now_hk = datetime.datetime.now(hk_tz)

    for source_name, url, color in feed_list:
        try:
            feed = feedparser.parse(url)
            # 如果 RSS 讀取失敗或格式錯誤
            if not feed.entries:
                continue

            for entry in feed.entries:
                # 1. 處理時間
                dt_obj = None
                time_str = ""
                
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    dt_utc = datetime.datetime(*entry.published_parsed[:6], tzinfo=pytz.utc)
                    dt_hk = dt_utc.astimezone(hk_tz)
                    dt_obj = dt_hk
                    time_str = dt_hk.strftime('%H:%M')
                else:
                    # 如果沒有時間，使用當前時間作為佔位符，但標記為未知
                    dt_obj = now_hk
                    time_str = "--:--"

                # 2. 過濾邏輯 (如果是政府新聞稿，只留今天的)
                if filter_today:
                    if dt_obj.date() != now_hk.date():
                        continue # 跳過非今天的新聞

                # 3. 處理標題 (清洗 HTML)
                title_clean = clean_html_title(entry.title)
                
                # 4. 存入列表
                articles.append({
                    'source': source_name,
                    'title': title_clean,
                    'link': entry.link,
                    'time': time_str,
                    'timestamp': dt_obj, # 用於排序
                    'color': color
                })
        except Exception as e:
            # 靜默失敗，避免影響其他來源
            print(f"Error fetching {source_name}: {e}")
            continue

    # 按時間倒序排列 (最新的在最上面)
    articles.sort(key=lambda x: x['timestamp'], reverse=True)
    return articles

def render_news_table(articles):
    """將新聞渲染為 HTML 表格"""
    if not articles:
        return "<p style='color:#666; padding:10px;'>暫無相關新聞 (或是今日尚無更新)</p>"

    html = "<table>"
    for art in articles:
        html += f"""
        <tr>
            <td class="col-time">{art['time']}</td>
            <td class="col-source">
                <span class="badge" style="background-color: {art['color']}">{art['source']}</span>
            </td>
            <td class="col-title">
                <a class="news-link" href="{art['link']}" target="_blank">{art['title']}</a>
            </td>
        </tr>
        """
    html += "</table>"
    return html

# --- 4. 定義新聞來源 ---

# 政府新聞稿 (需要篩選今天)
gov_feeds = [
    ("政府新聞 (中)", "https://www.info.gov.hk/gia/rss/general_zh.xml", "#E74C3C"), # 紅色
    ("Gov News (En)", "https://www.info.gov.hk/gia/rss/general_en.xml", "#C0392B")  # 深紅
]

# 其他媒體
other_feeds = [
    # 使用 Google News 搜尋關鍵字產生 RSS，這通常比直接抓取官網更穩定且無亂碼
    ("商台 903", "https://news.google.com/rss/search?q=%E5%8F%B1%E5%90%92903&hl=zh-HK&gl=HK&ceid=HK:zh-Hant", "#F1C40F"), 
    ("TVB 新聞", "https://news.tvb.com/rss/local.xml", "#2ECC71"), 
    ("Now 新聞", "https://news.now.com/rss/local", "#3498DB")      
]

# --- 5. 主程式介面 ---

st.title("🗞️ 香港新聞聚合中心")
st.caption(f"最後更新: {datetime.datetime.now(hk_tz).strftime('%Y-%m-%d %H:%M:%S')}")

if st.button("🔄 刷新新聞"):
    st.rerun()

# --- 區塊 1: 政府新聞稿 (今日) ---
st.markdown("### 🏛️ 政府新聞稿 (僅限今日)")
st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)

with st.spinner('正在讀取政府新聞...'):
    gov_articles = parse_feeds(gov_feeds, filter_today=True)
    st.markdown(render_news_table(gov_articles), unsafe_allow_html=True)

# --- 區塊 2: 其他媒體 ---
st.markdown("### 📺 媒體報導 (TVB / Now / 903)")
st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)

with st.spinner('正在讀取媒體新聞...'):
    other_articles = parse_feeds(other_feeds, filter_today=False) 
    st.markdown(render_news_table(other_articles), unsafe_allow_html=True)
