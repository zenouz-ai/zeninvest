#!/usr/bin/env python3
"""Quick test of Brave Search and Brave Answers APIs."""

import json
import os
import sys

# Load .env from project root
from pathlib import Path
root = Path(__file__).resolve().parent.parent
env_path = root / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

search_key = os.getenv("BRAVE_SEARCH_API_KEY")
answer_key = os.getenv("BRAVE_ANSWER_API_KEY")

def test_search():
    """Test Brave Web Search API."""
    print("\n" + "=" * 60)
    print("BRAVE WEB SEARCH API")
    print("=" * 60)
    if not search_key:
        print("SKIP: BRAVE_SEARCH_API_KEY not set")
        return
    import httpx
    url = "https://api.search.brave.com/res/v1/web/search"
    params = {"q": "AAPL stock earnings 2025", "count": 5}
    headers = {"X-Subscription-Token": search_key}
    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=15)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("web", {}).get("results", [])
            print(f"Results: {len(results)}")
            for i, r in enumerate(results[:3], 1):
                print(f"\n  [{i}] {r.get('title', 'N/A')[:60]}...")
                print(f"      URL: {r.get('url')}")
                print(f"      {r.get('description', '')[:120]}...")
        else:
            print(resp.text[:500])
    except Exception as e:
        print(f"Error: {e}")

def test_answers():
    """Test Brave Answers API (chat completions)."""
    print("\n" + "=" * 60)
    print("BRAVE ANSWERS API")
    print("=" * 60)
    if not answer_key:
        print("SKIP: BRAVE_ANSWER_API_KEY not set")
        return
    import httpx
    url = "https://api.search.brave.com/res/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "x-subscription-token": answer_key,
    }
    body = {
        "stream": False,
        "messages": [{"role": "user", "content": "What is Apple's current market cap? Give a brief answer."}],
    }
    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=30)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
            print(f"Answer:\n  {content[:500]}")
            if "citations" in data:
                print(f"\nCitations: {len(data.get('citations', []))}")
        else:
            print(resp.text[:500])
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_search()
    test_answers()
    print("\nDone.\n")
