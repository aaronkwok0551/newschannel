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
    'RTHK': 'https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml',
    '星島': 'https://www.stheadline.com/rss',
    '明報': 'https://news.mingpao.com/rss/ins/all.xml',
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
    
    # Regions to EXCLUDE
    exclude_regions = ['日本', '台灣', '珠海', '澳門', '澳洲', '中國', '內地', '大陸', '深圳', '廣州', '北京', '上海', '泰國', '馬來西亞', '新加坡', '韓國', '英國', '美國', '加拿大']
    
    # Very strict fallback keywords (must be HK-related)
    keywords = ['毒品', '海關', '保安局', '鄧炳強', '緝毒', '太空油', '依託咪酯', '禁毒', '走私', '檢獲', '截獲', '香港', '港島', '九龍', '新界']
    
    # First check: exclude non-HK regions
    for region in exclude_regions:
        if region in title:
            print(f"   🚫 Excluded (non-HK region: {region})")
            return False
    
    if not api_key:
        print(f"   ⚠️ MINIMAX_API_KEY not set!")
        result = any(kw in title for kw in keywords) and '香港' in title
        print(f"   🔍 Keyword check (no AI): {result}")
        return result
    
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
                    "role": "system",
                    "content": "你係一個嚴格既香港新聞編輯。過濾標準：\n1. 只接受「香港」本地既毒品、海關、保安局新聞\n2. 一旦標題出現「日本、台灣、珠海、澳門、澳洲、中國、內地、大陸、深圳、廣州」呢啲地區，全部都係NO\n3. 香港地產、娛樂、政治其他地方新聞都係NO\n4. 香港海關/警察/緝毒既新聞先YES"
                },
                {
                    "role": "user",
                    "content": f"""嚴格判斷呢條標題係咪「香港本地既毒品/海關/保安局」新聞：

標題: {title}
來源: {source}

❌ 如果標題有以下情況，必須答NO：
- 提到日本、台灣、珠海、澳門、澳洲、中國、內地、大陸等非香港地區
- 純粹香港地產/樓盤
- 香港娛樂圈/TVB
- 一般香港社會新聞（唔關毒品/海關/保安局）

✅ 只有呢啲先YES：
- 香港本地毒品相關新聞
- 香港海關緝毒/走私新聞
- 香港保安局/禁毒處/警察緝毒新聞

請只回答「YES」或「NO」"""
                }
            ],
            "max_tokens": 10,
            "temperature": 0.1
        }
        
        print(f"   🔄 Calling MiniMax API...")
        response = requests.post(url, headers=headers, json=data, timeout=30)
        
        print(f"   📡 API response status: {response.status_code}")
        print(f"   📝 Raw response (first 300 chars): {response.text[:300]}")
        
        if response.status_code == 200:
            result = response.json()
            
            # Try different response formats
            answer = None
            
            # Format 1: OpenAI-style (choices)
            if 'choices' in result and len(result['choices']) > 0:
                answer = result['choices'][0]['message']['content'].strip().upper()
            
            # Format 2: MiniMax direct
            elif 'text' in result:
                answer = result['text'].strip().upper()
            
            # Format 3: Look for answer in base_resp
            elif 'base_resp' in result:
                text_content = result.get('base_resp', {}).get('text_content', '')
                if text_content:
                    answer = text_content.strip().upper()
            
            if answer:
                print(f"   📝 AI answer: {answer}")
                return answer == 'YES'
            else:
                print(f"   ⚠️ No answer found in response")
                return any(kw in title for kw in keywords) and '香港' in title
        elif response.status_code == 401 or response.status_code == 403:
            print(f"   ❌ API auth failed (status {response.status_code})")
            return any(kw in title for kw in keywords) and '香港' in title
        else:
            print(f"   ⚠️ API error: {response.status_code}")
            return any(kw in title for kw in keywords) and '香港' in title
        
    except Exception as e:
        print(f"   ❌ AI check failed: {e}")
        return any(kw in title for kw in keywords) and '香港' in title

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
