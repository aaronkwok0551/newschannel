# -*- coding: utf-8 -*-
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import feedparser
import datetime
import pytz
import urllib.parse
import time
from bs4 import BeautifulSoup
import re
import urllib3
import concurrent.futures
import io
import os

# 嘗試載入 pydub，如果 Railway 正在編譯中就不會報錯
try:
    from pydub import AudioSegment
except ImportError:
    pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()
HK_TZ = pytz.timezone('Asia/Hong_Kong')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-HK,zh;q=0.9,en-US;q=0.8,en;q=0.7',
}

# 儲存新聞與天氣的記憶體
NEWS_DATA = {}
WEATHER_CACHE = {"temp": "--", "icon": "", "warning": ""}

def clean_title(raw_title: str) -> str:
    if not raw_title: return ""
    soup = BeautifulSoup(raw_title, "html.parser")
    text = soup.get_text()
    text = re.sub(r'\d+(分鐘|小時|天)前.*', '', text)
    return text.replace('\n', ' ').strip()

def clean_url(url: str) -> str:
    if not url: return ""
    url = url.strip()
    if "hkej.com" in url:
        url = url.replace("m.hkej.com", "www.hkej.com")
        url = re.sub(r'\++$', '', url)
    if "news.now.com" in url:
        return urllib.parse.quote(url, safe=":/%?=&")
    return urllib.parse.quote(url.split('?')[0], safe=":/%?=&")

def fetch_source(config):
    data = []
    now = datetime.datetime.now(HK_TZ)
    urls = config['url'] if isinstance(config['url'], list) else [config['url']]
    
    try:
        for u in urls:
            if config['type'] == 'json_wenweipo':
                r = requests.get(u, headers=HEADERS, timeout=20, verify=False)
                for item in r.json().get('data', []):
                    dt = datetime.datetime.strptime(item.get('updated'), "%Y-%m-%dT%H:%M:%S.%f%z")
                    data.append({'title': clean_title(item.get('title')), 'link': clean_url(item.get('url')), 'timestamp': dt.timestamp()})
            
            # HK01 API 處理邏輯
            elif config['type'] == 'json_hk01':
                r = requests.get(u, headers=HEADERS, timeout=20, verify=False)
                json_data = r.json()
                items = json_data.get('items', [])
                for item in items:
                    try:
                        article = item.get('data', item)
                        t_title = clean_title(article.get('title', ''))
                        t_link = article.get('publishUrl', article.get('url', ''))
                        if t_link and t_link.startswith('/'):
                            t_link = f"https://www.hk01.com{t_link}"
                        t_link = clean_url(t_link)
                        
                        ts = article.get('publishTime', article.get('publish_time'))
                        if ts:
                            if len(str(int(ts))) == 13: ts = ts / 1000
                            dt = datetime.datetime.fromtimestamp(ts, HK_TZ)
                        else:
                            dt = now
                        
                        if t_title and t_link:
                            data.append({'title': t_title, 'link': t_link, 'timestamp': dt.timestamp()})
                    except Exception:
                        pass
            
            elif config['type'] == 'rss':
                r = requests.get(u, headers=HEADERS, timeout=20, verify=False)
                feed = feedparser.parse(r.content)
                for entry in feed.entries:
                    t_title = clean_title(getattr(entry, "title", ""))
                    t_link = getattr(entry, "link", "")
                    if t_link.startswith("/"):
                        if "4xPuKWS" in u: t_link = f"https://www.881903.com{t_link}"
                        elif "7vsPHGi" in u: t_link = f"https://www.i-cable.com{t_link}"
                        elif "tBTzOcf" in u: t_link = f"https://www.hkej.com{t_link}"
                        elif "X5o1ke3" in u: t_link = f"https://topick.hket.com{t_link}"
                        elif "Lk7D530m" in u: t_link = f"https://news.now.com{t_link}"
                    
                    time_struct = getattr(entry, 'published_parsed', None) or getattr(entry, 'updated_parsed', None)
                    dt = datetime.datetime.fromtimestamp(time.mktime(time_struct), HK_TZ) if time_struct else now
                    data.append({'title': t_title, 'link': clean_url(t_link), 'timestamp': dt.timestamp()})
    except: pass
    
    seen = set()
    final = []
    for d in sorted(data, key=lambda x: x['timestamp'], reverse=True):
        if d['link'] not in seen:
            final.append(d)
            seen.add(d['link'])
    return config['name'], {"color": config['color'], "items": final[:80]}

