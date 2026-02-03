#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HK News Monitor - Uses MiniMax AI to determine relevant news
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

# RSS Sources to monitor
RSS_SOURCES = {
    # Government RSS
    '政府新聞': 'https://www.info.gov.hk/gia/rss/general_zh.xml',
    
    # News Sources with AI filtering
    'HK01': 'https://news.hk01.com/rss/focus/2135',
    'on.cc': 'https://news.on.cc/hk/import/rdf/news.rdf',
    'now新聞': 'https://news.now.com/home/rss.xml',
    '禁毒/海關': 'https://news.google.com/rss/search?q=毒品+OR+保安局+OR+鄧炳強+OR+緝毒+OR+海關+when:1d&hl=zh-HK&gl=HK&ceid=HK:zh-Hant',
    'RTHK': 'https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml',
    '星島': 'https://www.stheadline.com/rss',
    '明報': 'https://news.mingpao.com/rss/ins/all.xml',
    '文匯報': 'https://www.wenweipo.com/channels/wenweipo/hotlist/hours/24/stories.json',
}

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
    
    # Fallback keywords
    keywords = ['毒品', '海關', '保安局', '鄧炳強', '緝毒', '太空油', '依託咪酯', '禁毒', '走私', '檢獲', '截獲']
    
    if not api_key:
        print(f"   ⚠️ MINIMAX_API_KEY not set, using keyword fallback")
        return any(kw in title for kw in keywords)
    
    try:
        url = "https://api.minimax.chat/v1/text/chatcompletion_v2"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "MiniMax-M2.1",
            "messages": [
                {
                    "role": "user",
                    "content": f"""請判斷以下香港新聞標題係咪同「香港毒品」、「香港海關」或「香港保安局」相關。

新聞來源: {source}
標題: {title}

相關 topics:
- 香港毒品相關 (毒品、緝毒、禁毒、太空油、依託咪酯)
- 香港海關相關 (走私、截獲、檢獲)
- 香港保安局相關 (鄧炳強、保安局政策)

請只回答「YES」或「NO」"""
                }
            ],
            "max_tokens": 10,
            "temperature": 0.1
        }
        
        print(f"   🔄 Calling MiniMax API...")
        response = requests.post(url, headers=headers, json=data, timeout=30)
        
        print(f"   📡 API response status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                answer = result['choices'][0]['message']['content'].strip().upper()
                print(f"   📝 AI answer: {answer}")
                return answer == 'YES'
            else:
                print(f"   ⚠️ No choices in response: {result}")
        elif response.status_code == 401 or response.status_code == 403:
            print(f"   ❌ API auth failed (status {response.status_code}), using keyword fallback")
            print(f"   💡 Check your MINIMAX_API_KEY format")
            return any(kw in title for kw in keywords)
        else:
            print(f"   ⚠️ API error: {response.text[:200]}")
            return any(kw in title for kw in keywords)
        
    except Exception as e:
        print(f"   ❌ AI check failed: {e}")
        return any(kw in title for kw in keywords)

    return any(kw in title for kw in keywords)

def parse_rss_source(name, url):
    """Parse RSS/JSON source and return matching articles"""
    articles = []
    now = datetime.datetime.now(HK_TZ)
    
    try:
        if 'news.google.com' in url:
            feed = feedparser.parse(url)
            for entry in feed.entries[:30]:
                if check_with_minimax(entry.title, name):
                    time_struct = getattr(entry, 'published_parsed', None)
                    if time_struct:
                        dt_obj = datetime.datetime.fromtimestamp(
                            time.mktime(time_struct), HK_TZ
                        )
                        if (now - dt_obj).total_seconds() < 86400:
                            articles.append({
                                'source': name,
                                'title': entry.title.rsplit(' - ', 1)[0],
                                'link': entry.link,
                                
                                'datetime': dt_obj
                            })
        elif 'wenweipo.com' in url:
            response = requests.get(url, timeout=15)
            data = response.json()
            for item in data.get('data', [])[:30]:
                title = item.get('title', '')
                if check_with_minimax(title, '文匯報'):
                    pub_date = item.get('publishTime') or item.get('updated')
                    if pub_date:
                        try:
                            dt_obj = datetime.datetime.strptime(
                                pub_date, "%Y-%m-%dT%H:%M:%S.%f%z"
                            )
                            if (now - dt_obj.astimezone(HK_TZ)).total_seconds() < 86400:
                                articles.append({
                                    'source': '文匯報',
                                    'title': title,
                                    'link': item.get('url', ''),
                                    
                                    'datetime': dt_obj
                                })
                        except:
                            pass
        else:
            response = requests.get(url, timeout=15)
            feed = feedparser.parse(response.content)
            for entry in feed.entries[:30]:
                if check_with_minimax(entry.title, name):
                    time_struct = getattr(entry, 'updated_parsed', None) or getattr(entry, 'published_parsed', None)
                    if time_struct:
                        dt_obj = datetime.datetime.fromtimestamp(
                            time.mktime(time_struct), HK_TZ
                        )
                        if (now - dt_obj).total_seconds() < 86400:
                            articles.append({
                                'source': name,
                                'title': entry.title.rsplit(' - ', 1)[0],
                                'link': entry.link,
                                
                                'datetime': dt_obj
                            })
    except Exception as e:
        print(f"❌ Error fetching {name}: {e}")
    
    return articles

def main():
    print(f"\n🕐 [{datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Starting AI news monitor...")
    print(f"📡 Monitoring {len(RSS_SOURCES)} sources")
    
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
        articles = parse_rss_source(name, url)
        all_articles.extend(articles)
        print(f"   → Found {len(articles)} AI-matched articles")
    
    # Sort by time
    all_articles.sort(key=lambda x: x['datetime'], reverse=True)
    
    # Remove duplicates
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
    
    print(f"\n📊 Articles by source: {dict((k, len(v)) for k, v in articles_by_source.items())}")
    
    # Save to file in new format
    with open('new_articles.txt', 'w', encoding='utf-8') as f:
        f.write("📰 綜合媒體快訊 (彙整)\n\n")
        for source, articles in articles_by_source.items():
            # Emoji mapping
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
            f.write(f"{emoji} {source}\n")
            for article in articles[:8]:  # Max 8 per source
                title = article['title'].replace('\n', ' ').strip()
                f.write(f"• [{title}]({article['link']})\n")
            f.write("\n")
    
    # Send notification
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
        
        # Only send if 8am-10pm HKT
        now_hkt = datetime.datetime.now(HK_TZ)
        if 8 <= now_hkt.hour <= 22:
            send_telegram(message)
            print(f"\n✅ Notification sent for {len(unique_articles)} articles")
        else:
            print(f"\n⏰ Outside monitoring hours, notification skipped")
    else:
        print("\n📭 No matching articles found")
    
    print(f"\n✅ Monitor complete at {datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == '__main__':
    main()
