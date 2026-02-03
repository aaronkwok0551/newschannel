#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple test script for MiniMax API - Fixed version
"""
import os
import sys
import json
import re

# Simple HTTP client (no requests needed)
import urllib.request
import urllib.error
import urllib.parse

# Get API key
api_key = os.environ.get('MINIMAX_API_KEY', '')
group_id = os.environ.get('MINIMAX_GROUP_ID', '')

if not api_key:
    print("❌ MINIMAX_API_KEY not set!")
    sys.exit(1)

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

# Better prompt with more tokens
data = {
    "model": "MiniMax-M2.1",
    "max_tokens": 200,
    "temperature": 0.1,
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Is this about Hong Kong drugs news? Reply with ONLY YES or NO (one word)."
                }
            ]
        }
    ]
}

print(f"\n🔄 Calling MiniMax API...")
print(f"📡 URL: {url}")

# Create request
req = urllib.request.Request(
    url,
    data=json.dumps(data).encode('utf-8'),
    headers=headers
)

try:
    response = urllib.request.urlopen(req, timeout=30)
    result_raw = response.read().decode('utf-8')
    result = json.loads(result_raw)
    
    print(f"\n📡 Status: {response.status}")
    print(f"📝 Response: {result_raw[:500]}")
    
    # Try to extract the actual text from the response
    assistant_text = ""
    
    # Method 1: Look for content blocks
    content = result.get("content", [])
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                # Check for thinking block
                if block.get("type") == "thinking" and "text" in block:
                    assistant_text = block["text"]
                    break
                # Check for text block
                if block.get("type") == "text" and "text" in block:
                    assistant_text = block["text"]
                    break
    
    # Method 2: Look for "text" field in content
    if not assistant_text and "content" in result:
        content_val = result["content"]
        if isinstance(content_val, str):
            assistant_text = content_val
        elif isinstance(content_val, dict) and "text" in content_val:
            assistant_text = content_val["text"]
    
    # Method 3: Look for "answer" field
    if not assistant_text and "answer" in result:
        assistant_text = result["answer"]
    
    # Method 4: Search for YES or NO in the raw response
    if not assistant_text:
        raw_lower = result_raw.lower()
        if '"yes"' in raw_lower or raw_lower.endswith('"yes"') or "yes" in raw_lower.split()[-3:]:
            assistant_text = "YES"
        elif '"no"' in raw_lower or raw_lower.endswith('"no"') or "no" in raw_lower.split()[-3:]:
            assistant_text = "NO"
    
    print(f"\n✅ Extracted: {assistant_text}")
    
    # Check if relevant
    is_relevant = assistant_text.upper().strip() == "YES" if assistant_text else False
    print(f"📌 Relevant: {is_relevant}")
    
except urllib.error.HTTPError as e:
    print(f"\n❌ HTTP Error: {e.code} - {e.reason}")
    print(f"Body: {e.read().decode('utf-8')[:500]}")
except Exception as e:
    print(f"\n❌ Error: {e}")
