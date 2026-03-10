"""Simple test script to verify dashboard endpoints (original + full API)."""

import sys

import requests

BASE_URL = "http://localhost:8000"

# 503 = dashboard disabled in config; 404 = no data; both are "endpoint exists"
OK_STATUSES = {200, 404, 503}


def test_endpoint(path: str, method: str = "GET", data: dict | None = None) -> bool:
    """Test an endpoint. Returns True if request reached the server (2xx/4xx/5xx)."""
    url = f"{BASE_URL}{path}"
    print(f"\n{method} {path}")
    try:
        if method == "GET":
            response = requests.get(url, timeout=5)
        elif method == "POST":
            response = requests.post(url, json=data or {}, timeout=5)
        else:
            print(f"  ❌ Unsupported method: {method}")
            return False

        print(f"  Status: {response.status_code}")
        if response.status_code in OK_STATUSES:
            try:
                body = response.json()
                if isinstance(body, list):
                    print(f"  ✅ Response: {len(body)} items")
                elif isinstance(body, dict):
                    keys = list(body.keys())[:8]
                    print(f"  ✅ Response keys: {keys}")
                else:
                    print(f"  ✅ Response: {str(body)[:100]}")
            except Exception:
                print(f"  ✅ Response: {response.text[:100]}")
            return True
        print(f"  ⚠️  Response: {response.text[:200]}")
        return False
    except requests.exceptions.ConnectionError:
        print(f"  ❌ Connection failed. Is the server running on {BASE_URL}?")
        return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def main() -> int:
    print("Testing Dashboard API Endpoints (full API)...")
    print("=" * 50)

    endpoints = [
        ("/health", "GET"),
        ("/", "GET"),
        ("/api/status/", "GET"),
        ("/api/runs/", "GET"),
        ("/api/universe/", "GET"),
        ("/api/portfolio/", "GET"),
        ("/api/orders/", "GET"),
        ("/api/events/", "GET"),
        ("/api/decisions/", "GET"),
        ("/api/decisions/waterfall?cycle_id=test&ticker=AAPL_US_EQ", "GET"),
        ("/api/moderation/test-cycle", "GET"),
        ("/api/risk/test-cycle", "GET"),
        ("/api/opportunity/scores/", "GET"),
        ("/api/opportunity/queue/", "GET"),
        ("/api/outcomes/", "GET"),
        ("/api/outcomes/stats", "GET"),
        ("/api/stop-loss/current", "GET"),
        ("/api/stop-loss/adjustments", "GET"),
        ("/api/performance/metrics", "GET"),
        ("/api/performance/history", "GET"),
        ("/api/costs/daily", "GET"),
        ("/api/costs/monthly", "GET"),
        ("/api/costs/degradation", "GET"),
        ("/api/api-usage/daily", "GET"),
        ("/api/system/state", "GET"),
    ]
    ok = 0
    for path, method in endpoints:
        if test_endpoint(path, method):
            ok += 1

    print("\n" + "=" * 50)
    print(f"Result: {ok}/{len(endpoints)} endpoints reached (200/404/503 = OK).")
    print("\nNote: 503 = dashboard disabled in config/settings.yaml (dashboard.enabled: true).")
    print("Empty lists or 404 are normal if the database has no runs/decisions yet.")
    return 0 if ok == len(endpoints) else 1


if __name__ == "__main__":
    sys.exit(main())
