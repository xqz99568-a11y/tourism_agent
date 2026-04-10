import os
import requests
from dotenv import load_dotenv

load_dotenv()

print('=== QWeather API Auth Methods Test ===')

api_key = os.getenv('QWEATHER_API_KEY')
print(f'API Key: {api_key}')

location_id = '101010100'

# Test 1: devapi with key param only (no header)
print('\n===== Test 1: devapi.qweather.com with key param only =====')
url = 'https://devapi.qweather.com/v7/weather/3d'
params = {
    'location': location_id,
    'key': api_key,
    'lang': 'zh',
}
try:
    resp = requests.get(url, params=params, timeout=15)
    print(f'Status: {resp.status_code}')
    data = resp.json()
    print(f'Response: {data}')
    if data.get("code") == "200":
        daily = data.get("daily", [])
        print(f'SUCCESS! Daily count: {len(daily)}')
        if daily:
            print(f'First day: {daily[0]}')
except Exception as e:
    print(f'Error: {e}')

# Test 2: devapi with X-QW-Api-Key header
print('\n===== Test 2: devapi.qweather.com with X-QW-Api-Key header =====')
headers = {
    "X-QW-Api-Key": api_key,
}
params = {
    'location': location_id,
    'lang': 'zh',
}
try:
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    print(f'Status: {resp.status_code}')
    data = resp.json()
    print(f'Response: {data}')
except Exception as e:
    print(f'Error: {e}')

# Test 3: devapi with both key param and header
print('\n===== Test 3: devapi.qweather.com with both key param and header =====')
headers = {
    "X-QW-Api-Key": api_key,
}
params = {
    'location': location_id,
    'key': api_key,
    'lang': 'zh',
}
try:
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    print(f'Status: {resp.status_code}')
    data = resp.json()
    print(f'Response: {data}')
except Exception as e:
    print(f'Error: {e}')

# Test 4: api.qweather.com (commercial)
print('\n===== Test 4: api.qweather.com (commercial) =====')
url_com = 'https://api.qweather.com/v7/weather/3d'
params = {
    'location': location_id,
    'key': api_key,
    'lang': 'zh',
}
try:
    resp = requests.get(url_com, params=params, timeout=15)
    print(f'Status: {resp.status_code}')
    data = resp.json()
    print(f'Response: {data}')
except Exception as e:
    print(f'Error: {e}')

# Test 5: city lookup
print('\n===== Test 5: devapi city lookup =====')
url_geo = 'https://devapi.qweather.com/geo/v2/city/lookup'
params = {
    'location': '北京',
    'key': api_key,
    'lang': 'zh',
    'number': 1,
}
try:
    resp = requests.get(url_geo, params=params, timeout=15)
    print(f'Status: {resp.status_code}')
    data = resp.json()
    print(f'Response: {data}')
except Exception as e:
    print(f'Error: {e}')
