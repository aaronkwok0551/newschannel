#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HK News Monitor - Monitors news related to drugs, customs, and security bureau
"""

import requests
import feedparser
import datetime
import pytz
import re
import os
import sys
import json

# Hong Kong Timezone
HK_TZ = pytz.timezone('Asia/Hong_Kong')

# Keywords to search for
KEYWORDS = [
    '毒品', '海關', '保安局', '鄧炳強', '緝毒', '太空油', 
    '依託咪酯', '禁毒', '毒品案', '戰時炸彈', '安全帶'
]

# RSS Sources to monitor
RSS_SOURCES = {
    '政府新聞': 'https://www.info.gov.hk/gia/rss/general_zh.xml',
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

def check_keyword(title):
    """Check if title contains any keyword"""
    title_lower = title.lower()
    for keyword in KEYWORDS:
        if keyword in title:
            return True
    return False

def parse_rss_source(name, url):
    """Parse RSS/JSON source and return matching articles"""
    articles = []
    now = datetime.datetime.now(HK_TZ)
    
    try:
        if 'news.google.com' in url:
            # Google News RSS
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if check_keyword(entry.title):
                    time_struct = getattr(entry, 'published_parsed', None)
                    if time_struct:
                        dt_obj = datetime.datetime.fromtimestamp(
                            time.mktime(time_struct), HK_TZ
                        )
                        if (now - dt_obj).total_seconds() < 86400:  # Within 24 hours
                            articles.append({
                                'source': name,
                                'title': entry.title.rsplit(' - ', 1)[0],
                                'link': entry.link,
                                'time': dt_obj.strftime('%H:%M'),
                                'datetime': dt_obj
                            })
        elif 'wenweipo.com' in url:
            # Wenweipo JSON
            response = requests.get(url, timeout=15)
            data = response.json()
            for item in data.get('data', []):
                title = item.get('title', '')
                if check_keyword(title):
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
                                    'time': dt_obj.strftime('%H:%M'),
                                    'datetime': dt_obj
                                })
                        except:
                            pass
        else:
            # Regular RSS
            response = requests.get(url, timeout=15)
            feed = feedparser.parse(response.content)
            for entry in feed.entries:
                if check_keyword(entry.title):
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
                                'time': dt_obj.strftime('%H:%M'),
                                'datetime': dt_obj
                            })
    except Exception as e:
        print(f"❌ Error fetching {name}: {e}")
    
    return articles

def main():
    print(f"\n🕐 [{datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Starting news monitor...")
    print(f"📡 Monitoring {len(RSS_SOURCES)} sources for keywords: {KEYWORDS[:5]}...\n")
    
    all_articles = []
    
    for name, url in RSS_SOURCES.items():
        print(f"📥 Fetching {name}...")
        articles = parse_rss_source(name, url)
        all_articles.extend(articles)
        print(f"   → Found {len(articles)} matching articles")
    
    # Sort by time
    all_articles.sort(key=lambda x: x['datetime'], reverse=True)
    
    # Remove duplicates based on title
    seen = set()
    unique_articles = []
    for article in all_articles:
        title_key = article['title'][:30]  # First 30 chars as key
        if title_key not in seen:
            seen.add(title_key)
            unique_articles.append(article)
    
    print(f"\n📊 Total unique articles: {len(unique_articles)}")
    
    # Save to file for GitHub Actions
    with open('new_articles.txt', 'w', encoding='utf-8') as f:
        for article in unique_articles[:15]:  # Max 15 articles
            f.write(f"• {article['source']} [{article['time']}] {article['title']}\n")
            f.write(f"  {article['link']}\n\n")
    
    # Send notification if there are new articles
    if unique_articles:
        message = f"📰 **香港即時新聞監測** ({len(unique_articles)}則)\n\n"
        for article in unique_articles[:5]:  # First 5 in notification
            message += f"• {article['source']} [{article['time']}] {article['title']}\n"
        
        message += f"\n... 同埋{len(unique_articles)-5}則更多\n"
        message += f"🔗 https://github.com/aaronkwok0551/newschannel"
        
        # Only send if it's between 8am-10pm HKT
        now_hkt = datetime.datetime.now(HK_TZ)
        if 8 <= now_hkt.hour <= 22:
            send_telegram(message)
            print(f"\n✅ Notification sent for {len(unique_articles)} articles")
        else:
            print(f"\n⏰ Outside monitoring hours (8am-10pm), notification skipped")
    else:
        print("\n📭 No matching articles found")
    
    print(f"\n✅ Monitor complete at {datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == '__main__':
    main()
