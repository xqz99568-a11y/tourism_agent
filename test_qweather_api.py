import os
import sys
import requests

sys.path.insert(0, r'd:\Code\Tourism_Agent')

# Load dotenv
from dotenv import load_dotenv
load_dotenv()

print('=== QWeather API Direct Test ===')

api_key = os.getenv('QWEATHER_API_KEY')
print(f'API Key: {api_key[:10]}...')

# Test city lookup first
lookup_url = 'https://devapi.qweather.com/geo/v2/city/lookup'
params = {
    'location': '北京',
    'key': api_key,
    'number': 1,
    'lang': 'zh',
}
print(f'\n1. Testing city lookup for "北京"')
print(f'URL: {lookup_url}')
print(f'Params: location={params["location"]}, key=***, lang={params["lang"]}')

try:
    resp = requests.get(lookup_url, params=params, timeout=10)
    print(f'Response status: {resp.status_code}')
    data = resp.json()
    print(f'Response code: {data.get("code")}')
    if data.get("location"):
        print(f'Location found: {data["location"][0]}')
    else:
        print(f'Full response: {data}')
except Exception as e:
    print(f'Error: {e}')

# Test weather API with location ID
weather_url = 'https://devapi.qweather.com/v7/weather/3d'
location_id = '101010100'  # Beijing

print(f'\n2. Testing weather API with Beijing ID: {location_id}')
print(f'URL: {weather_url}')

try:
    headers = {
        "X-QW-Api-Key": api_key,
        "Accept-Encoding": "gzip",
    }
    params = {
        "location": location_id,
        "key": api_key,
        "lang": "zh",
    }
    resp = requests.get(weather_url, params=params, headers=headers, timeout=10)
    print(f'Response status: {resp.status_code}')
    data = resp.json()
    print(f'Response code: {data.get("code")}')
    if data.get("code") == "200":
        daily = data.get("daily", [])
        print(f'Daily forecast count: {len(daily)}')
        if daily:
            print(f'First day: {daily[0]}')
    else:
        print(f'Full response: {data}')
except Exception as e:
    print(f'Error: {e}')

# Test weather API with city name
print(f'\n3. Testing weather API with city name "北京"')
try:
    params = {
        "location": "北京",
        "key": api_key,
        "lang": "zh",
    }
    resp = requests.get(weather_url, params=params, headers=headers, timeout=10)
    print(f'Response status: {resp.status_code}')
    data = resp.json()
    print(f'Response code: {data.get("code")}')
    if data.get("code") == "200":
        daily = data.get("daily", [])
        print(f'Daily forecast count: {len(daily)}')
    else:
        print(f'Full response: {data}')
except Exception as e:
    print(f'Error: {e}')
