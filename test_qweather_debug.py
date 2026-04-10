import os
import requests
from dotenv import load_dotenv

load_dotenv()

print('=== QWeather Debug: Check actual URL being called ===')

api_key = os.getenv('QWEATHER_API_KEY')

# Test 1: Build URL exactly as weather_client.py does
print('\n===== Test: exact replication of _request_weather_payload =====')
BASE_URL = "https://devapi.qweather.com/v7/weather/3d"

# Note: _request_weather_payload passes "key" as a param AND sets X-QW-Api-Key header
headers = {
    "X-QW-Api-Key": api_key,
    "Accept-Encoding": "gzip",
}

params = {
    "location": "101010100",
    "key": api_key,
    "lang": "zh",
}

# requests.get normalizes params - let's check the exact URL
req = requests.Request('GET', BASE_URL, params=params, headers=headers)
prepped = req.prepare()
print(f'Full URL being called: {prepped.url}')

# Now make the request
session = requests.Session()
try:
    resp = session.send(prepped, timeout=15)
    print(f'Status: {resp.status_code}')
    print(f'Final URL (after redirects): {resp.url}')
    print(f'Response: {resp.text[:500]}')
except Exception as e:
    print(f'Error: {e}')

# Test 2: Try without Accept-Encoding header
print('\n===== Test: without Accept-Encoding header =====')
headers2 = {
    "X-QW-Api-Key": api_key,
}
params2 = {
    "location": "101010100",
    "key": api_key,
    "lang": "zh",
}
req2 = requests.Request('GET', BASE_URL, params=params2, headers=headers2)
prepped2 = req2.prepare()
print(f'Full URL: {prepped2.url}')
try:
    resp2 = requests.get(BASE_URL, params=params2, headers=headers2, timeout=15)
    print(f'Status: {resp2.status_code}')
    print(f'Response: {resp2.text[:500]}')
except Exception as e:
    print(f'Error: {e}')

# Test 3: Check if devapi.qweather.com has a working endpoint
print('\n===== Test: Check if host is accessible at all =====')
try:
    resp3 = requests.get('https://devapi.qweather.com', timeout=10)
    print(f'Status: {resp3.status_code}')
    print(f'Response: {resp3.text[:200]}')
except Exception as e:
    print(f'Error: {e}')

# Test 4: Check headers of the error response
print('\n===== Test: Check response headers from 403 =====')
try:
    resp4 = requests.get(BASE_URL, params=params, headers=headers, timeout=15)
    print(f'Status: {resp4.status_code}')
    print(f'Headers: {dict(resp4.headers)}')
except Exception as e:
    print(f'Error: {e}')
