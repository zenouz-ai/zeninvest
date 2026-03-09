"""Simple test script to verify dashboard endpoints."""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_endpoint(path: str, method: str = "GET", data: dict | None = None):
    """Test an endpoint."""
    url = f"{BASE_URL}{path}"
    print(f"\n{method} {path}")
    try:
        if method == "GET":
            response = requests.get(url, timeout=5)
        elif method == "POST":
            response = requests.post(url, json=data, timeout=5)
        else:
            print(f"  ❌ Unsupported method: {method}")
            return
        
        print(f"  Status: {response.status_code}")
        if response.status_code == 200:
            try:
                data = response.json()
                if isinstance(data, list):
                    print(f"  ✅ Response: {len(data)} items")
                elif isinstance(data, dict):
                    print(f"  ✅ Response keys: {list(data.keys())[:5]}")
                else:
                    print(f"  ✅ Response: {str(data)[:100]}")
            except:
                print(f"  ✅ Response: {response.text[:100]}")
        else:
            print(f"  ⚠️  Response: {response.text[:200]}")
    except Exception as e:
        print(f"  ❌ Error: {e}")

if __name__ == "__main__":
    print("Testing Dashboard API Endpoints...")
    print("=" * 50)
    
    # Health check
    test_endpoint("/health")
    
    # Root
    test_endpoint("/")
    
    # Runs
    test_endpoint("/api/runs/")
    
    # Universe
    test_endpoint("/api/universe/")
    
    # Portfolio
    test_endpoint("/api/portfolio/")
    
    # Orders
    test_endpoint("/api/orders/")
    
    # Events
    test_endpoint("/api/events/")
    
    print("\n" + "=" * 50)
    print("Test complete! Check output above for results.")
    print("\nNote: Some endpoints may return empty results if database is empty.")
    print("This is expected for a fresh installation.")
