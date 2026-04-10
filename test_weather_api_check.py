import os
import sys
import requests
from dotenv import load_dotenv

sys.path.insert(0, r'd:\Code\Tourism_Agent')
load_dotenv()

# Manually test the API with new host
api_key = os.getenv('QWEATHER_API_KEY')
print(f'API Key: {api_key[:10]}...')

print('\n=== Testing api.qweather.com directly ===')

# Test 1: Weather API with location ID
url = 'https://api.qweather.com/v7/weather/3d'
headers = {'X-QW-Api-Key': api_key}
params = {'location': '101010100', 'lang': 'zh'}
try:
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    print(f'Status: {resp.status_code}')
    data = resp.json()
    print(f'Response keys: {list(data.keys())}')
    if data.get('code') == '200':
        print('SUCCESS!')
        daily = data.get('daily', [])
        print(f'Daily count: {len(daily)}')
        if daily:
            print(f'First day: {daily[0]}')
    else:
        print(f'Error: {data}')
except Exception as e:
    print(f'Exception: {e}')

# Test 2: City lookup
print('\n=== Testing city lookup ===')
lookup_url = 'https://api.qweather.com/geo/v2/city/lookup'
params = {'location': '北京', 'key': api_key, 'number': 1, 'lang': 'zh'}
try:
    resp = requests.get(lookup_url, params=params, timeout=10)
    print(f'Status: {resp.status_code}')
    data = resp.json()
    print(f'Response keys: {list(data.keys())}')
    if data.get('code') == '200':
        print('SUCCESS!')
        locations = data.get('location', [])
        print(f'Found {len(locations)} locations')
        if locations:
            print(f'First location: {locations[0]}')
    else:
        print(f'Error: {data}')
except Exception as e:
    print(f'Exception: {e}')

# Test 3: Check weather_client._request_weather_payload directly
print('\n=== Testing weather_client._request_weather_payload ===')
from app.services.weather_client import _request_weather_payload, _coerce_location
try:
    payload = _request_weather_payload('101010100', timeout=10)
    print(f'Payload keys: {list(payload.keys())}')
    print(f'Code: {payload.get("code")}')
    if payload.get('code') == '200':
        print('SUCCESS!')
        daily = payload.get('daily', [])
        print(f'Daily count: {len(daily)}')
    else:
        print(f'Error response: {payload}')
except Exception as e:
    print(f'Exception: {e}')
