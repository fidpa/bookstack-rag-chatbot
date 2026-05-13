#!/usr/bin/env python3
"""
Test script for BookStack API
"""

import os
import requests


def test_bookstack_api():
    """Test BookStack API connectivity"""

    # Configuration
    base_url = os.getenv("BOOKSTACK_URL", "http://bookstack:80")
    token_id = os.getenv("BOOKSTACK_TOKEN_ID", "")
    token_secret = os.getenv("BOOKSTACK_TOKEN_SECRET", "")

    print("Testing BookStack API:")
    print(f"Base URL: {base_url}")
    print(f"Token ID: {token_id[:8]}...")
    print(f"Token Secret: {token_secret[:8]}...")
    print()

    if not token_id or not token_secret:
        print("❌ Missing API tokens!")
        return False

    # Setup session with auth
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Token {token_id}:{token_secret}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )

    # Test different endpoints
    endpoints = ["/api/docs", "/api/books", "/api/pages"]

    for endpoint in endpoints:
        url = f"{base_url.rstrip('/')}{endpoint}"
        print(f"Testing {endpoint}...")

        try:
            response = session.get(url, timeout=10)
            print(f"  Status: {response.status_code}")
            print(f"  Content-Type: {response.headers.get('Content-Type', 'Unknown')}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    if "data" in data:
                        print(f"  Results: {len(data['data'])} items")
                    else:
                        print(f"  Response keys: {list(data.keys())}")
                except Exception:
                    print(f"  Response (first 100 chars): {response.text[:100]}...")
            else:
                print(f"  Error: {response.text[:200]}")

        except Exception as e:
            print(f"  Exception: {e}")

        print()

    return True


if __name__ == "__main__":
    test_bookstack_api()
