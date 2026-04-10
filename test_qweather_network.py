import os
import requests
from dotenv import load_dotenv

load_dotenv()

print('=== QWeather Network Traffic Capture ===')

api_key = os.getenv('QWEATHER_API_KEY')
print(f'API Key: {api_key}')

# Intercept-level debugging: check if maybe there's a proxy or DNS issue
# Try with and without SSL verification
import urllib3
urllib3.disable_warnings()

# Test 1: Check if maybe the key needs ONLY header auth (not key param)
print('\n===== Test: Header only (no key param) =====')
url = 'https://devapi.qweather.com/v7/weather/3d'
headers = {'X-QW-Api-Key': api_key}
params = {'location': '101010100', 'lang': 'zh'}
try:
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    print(f'Status: {resp.status_code}')
    print(f'Response: {resp.text[:300]}')
except Exception as e:
    print(f'Error: {e}')

# Test 2: Check if maybe the key is for a DIFFERENT product
# E.g., the key might be registered for "Weather" but not for "Geo"
print('\n===== Test: Try weather endpoint only =====')
# Different endpoints to try
test_urls = [
    ('https://devapi.qweather.com/v7/weather/3d?location=101010100&key=' + api_key, 'devapi weather 3d'),
    ('https://api.qweather.com/v7/weather/3d?location=101010100&key=' + api_key, 'api weather 3d'),
]
for url, desc in test_urls:
    print(f'\n--- {desc} ---')
    try:
        resp = requests.get(url, timeout=10)
        print(f'Status: {resp.status_code}')
        print(f'Response: {resp.text[:300]}')
    except Exception as e:
        print(f'Error: {e}')

# Test 3: Check if this is a network/DNS issue specific to this machine
print('\n===== Test: Check DNS resolution =====')
try:
    import socket
    ip = socket.getaddrinfo('devapi.qweather.com', 443)
    print(f'devapi.qweather.com resolves to: {ip}')
except Exception as e:
    print(f'DNS error: {e}')

try:
    ip2 = socket.getaddrinfo('api.qweather.com', 443)
    print(f'api.qweather.com resolves to: {ip2}')
except Exception as e:
    print(f'DNS error: {e}')

# Test 4: Maybe it's a network restriction in China
print('\n===== Test: Check connectivity =====')
test_sites = [
    ('https://devapi.qweather.com', 'QWeather devapi'),
    ('https://api.qweather.com', 'QWeather api'),
    ('https://www.baidu.com', 'Baidu'),
    ('https://www.google.com', 'Google'),
]
for url, name in test_sites:
    try:
        resp = requests.head(url, timeout=5)
        print(f'{name}: {resp.status_code}')
    except Exception as e:
        print(f'{name}: FAILED - {e}')
