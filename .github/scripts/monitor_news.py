#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HK News Monitor - Uses MiniMax AI to determine relevant news
Deduplication (asked + sent) and daily filtering enabled
"""

import requests
import feedparser
import datetime
import pytz
import os
import json
import time
import re
import hashlib

# Hong Kong Timezone
HK_TZ = pytz.timezone('Asia/Hong_Kong')

# File to track sent and asked articles
SENT_ARTICLES_FILE = 'sent_articles.txt'
ASKED_ARTICLES_FILE = 'asked_articles.json'
DAILY_LOG_FILE = 'daily_log.md'

# Robust text extraction function
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

def strip_think(s):
    """Remove thinking blocks from text"""
    if not s:
        return ""
    return THINK_RE.sub("", s).strip()

def collect_text(obj, out):
    """Recursively collect text from JSON-like object"""
    if isinstance(obj, str):
        t = strip_think(obj)
        if t:
            out.append(t)
    elif isinstance(obj, list):
        for it in obj:
            collect_text(it, out)
    elif isinstance(obj, dict):
        # Common keys first
        for k in ("text", "content", "message", "output_text"):
            if k in obj:
                collect_text(obj[k], out)
        # Then scan all values
        for v in obj.values():
            collect_text(v, out)

def extract_text_from_response(resp):
    """Extract final text from MiniMax response - strict 1/0 extraction"""
    import re
    
    # 完整response文字
    full_text = str(resp)
    
    # 先移除thinking blocks
    clean = re.sub(r"<think>.*?</think>", "", full_text, flags=re.S).strip()
    
    # 嚴格：直接係 "1" 或 "0"
    if clean == "1":
        return "1"
    if clean == "0":
        return "0"
    
    # 二次檢查：從response尾部提取
    # MiniMax通常會喺最後output答案
    lines = clean.split('\n')
    for line in reversed(lines):
        line = line.strip()
        if line in ['1', '0']:
            return line
    
    # 二次檢查：search for 1 or 0
    m = re.search(r'\b([01])\b', clean)
    return m.group(1) if m else ""

# RSS Sources to monitor
RSS_SOURCES = {
    'Google News': 'https://news.google.com/rss/search?q=毒品+OR+保安局+OR+鄧炳強+OR+緝毒+OR+太空油+OR+依託咪酯+OR+禁毒+OR+毒品案+OR+海關+OR+戰時炸彈+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant',
    '政府新聞': 'https://www.info.gov.hk/gia/rss/general_zh.xml',
    'RTHK': 'https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml',
    'HK01': 'https://web-data.api.hk01.com/v2/feed/category/0',
    '星島': 'https://www.stheadline.com/rss',
    '明報': 'https://news.mingpao.com/rss/ins/all.xml',
    'i-Cable': 'https://www.i-cable.com/feed',
    'on.cc': 'https://rsshub-production-9dfc.up.railway.app/oncc/zh-hant/news',
}

def get_title_hash(title):
    """Generate short hash for title comparison"""
    return hashlib.md5(title.encode('utf-8')).hexdigest()[:8]

def load_asked_articles():
    """Load previously asked article hashes with timestamp"""
    asked = {}
    try:
        if os.path.exists(ASKED_ARTICLES_FILE):
            with open(ASKED_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                asked = json.load(f)
    except Exception as e:
        print(f"   ⚠️ Error loading asked articles: {e}")
    return asked

def save_asked_articles(asked):
    """Save asked article hashes with timestamp"""
    try:
        # Keep only last 7 days
        cutoff = datetime.datetime.now(HK_TZ) - datetime.timedelta(days=7)
        filtered = {k: v for k, v in asked.items() 
                    if datetime.datetime.fromisoformat(v['asked_at']) > cutoff}
        with open(ASKED_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(filtered, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"   ⚠️ Error saving asked articles: {e}")

def load_sent_articles():
    """Load previously sent article URLs"""
    sent = set()
    try:
        if os.path.exists(SENT_ARTICLES_FILE):
            with open(SENT_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('http'):
                        sent.add(line)
    except Exception as e:
        print(f"   ⚠️ Error loading sent articles: {e}")
    return sent

def save_sent_articles(sent_urls):
    """Save sent article URLs to file"""
    try:
        with open(SENT_ARTICLES_FILE, 'w', encoding='utf-8') as f:
            for url in sorted(sent_urls):
                f.write(f"{url}\n")
    except Exception as e:
        print(f"   ⚠️ Error saving sent articles: {e}")

def is_today(dt_obj):
    """Check if datetime is today in HKT"""
    now = datetime.datetime.now(HK_TZ)
    return dt_obj.date() == now.date()

def send_telegram(message):
    """Send message to Telegram"""
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if not bot_token or not chat_id:
        print("⚠️ Telegram credentials not set")
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True
    }
    
    try:
        response = requests.post(url, json=data, timeout=10)
        if response.ok:
            print("✅ Telegram notification sent")
            return True
        else:
            print(f"❌ Telegram failed: {response.text}")
    except Exception as e:
        print(f"❌ Telegram error: {e}")
    return False


def check_with_minimax(title, source, asked_articles):
    """Use MiniMax AI to check if news is relevant - with deduplication"""
    api_key = os.environ.get('MINIMAX_API_KEY', '')
    group_id = os.environ.get('MINIMAX_GROUP_ID', '')
    
    # Check if title is empty or too short
    if not title or not title.strip() or len(title.strip()) < 2:
        print(f"   🚫 Empty/short title, skipping AI")
        title_hash = get_title_hash(title)
        if title_hash:
            asked_articles[title_hash] = {'asked_at': datetime.datetime.now(HK_TZ).isoformat(), 'result': 'NO'}
        return False
    
    # Check if already asked today (deduplication)
    title_hash = get_title_hash(title)
    if title_hash in asked_articles:
        asked_info = asked_articles[title_hash]
        result = asked_info.get('result', 'NO')
        print(f"   ⏭️ Already asked: {result}")
        return result == 'YES'
    
    # Exclude regions (真正海外先排除)
    exclude_regions = ['日本', '台灣', '澳洲', '泰國', '馬來西亞', '新加坡', 
                       '韓國', '英國', '美國', '加拿大']
    
    # Region filter - 只排除真正海外
    for region in exclude_regions:
        if region in title:
            asked_articles[title_hash] = {'asked_at': datetime.datetime.now(HK_TZ).isoformat(), 'result': 'NO'}
            print(f"   🚫 Excluded (non-HK: {region})")
            return False
    
    # --- HK-context org routing (fast path; reduces AI calls) ---
    title_l = title.lower()
    
    # 強機構詞
    strong_org = ["香港海關", "hong kong customs", "保安局", "security bureau", 
                  "禁毒處", "adcc", "鄧炳強", "販毒", "吸毒", "藏毒", "緝毒", 
                  "毒品", "檢獲", "走私毒品", "海關檢獲"]
    
    # 弱詞
    weak_org = ["海關", "customs"]
    
    # 香港上下文
    hk_ctx = ["香港", "本港", "hksar", "hong kong", "港"]
    
    # 香港媒體來源
    hk_sources = {"政府新聞", "RTHK", "HK01", "星島", "明報", "i-Cable", "on.cc", 
                  "Google News", "文匯報", "am730", "東方日報", "都市日報"}
    
    has_strong = any(k in title for k in strong_org) or any(k in title_l for k in strong_org)
    has_weak = any(k in title for k in weak_org) or any(k in title_l for k in weak_org)
    has_hk_context = (any(k in title for k in hk_ctx) or 
                      any(k in title_l for k in hk_ctx) or 
                      (source in hk_sources))
    
    # 規則 1：強機構 + 香港上下文 → 直接 YES
    if has_strong and has_hk_context:
        asked_articles[title_hash] = {'asked_at': datetime.datetime.now(HK_TZ).isoformat(), 'result': 'YES'}
        print("   ✅ Strong org + HK context (no AI)")
        return True
    
    # 規則 2：弱機構 + 香港上下文 → 直接 YES
    if has_weak and has_hk_context:
        asked_articles[title_hash] = {'asked_at': datetime.datetime.now(HK_TZ).isoformat(), 'result': 'YES'}
        print("   ✅ Customs + HK context (no AI)")
        return True
    
    # 規則 3：完全無命中機構 → 直接 NO
    if not (has_strong or has_weak):
        asked_articles[title_hash] = {'asked_at': datetime.datetime.now(HK_TZ).isoformat(), 'result': 'NO'}
        print("   🚫 No org hit (no AI)")
        return False
    
    # 規則 4：命中機構但無香港上下文 → AI fallback
    # (呢度可能係海外海關新聞，需要AI判斷)
    
    # No API key - keyword fallback
    if not api_key:
        print(f"   ⚠️ No API key - using keyword fallback")
        core_keywords = ['毒品', '海關', '保安局', '鄧炳強', '緝毒', '太空油', '依託咪酯', 
                         '禁毒', '走私', '檢獲', '截獲', '販毒', '吸毒']
        hk_keywords = ['香港', '港島', '九龍', '新界', '本港', '香港海關', '香港警方']
        has_core = any(kw in title for kw in core_keywords)
        has_hk = any(kw in title for kw in hk_keywords)
        result = has_core and has_hk
    # No API key - keyword fallback
    if not api_key:
        print(f"   ⚠️ No API key - using keyword fallback")
        core_keywords = ['毒品', '海關', '保安局', '鄧炳強', '緝毒', '太空油', '依託咪酯', 
                         '禁毒', '走私', '檢獲', '截獲', '販毒', '吸毒']
        hk_keywords = ['香港', '港島', '九龍', '新界', '本港', '香港海關', '香港警方']
        has_core = any(kw in title for kw in core_keywords)
        has_hk = any(kw in title for kw in hk_keywords)
        result = has_core and has_hk
        asked_articles[title_hash] = {'asked_at': datetime.datetime.now(HK_TZ).isoformat(), 'result': 'YES' if result else 'NO'}
        print(f"   🔍 Keyword check: {result}")
        return result
    
    # Call MiniMax API
    try:
        url = "https://api.minimax.io/anthropic/v1/messages"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        if group_id:
            headers["X-GroupId"] = group_id
        
        data = {
            "model": "MiniMax-M2.1",
            "max_tokens": 1,
            "temperature": 0.0,
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": f"""你是一個二元分類器。任務：判斷下列新聞是否與毒品/禁毒直接相關。

