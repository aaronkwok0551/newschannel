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
    """Extract final text from MiniMax response - handle thinking blocks"""
    texts = []
    collect_text(resp, texts)
    
    if texts:
        text = texts[0]
        # Check for thinking-only response
        if text.startswith("We need to interpret") or len(text) < 15:
            resp_str = str(resp).lower()
            if '"yes"' in resp_str or '"yes"' in resp_str:
                return "YES"
            elif '"no"' in resp_str or '"no"' in resp_str:
                return "NO"
        return text
    return ""

# RSS Sources to monitor
RSS_SOURCES = {
    '政府新聞': 'https://www.info.gov.hk/gia/rss/general_zh.xml',
    'HK01': 'https://news.hk01.com/rss/focus/2135',
    'on.cc': 'https://news.on.cc/hk/import/rdf/news.rdf',
    'now新聞': 'https://news.now.com/home/rss.xml',
    'RTHK': 'https://rthk.hk/rthxnews/rss/c_expressnews_clocal.xml',
    '星島': 'https://www.stheadline.com/rss',
    '明報': 'https://news.mingpao.com/rss/ins/all.xml',
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
    
    # Check if already asked today (deduplication)
    title_hash = get_title_hash(title)
    if title_hash in asked_articles:
        asked_info = asked_articles[title_hash]
        print(f"   ⏭️ Already asked {asked_info['result']}: {title[:40]}...")
        return asked_info.get('result') == 'YES'
    
    # Keywords for fallback
    core_keywords = ['毒品', '海關', '保安局', '鄧炳強', '緝毒', '太空油', '依託咪酯', 
                    '禁毒', '走私', '檢獲', '截獲', '販毒', '吸毒']
    hk_keywords = ['香港', '港島', '九龍', '新界', '本港', '香港海關', '香港警方']
    exclude_regions = ['日本', '台灣', '珠海', '澳門', '澳洲', '中國', '內地', '大陸', 
                       '深圳', '廣州', '北京', '上海', '泰國', '馬來西亞', '新加坡', 
                       '韓國', '英國', '美國', '加拿大']
    
    # Region filter
    for region in exclude_regions:
        if region in title:
            asked_articles[title_hash] = {'asked_at': datetime.datetime.now(HK_TZ).isoformat(), 'result': 'NO'}
            print(f"   🚫 Excluded (non-HK: {region})")
            return False
    
    if not api_key:
        print(f"   ⚠️ No API key - using keyword fallback")
        has_core = any(kw in title for kw in core_keywords)
        has_hk = any(kw in title for kw in hk_keywords)
        result = has_core and has_hk
        asked_articles[title_hash] = {'asked_at': datetime.datetime.now(HK_TZ).isoformat(), 'result': 'YES' if result else 'NO'}
        print(f"   🔍 Keyword check: {result}")
        return result
    
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
            "max_tokens": 50,
            "temperature": 0.1,
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": f"Is this Hong Kong drugs/customs news? Reply YES or NO only."
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
            
            is_relevant = assistant_text.upper().strip() in ['YES', 'Relevant']
            asked_articles[title_hash] = {
                'asked_at': datetime.datetime.now(HK_TZ).isoformat(),
                'result': 'YES' if is_relevant else 'NO'
            }
            return is_relevant
        
        print(f"   ⚠️ API error, using keyword fallback")
        has_core = any(kw in title for kw in core_keywords)
        has_hk = any(kw in title for kw in hk_keywords)
        result = has_core and has_hk
        asked_articles[title_hash] = {'asked_at': datetime.datetime.now(HK_TZ).isoformat(), 'result': 'YES' if result else 'NO'}
        return result
        
    except Exception as e:
        print(f"   ❌ AI check failed: {e}")
        has_core = any(kw in title for kw in core_keywords)
        has_hk = any(kw in title for kw in hk_keywords)
        result = has_core and has_hk
        asked_articles[title_hash] = {'asked_at': datetime.datetime.now(HK_TZ).isoformat(), 'result': 'YES' if result else 'NO'}
        return result

def log_daily_summary(new_articles, sent_count):
    """Log daily summary to markdown file"""
    try:
        today = datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d')
        log_entry = f"\n## {today}\n"
        log_entry += f"- **Checked**: {len(new_articles)} new articles\n"
        log_entry += f"- **Sent**: {sent_count} articles\n"
        
        if new_articles:
            log_entry += "\n**Articles**:\n"
            for art in new_articles[:10]:
                log_entry += f"- [{art['source']}] {art['title'][:50]}...\n"
        
        # Prepend to log file
        if os.path.exists(DAILY_LOG_FILE):
            with open(DAILY_LOG_FILE, 'r', encoding='utf-8') as f:
                existing = f.read()
        else:
            existing = "# Daily News Log\n"
        
        with open(DAILY_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(log_entry + "\n" + existing)
        
        print(f"   📝 Daily log updated")
    except Exception as e:
        print(f"   ⚠️ Log error: {e}")

def parse_rss_source(name, url, sent_articles, asked_articles):
    """Parse RSS/JSON source and return matching articles"""
    articles = []
    
    try:
        if 'news.google.com' in url:
            feed = feedparser.parse(url)
            for entry in feed.entries[:30]:
                link = entry.link
                if link in sent_articles:
                    continue
                
                if check_with_minimax(entry.title, name, asked_articles):
                    time_struct = getattr(entry, 'published_parsed', None)
                    if time_struct:
                        dt_obj = datetime.datetime.fromtimestamp(time.mktime(time_struct), HK_TZ)
                        if is_today(dt_obj):
                            articles.append({
                                'source': name,
                                'title': entry.title.rsplit(' - ', 1)[0],
                                'link': link,
                                'datetime': dt_obj
                            })
        
        elif 'wenweipo.com' in url:
            response = requests.get(url, timeout=15)
            data = response.json()
            for item in data.get('data', [])[:30]:
                title = item.get('title', '')
                link = item.get('url', '')
                if link in sent_articles:
                    continue
                
                if check_with_minimax(title, '文匯報', asked_articles):
                    pub_date = item.get('publishTime') or item.get('updated')
                    if pub_date:
                        try:
                            dt_obj = datetime.datetime.strptime(pub_date, "%Y-%m-%dT%H:%M:%S.%f%z")
                            dt_obj = dt_obj.astimezone(HK_TZ)
                            if is_today(dt_obj):
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
            for entry in feed.entries[:30]:
                link = entry.link
                if link in sent_articles:
                    continue
                
                if check_with_minimax(entry.title, name, asked_articles):
                    time_struct = getattr(entry, 'updated_parsed', None) or getattr(entry, 'published_parsed', None)
                    if time_struct:
                        dt_obj = datetime.datetime.fromtimestamp(time.mktime(time_struct), HK_TZ)
                        if is_today(dt_obj):
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