# --- 香港天文台天氣抓取 ---
def fetch_weather():
    try:
        url = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=tc"
        r = requests.get(url, timeout=10)
        data = r.json()
        temp = data.get("temperature", {}).get("data", [{}])[0].get("value", "--")
        icon_list = data.get("icon", [])
        icon = f"https://www.hko.gov.hk/images/HKOWxIconOutline/pic{icon_list[0]}.png" if icon_list else ""
        warnings = data.get("warningMessage", [])
        warning_text = " | ".join(warnings) if warnings else ""
        WEATHER_CACHE["temp"] = temp
        WEATHER_CACHE["icon"] = icon
        WEATHER_CACHE["warning"] = warning_text
    except Exception as e:
        print("天氣抓取失敗:", e)

# --- 媒體設定 ---
RSSHUB = "https://rsshub-production-9dfc.up.railway.app"
FAST_CONFIGS = [
    {"name": "💊 禁毒/海關", "type": "rss", "url": "https://news.google.com/rss/search?q=毒品+OR+海關+when:1d&hl=zh-HK&gl=HK", "color": "#D946EF"},
    {"name": "🏛 政府新聞", "type": "rss", "url": "https://www.info.gov.hk/gia/rss/general_zh.xml", "color": "#E74C3C"},
    {"name": "📻 RTHK 電台", "type": "rss", "url": "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "color": "#FF9800"},
    {"name": "🎙️ 商業電台", "type": "rss", "url": "https://politepaul.com/fd/4xPuKWS07tJs.xml", "color": "#334155"}
]
SLOW_CONFIGS = [
    {"name": "💡 on.cc 東網", "type": "rss", "url": "https://politepaul.com/fd/cTsVfG4sKP6c.xml", "color": "#7C3AED"},
    {"name": "📰 HK01 即時", "type": "json_hk01", "url": "https://web-data.api.hk01.com/v2/feed/category/0", "color": "#2563EB"},
    {"name": "🐯 星島頭條", "type": "rss", "url": "https://www.stheadline.com/rss", "color": "#F97316"},
    {"name": "📝 明報即時", "type": "rss", "url": "https://news.mingpao.com/rss/ins/all.xml", "color": "#7C3AED"},
    {"name": "🐯 Now 新聞", "type": "rss", "url": "https://politepaul.com/fd/Lk7D530mgplN.xml", "color": "#16A34A"},
    {"name": "📺 有線新聞", "type": "rss", "url": "https://politepaul.com/fd/7vsPHGi1tzC9.xml", "color": "#A855F7"},
    {"name": "🟢 經濟/TOPick", "type": "rss", "url": "https://politepaul.com/fd/X5o1ke3uTiH3.xml", "color": "#0D9488"},
    {"name": "📜 信報新聞", "type": "rss", "url": "https://politepaul.com/fd/tBTzOcfkQWzF.xml", "color": "#64748B"},
    {"name": "🍊 橙新聞(合)", "type": "rss", "url": ["https://politepaul.com/fd/KZGhqIiTnOCq.xml", "https://politepaul.com/fd/8fzf6zRfoy6H.xml"], "color": "#EA580C"},
    {"name": "📜 文匯(合)", "type": "rss", "url": ["https://politepaul.com/fd/C499xnjIBdRm.xml", "https://politepaul.com/fd/6oljXv2E75Pp.xml"], "color": "#BE123C"},
    {"name": "🔵 點新聞(合)", "type": "rss", "url": ["https://politepaul.com/fd/xbfGvXWovqfk.xml", "https://politepaul.com/fd/59PndwU1mb82.xml"], "color": "#0369A1"},
    {"name": "📜 文匯(JSON)", "type": "json_wenweipo", "url": "https://www.wenweipo.com/channels/wenweipo/hotlist/hours/24/stories.json", "color": "#BE123C"},
]

def update_news(configs):
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as exe:
        futures = [exe.submit(fetch_source, c) for c in configs]
        for f in concurrent.futures.as_completed(futures):
            name, data = f.result()
            NEWS_DATA[name] = data

def job_fast(): update_news(FAST_CONFIGS)
def job_slow(): update_news(SLOW_CONFIGS)

@app.on_event("startup")
def startup_event():
    update_news(FAST_CONFIGS + SLOW_CONFIGS)
    fetch_weather()
    scheduler = BackgroundScheduler()
    scheduler.add_job(job_fast, 'interval', minutes=1)
    scheduler.add_job(job_slow, 'interval', minutes=6)
    scheduler.add_job(fetch_weather, 'interval', minutes=15)
    scheduler.start()

@app.get("/api/news")
def get_news(): return NEWS_DATA

@app.get("/api/weather")
def get_weather(): return WEATHER_CACHE

# --- API：音訊剪輯 (150MB 防護) ---
@app.post("/api/cut-audio")
async def cut_audio(
    file: UploadFile = File(...),
    start_sec: float = Form(...),
    end_sec: float = Form(...)
):
    try:
        MAX_SIZE = 150 * 1024 * 1024 
        audio_bytes = bytearray()
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk: break
            audio_bytes.extend(chunk)
            if len(audio_bytes) > MAX_SIZE:
                raise HTTPException(status_code=413, detail="檔案太大！請上傳小於 150MB 的檔案。")
        
        audio_io = io.BytesIO(audio_bytes)
        audio = AudioSegment.from_file(audio_io)
        start_ms, end_ms = int(start_sec * 1000), int(end_sec * 1000)
        clipped_audio = audio[start_ms:end_ms]
        
        out_io = io.BytesIO()
        clipped_audio.export(out_io, format="mp3")
        out_io.seek(0)
        
        safe_filename = file.filename.rsplit('.', 1)[0]
        return StreamingResponse(
            out_io, 
            media_type="audio/mpeg", 
            headers={"Content-Disposition": f'attachment; filename="clipped_{safe_filename}.mp3"'}
        )
    except HTTPException as he:
        return {"error": he.detail}
    except Exception as e:
        return {"error": str(e)}

# --- API：Whisper 逐字稿生成 (使用 Groq) ---
@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"error": "伺服器尚未設定 GROQ_API_KEY，無法使用逐字稿功能。"}

    try:
        MAX_SIZE = 25 * 1024 * 1024 
        audio_bytes = bytearray()
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk: break
            audio_bytes.extend(chunk)
            if len(audio_bytes) > MAX_SIZE:
                raise HTTPException(status_code=413, detail="檔案超過 25MB 限制！請先使用剪接工具將檔案縮小。")
        
        audio_io = io.BytesIO(audio_bytes)
        audio_io.name = file.filename

        from openai import OpenAI
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1"
        )
        
        transcript = client.audio.transcriptions.create(
            model="whisper-large-v3", 
            file=audio_io,
            # 👉 關鍵修改 1：把 "text" 改成 "srt"，這樣就會自帶完美的時分秒時間軸！
            response_format="srt", 
            # 👉 關鍵修改 2：把 prompt 改成「純粹的風格示範」，不要用命令句
            prompt="這是一段繁體中文、廣東話與English夾雜的會議紀錄。示範標點符號：，。！？"
        )
        
        return {"text": transcript}
    except HTTPException as he:
        return {"error": he.detail}
    except Exception as e:
        return {"error": str(e)}

@app.get("/", response_class=HTMLResponse)
def serve_home():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()
