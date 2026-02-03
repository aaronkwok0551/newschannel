#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple test script for MiniMax API
"""
import os
import requests
import json
import re

# Get API key
api_key = os.environ.get('MINIMAX_API_KEY', '')
group_id = os.environ.get('MINIMAX_GROUP_ID', '')

if not api_key:
    print("❌ MINIMAX_API_KEY not set!")
    exit(1)

print(f"🔑 API key: {api_key[:15]}...")
print(f"🆔 Group ID: {group_id}")

# Test URL
url = "https://api.minimax.io/anthropic/v1/messages"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

if group_id:
    headers["X-GroupId"] = group_id

# Simple test prompt
data = {
    "model": "MiniMax-M2.1",
    "max_tokens": 10,
    "temperature": 0.1,
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Is this about Hong Kong drugs news? Reply YES or NO."
                }
            ]
        }
    ]
}

print(f"\n🔄 Calling MiniMax API...")
print(f"📡 URL: {url}")
print(f"📝 Request: {json.dumps(data, ensure_ascii=False)[:200]}...")

response = requests.post(url, headers=headers, json=data, timeout=30)

print(f"\n📡 Status: {response.status_code}")
print(f"📝 Response (first 500 chars): {response.text[:500]}")

if response.status_code == 200:
    try:
        result = response.json()
        print(f"\n✅ JSON parsed successfully!")
        print(f"📋 Keys in response: {list(result.keys())}")
        
        # Try to extract text
        texts = []
        
        def collect_text(obj):
            if isinstance(obj, str):
                texts.append(obj)
            elif isinstance(obj, list):
                for item in obj:
                    collect_text(item)
            elif isinstance(obj, dict):
                for key, value in obj.items():
                    if key in ['text', 'content', 'message']:
                        collect_text(value)
                    else:
                        collect_text(value)
        
        collect_text(result)
        print(f"\n📝 Extracted texts: {texts}")
        
    except Exception as e:
        print(f"❌ JSON parse error: {e}")
else:
    print(f"\n❌ Request failed with status {response.status_code}")
