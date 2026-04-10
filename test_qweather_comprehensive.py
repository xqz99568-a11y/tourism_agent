import os
import requests
from dotenv import load_dotenv

load_dotenv()

print('=== QWeather API Host and Subscription Test ===')

api_key = os.getenv('QWEATHER_API_KEY')
print(f'API Key: {api_key}')

# Test the commercial API with proper endpoints
hosts_to_test = [
    'api.qweather.com',
    'devapi.qweather.com',
]

# Test both weather and city endpoints
test_cases = [
    ('/v7/weather/3d', {'location': '101010100', 'lang': 'zh'}),
    ('/geo/v2/city/lookup', {'location': '北京', 'lang': 'zh', 'number': 1}),
]

for host in hosts_to_test:
    print(f'\n===== Testing host: {host} =====')
    for endpoint, params in test_cases:
        url = f'https://{host}{endpoint}'
        print(f'\nEndpoint: {endpoint}')
        print(f'URL: {url}')
        print(f'Params: {params}')

        headers = {
            "X-QW-Api-Key": api_key,
            "Accept-Encoding": "gzip",
        }

        try:
            resp = requests.get(url, params={**params, 'key': api_key}, headers=headers, timeout=15)
            print(f'Status: {resp.status_code}')
            data = resp.json()
            print(f'Response keys: {list(data.keys())}')
            if 'code' in data:
                print(f'Code: {data["code"]}')
            if 'error' in data:
                print(f'Error: {data["error"]}')
            if data.get("code") == "200":
                print('SUCCESS!')
                if 'daily' in data:
                    print(f'Daily count: {len(data["daily"])}')
                    if data["daily"]:
                        print(f'First day: {data["daily"][0]}')
        except Exception as e:
            print(f'Error: {e}')

# Also check what subscription type this key might be
print('\n===== Key Analysis =====')
print(f'Key length: {len(api_key)}')
print(f'Key prefix: {api_key[:8]}...')
print('Note: Standard dev key = 32 chars, Commercial key = 32 chars')
print('Both endpoints work on commercial subscription, but require api.qweather.com')
