import os
import requests

from dotenv import load_dotenv
load_dotenv()

print('=== QWeather API Host Test ===')

api_key = os.getenv('QWEATHER_API_KEY')
api_host = os.getenv('QWEATHER_API_HOST', 'devapi.qweather.com')

print(f'API Key: {api_key[:10]}...')
print(f'Current API Host: {api_host}')

# Try different hosts
hosts_to_test = [
    'api.qweather.com',      # Commercial API
    'devapi.qweather.com',   # Development API
]

location_id = '101010100'  # Beijing

for host in hosts_to_test:
    print(f'\n--- Testing host: {host} ---')
    url = f'https://{host}/v7/weather/3d'
    headers = {
        "X-QW-Api-Key": api_key,
        "Accept-Encoding": "gzip",
    }
    params = {
        "location": location_id,
        "key": api_key,
        "lang": "zh",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        print(f'Status: {resp.status_code}')
        data = resp.json()
        print(f'Response: {data}')
        if data.get("code") == "200":
            daily = data.get("daily", [])
            print(f'SUCCESS! Daily forecast count: {len(daily)}')
            if daily:
                print(f'First day: {daily[0]}')
    except Exception as e:
        print(f'Error: {e}')

# Also test city lookup with commercial host
print(f'\n--- Testing city lookup with commercial host ---')
lookup_url = f'https://api.qweather.com/geo/v2/city/lookup'
params = {
    'location': '北京',
    'key': api_key,
    'number': 1,
    'lang': 'zh',
}
try:
    resp = requests.get(lookup_url, params=params, timeout=10)
    print(f'Status: {resp.status_code}')
    data = resp.json()
    print(f'Response: {data}')
except Exception as e:
    print(f'Error: {e}')