判定為「有關(1)」的例子：
- 香港海關/緝毒/檢獲/販毒/吸毒/藏毒 + 香港/本港/HK/香港政府渠道
- 保安局/禁毒處/鄧炳強 + 香港相關

判定為「無關(0)」：
- 純台灣/內地毒品新聞（冇香港提及）
- 「台大」= 台灣大學，不是香港
- 台灣媒體但冇明確提及香港
- 只提到「藥物」但明顯是醫療用藥

重要：台灣大學(台大)、中華日報等非香港來源必須0。

輸出規則：
只輸出單一字元：1 或 0。

來源：{source}
新聞：{title}"""
                }]
            }]
        }
        
        print(f"   🔄 Calling MiniMax AI...")
        response = requests.post(url, headers=headers, json=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            
            # Save response for debugging
            try:
                with open('minimax_response.json', 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
            except:
                pass
            
            assistant_text = extract_text_from_response(result)
            print(f"   📝 AI response: {assistant_text}")
            
            # Check if AI returned 1 (relevant)
            is_relevant = assistant_text == '1'
            asked_articles[title_hash] = {
                'asked_at': datetime.datetime.now(HK_TZ).isoformat(),
                'result': 'YES' if is_relevant else 'NO'
            }
            return is_relevant
        
        print(f"   ⚠️ API error, using keyword fallback")
        core_keywords = ['毒品', '海關', '保安局', '鄧炳強', '緝毒', '太空油', '依託咪酯', 
                         '禁毒', '走私', '檢獲', '截獲', '販毒', '吸毒']
        hk_keywords = ['香港', '港島', '九龍', '新界', '本港', '香港海關', '香港警方']
        has_core = any(kw in title for kw in core_keywords)
        has_hk = any(kw in title for kw in hk_keywords)
        result = has_core and has_hk
        asked_articles[title_hash] = {'asked_at': datetime.datetime.now(HK_TZ).isoformat(), 'result': 'YES' if result else 'NO'}
        return result
        
    except Exception as e:
        print(f"   ❌ AI check failed: {e}")
        core_keywords = ['毒品', '海關', '保安局', '鄧炳強', '緝毒', '太空油', '依託咪酯', 
                         '禁毒', '走私', '檢獲', '截獲', '販毒', '吸毒']
        hk_keywords = ['香港', '港島', '九龍', '新界', '本港', '香港海關', '香港警方']
        has_core = any(kw in title for kw in core_keywords)
        has_hk = any(kw in title for kw in hk_keywords)
        result = has_core and has_hk
        asked_articles[title_hash] = {'asked_at': datetime.datetime.now(HK_TZ).isoformat(), 'result': 'YES' if result else 'NO'}
        return result

def parse_rss_source(name, url, sent_articles, asked_articles):
    """Parse RSS/JSON source and return matching articles"""
    articles = []
    now_hkt = datetime.datetime.now(HK_TZ)
    
    try:
        if 'news.google.com' in url:
            feed = feedparser.parse(url)
            print(f"   📰 Found {len(feed.entries)} entries from Google News")
            for entry in feed.entries[:30]:
                link = entry.link
                if link in sent_articles:
                    continue
                
                # Check date FIRST
                time_struct = getattr(entry, 'published_parsed', None)
                if not time_struct:
                    continue
                
                dt_obj = datetime.datetime.fromtimestamp(time.mktime(time_struct), HK_TZ)
                if not is_today(dt_obj):
                    continue
                
                print(f"   📄 Today: {entry.title[:50]}...")
                if check_with_minimax(entry.title, name, asked_articles):
                    articles.append({
                        'source': name,
                        'title': entry.title.rsplit(' - ', 1)[0],
                        'link': link,
                        'datetime': dt_obj
                    })
        
        elif 'wenweipo.com' in url:
            response = requests.get(url, timeout=15)
            data = response.json()
            items = data.get('data', [])[:30]
            print(f"   📰 Found {len(items)} entries from 文匯報")
            for item in items:
                title = item.get('title', '')
                link = item.get('url', '')
                if link in sent_articles:
                    continue
                
                pub_date = item.get('publishTime') or item.get('updated')
                if not pub_date:
                    continue
                
                try:
                    dt_obj = datetime.datetime.strptime(pub_date, "%Y-%m-%dT%H:%M:%S.%f%z")
                    dt_obj = dt_obj.astimezone(HK_TZ)
                    if not is_today(dt_obj):
                        continue
                    
                    print(f"   📄 Today: {title[:50]}...")
                    if check_with_minimax(title, '文匯報', asked_articles):
                        articles.append({
                            'source': '文匯報',
                            'title': title,
                            'link': link,
                            'datetime': dt_obj
                        })
                except:
                    pass
        
        else:
            response = requests.get(url, timeout=15)
            feed = feedparser.parse(response.content)
            print(f"   📰 Found {len(feed.entries)} entries from {name}")
            for entry in feed.entries[:30]:
                link = entry.link
                if link in sent_articles:
                    continue
                
                # Check date FIRST
                time_struct = getattr(entry, 'updated_parsed', None) or getattr(entry, 'published_parsed', None)
                if not time_struct:
                    continue
                
                dt_obj = datetime.datetime.fromtimestamp(time.mktime(time_struct), HK_TZ)
                if not is_today(dt_obj):
                    continue
                
                print(f"   📄 Today: {entry.title[:50]}...")
                if check_with_minimax(entry.title, name, asked_articles):
                    articles.append({
                        'source': name,
                        'title': entry.title.rsplit(' - ', 1)[0],
                        'link': link,
                        'datetime': dt_obj
                    })
    
    except Exception as e:
        print(f"❌ Error fetching {name}: {e}")
    
    return articles

def main():
    now_hkt = datetime.datetime.now(HK_TZ)
    print(f"\n🕐 [{now_hkt.strftime('%Y-%m-%d %H:%M:%S')}] Starting AI news monitor...")
    print(f"📡 Monitoring {len(RSS_SOURCES)} sources")
    
    # Load tracking data
    sent_articles = load_sent_articles()
    asked_articles = load_asked_articles()
    print(f"📋 Loaded {len(sent_articles)} sent, {len(asked_articles)} asked articles")
    
    # Check API key
    api_key = os.environ.get('MINIMAX_API_KEY', '')
    print(f"🤖 MiniMax: {'✅ Configured' if api_key else '❌ Not configured'}")
    
    print()
    all_articles = []
    
    for name, url in RSS_SOURCES.items():
        print(f"📥 Fetching {name}...")
        articles = parse_rss_source(name, url, sent_articles, asked_articles)
        all_articles.extend(articles)
        print(f"   → Found {len(articles)} new articles")
    
    # Save asked articles
    save_asked_articles(asked_articles)
    
    # Sort and deduplicate
    all_articles.sort(key=lambda x: x['datetime'], reverse=True)
    
    seen = set()
    unique_articles = []
    for article in all_articles:
        if article['link'] not in seen:
            seen.add(article['link'])
            unique_articles.append(article)
    
    # Group by source
    articles_by_source = {}
    for article in unique_articles:
        source = article['source']
        articles_by_source.setdefault(source, []).append(article)
    
    print(f"\n📊 Summary: {dict((k, len(v)) for k, v in articles_by_source.items())}")
    
    # Send notification
    if unique_articles and 8 <= now_hkt.hour <= 19:
        message = "📰 綜合媒體快訊\n\n"
        
        emoji_map = {
            '政府新聞': '📰', 'HK01': '📰', 'on.cc': '📰', 'now新聞': '📰',
            'RTHK': '📰', '星島': '🐯', '明報': '📝', '文匯報': '📰',
        }
        
        for source, articles in articles_by_source.items():
            emoji = emoji_map.get(source, '📰')
            message += f"{emoji} {source}\n"
            for article in articles[:5]:
                title = article['title'].replace('\n', ' ').strip()
                message += f"• [{title}]({article['link']})\n"
            message += "\n"
        
        message += f"🔗 [GitHub](https://github.com/aaronkwok0551/newschannel)"
        
        if send_telegram(message):
            for article in unique_articles:
                sent_articles.add(article['link'])
            save_sent_articles(sent_articles)
            log_daily_summary(unique_articles, len(unique_articles))
            print(f"\n✅ Sent {len(unique_articles)} articles")
        else:
            print(f"\n⚠️ Telegram failed")
    
    elif unique_articles:
        print(f"\n⏰ Outside hours (8am-7pm), skipped sending")
        log_daily_summary(unique_articles, 0)
    else:
        print(f"\n📭 No new articles")
    
    print(f"\n✅ Complete at {datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == '__main__':
    main()
