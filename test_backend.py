import urllib.request
import json

try:
    response = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)
    print(f"Status: {response.status}")
    print(f"Body: {response.read().decode()}")
except Exception as e:
    print(f"Error: {e}")

# Test streaming endpoint
print("\n--- Testing /chat/stream ---")
try:
    data = json.dumps({"message": "北京3天游"}).encode()
    req = urllib.request.Request(
        'http://127.0.0.1:8000/chat/stream',
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    response = urllib.request.urlopen(req, timeout=10)
    print(f"Status: {response.status}")
    print(f"Content-Type: {response.headers.get('Content-Type')}")
    content = response.read(500)
    print(f"First 500 bytes: {content.decode()}")
except Exception as e:
    print(f"Error: {e}")
