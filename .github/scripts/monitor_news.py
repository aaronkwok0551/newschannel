#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HK News Monitor - Uses MiniMax AI to determine relevant news
Deduplication and daily filtering enabled
"""

import requests
import feedparser
import datetime
import pytz
import os
import json
import time

# Hong Kong Timezone
HK_TZ = pytz.timezone('Asia/Hong_Kong')

# File to track sent articles
SENT_ARTICLES_FILE = 'sent_articles.txt'

# RSS Sources to monitor
RSS_SOURCES = {
    # Government RSS
    '政府新聞': 'https://www.info.gov.hk/gia/rss/general_zh.xml',
    
    # News Sources with AI filtering
    'HK01': 'https://news.hk01.com/rss/focus/2135',
    'on.cc': 'https://news.on.cc/hk/import/rdf/news.rdf',
    'now新聞': 'https://news.now.com/home/rss.xml',
    'RTHK': 'https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml',
    '星島': 'https://www.stheadline.com/rss',
    '明報': 'https://news.mingpao.com/rss/ins/all.xml',
}

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

def is_recent(dt_obj, hours=24):
    """Check if datetime is within specified hours"""
    now = datetime.datetime.now(HK_TZ)
    return (now - dt_obj).total_seconds() < (hours * 3600)

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

def check_with_minimax(title, source):
    """Use MiniMax AI to check if news is relevant"""
    api_key = os.environ.get('MINIMAX_API_KEY', '')
    group_id = os.environ.get('MINIMAX_GROUP_ID', '')  # Optional for some plans
    
    # Regions to EXCLUDE
    exclude_regions = ['日本', '台灣', '珠海', '澳門', '澳洲', '中國', '內地', '大陸', '深圳', '廣州', '北京', '上海', '泰國', '馬來西亞', '新加坡', '韓國', '英國', '美國', '加拿大']
    
    # Strict keyword fallback (must be directly related to drugs/customs/security bureau)
    # Must include at least ONE of these core keywords:
    # - Drug-related: 毒品, 緝毒, 太空油, 依託咪酯, 禁毒, 販毒, 吸毒
    # - Customs-related: 海關, 走私, 檢獲, 截獲
    # - Security Bureau related: 保安局, 鄧炳強
    
    # All news MUST include at least one of these core keywords
    core_keywords = ['毒品', '海關', '保安局', '鄧炳強', '緝毒', '太空油', '依託咪酯', '禁毒', '走私', '檢獲', '截獲', '販毒', '吸毒']
    
    # Must also include HK indicator
    hk_keywords = ['香港', '港島', '九龍', '新界', '本港', '香港海關', '香港警方']
    
    # First check: exclude non-HK regions
    for region in exclude_regions:
        if region in title:
            print(f"   🚫 Excluded (non-HK region: {region})")
            return False
    
    if not api_key:
        print(f"   ⚠️ MINIMAX_API_KEY not set!")
        # Strict keyword fallback
        has_core = any(kw in title for kw in core_keywords)
        has_hk = any(kw in title for kw in hk_keywords)
        result = has_core and has_hk
        print(f"   🔍 Core keyword: {has_core}, HK keyword: {has_hk} → {result}")
        return result
    
    try:
        # Standard REST API format (OpenAI-style from MiniMax docs)
        url = "https://api.minimax.io/v1/text/chatcompletion_v2"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Try with Group ID header
        if group_id:
            headers["X-GroupId"] = group_id
        
        # Simpler format - MiniMax-M1 (non-reasoning model)
        data = {
            "model": "MiniMax-M1",
            "max_tokens": 5,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "user",
                    "content": f"Is this about Hong Kong drugs/customs news? Reply YES or NO. Title: {title}"
                }
            ]
        }
        
        print(f"   🔄 Calling MiniMax API (M1)...")
        response = requests.post(url, headers=headers, json=data, timeout=30)
        
        print(f"   📡 Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   📝 Response: {str(result)[:200]}")
            
            # Handle null choices
            if result.get('choices') is None:
                print(f"   ⚠️ choices is null - model returned no response")
                has_core = any(kw in title for kw in core_keywords)
                has_hk = any(kw in title for kw in hk_keywords)
                return has_core and has_hk
            
            # Parse choices format
            if 'choices' in result and len(result['choices']) > 0:
                answer = result['choices'][0]['message']['content'].strip().upper()
                print(f"   📝 AI answer: {answer}")
                return answer == 'YES'
        
        elif response.status_code in [401, 403]:
            print(f"   ❌ Auth failed: {response.text[:200]}")
        
        # If all attempts fail, use keyword fallback
        print(f"   ⚠️ All AI attempts failed, using keyword fallback")
        has_core = any(kw in title for kw in core_keywords)
        has_hk = any(kw in title for kw in hk_keywords)
        return has_core and has_hk
        
    except Exception as e:
        print(f"   ❌ AI check failed: {e}")
        # Strict keyword fallback
        has_core = any(kw in title for kw in core_keywords)
        has_hk = any(kw in title for kw in hk_keywords)
        return has_core and has_hk


def parse_rss_source(name, url, sent_articles):
    """Parse RSS/JSON source and return matching articles"""
    articles = []
    now = datetime.datetime.now(HK_TZ)
    
    try:
        if 'news.google.com' in url:
            feed = feedparser.parse(url)
            for entry in feed.entries[:30]:
                link = entry.link
                
                # Skip if already sent
                if link in sent_articles:
                    print(f"   ⏭️ Already sent, skipping: {entry.title[:40]}...")
                    continue
                
                if check_with_minimax(entry.title, name):
                    time_struct = getattr(entry, 'published_parsed', None)
                    if time_struct:
                        dt_obj = datetime.datetime.fromtimestamp(
                            time.mktime(time_struct), HK_TZ
                        )
                        # Only today's news
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
                
                # Skip if already sent
                if link in sent_articles:
                    print(f"   ⏭️ Already sent, skipping: {title[:40]}...")
                    continue
                
                if check_with_minimax(title, '文匯報'):
                    pub_date = item.get('publishTime') or item.get('updated')
                    if pub_date:
                        try:
                            dt_obj = datetime.datetime.strptime(
                                pub_date, "%Y-%m-%dT%H:%M:%S.%f%z"
                            )
                            dt_obj = dt_obj.astimezone(HK_TZ)
                            # Only today's news
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
                
                # Skip if already sent
                if link in sent_articles:
                    print(f"   ⏭️ Already sent, skipping: {entry.title[:40]}...")
                    continue
                
                if check_with_minimax(entry.title, name):
                    time_struct = getattr(entry, 'updated_parsed', None) or getattr(entry, 'published_parsed', None)
                    if time_struct:
                        dt_obj = datetime.datetime.fromtimestamp(
                            time.mktime(time_struct), HK_TZ
                        )
                        # Only today's news
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
    print(f"\n🕐 [{datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Starting AI news monitor...")
    print(f"📡 Monitoring {len(RSS_SOURCES)} sources")
    
    # Load already sent articles
    sent_articles = load_sent_articles()
    print(f"📋 Loaded {len(sent_articles)} previously sent articles")
    
    # Check API key
    api_key = os.environ.get('MINIMAX_API_KEY', '')
    if api_key:
        print(f"🤖 MiniMax API key: {api_key[:10]}...")
    else:
        print("⚠️ MINIMAX_API_KEY not set, using keyword fallback")
    
    print()
    
    all_articles = []
    
    for name, url in RSS_SOURCES.items():
        print(f"📥 Fetching {name}...")
        articles = parse_rss_source(name, url, sent_articles)
        all_articles.extend(articles)
        print(f"   → Found {len(articles)} new articles")
    
    # Sort by time
    all_articles.sort(key=lambda x: x['datetime'], reverse=True)
    
    # Remove duplicates (by title within this run)
    seen = set()
    unique_articles = []
    for article in all_articles:
        title_key = article['title'][:30]
        if title_key not in seen:
            seen.add(title_key)
            unique_articles.append(article)
    
    # Group by source
    articles_by_source = {}
    for article in unique_articles:
        source = article['source']
        if source not in articles_by_source:
            articles_by_source[source] = []
        articles_by_source[source].append(article)
    
    print(f"\n📊 New articles by source: {dict((k, len(v)) for k, v in articles_by_source.items())}")
    
    # Send notification if there are new articles
    if unique_articles:
        message = "📰 綜合媒體快訊 (彙整)\n\n"
        
        for source, articles in articles_by_source.items():
            emoji_map = {
                '政府新聞': '📰',
                'HK01': '📰',
                'on.cc': '📰',
                'now新聞': '📰',
                '禁毒/海關': '📰',
                'RTHK': '📰',
                '星島': '🐯',
                '明報': '📝',
                '文匯報': '📰',
            }
            emoji = emoji_map.get(source, '📰')
            message += f"{emoji} {source}\n"
            for article in articles[:5]:  # Max 5 per source
                title = article['title'].replace('\n', ' ').strip()
                message += f"• [{title}]({article['link']})\n"
            message += "\n"
        
        message += f"🔗 https://github.com/aaronkwok0551/newschannel"
        
        # Only send if within monitoring hours (8am-7pm)
        now_hkt = datetime.datetime.now(HK_TZ)
        if 8 <= now_hkt.hour <= 19:
            if send_telegram(message):
                # Mark these articles as sent
                for article in unique_articles:
                    sent_articles.add(article['link'])
                save_sent_articles(sent_articles)
                print(f"\n✅ Sent {len(unique_articles)} new articles, updated tracking file")
            else:
                print(f"\n⚠️ Telegram send failed")
        else:
            print(f"\n⏰ Outside monitoring hours (8am-7pm), notification skipped")
            # Still update tracking to avoid duplicate notifications next time
            for article in unique_articles:
                sent_articles.add(article['link'])
            save_sent_articles(sent_articles)
    else:
        print("\n📭 No new articles found today")
    
    print(f"\n✅ Monitor complete at {datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == '__main__':
    main()
