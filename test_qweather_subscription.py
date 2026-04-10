import os
import requests
from dotenv import load_dotenv

load_dotenv()

print('=== QWeather Subscription Type Check ===')

api_key = os.getenv('QWEATHER_API_KEY')

# The error message says "Invalid Host" - this might mean the key was registered on api.qweather.com but is being used on devapi.qweather.com
# Or vice versa
# Let's check the QWeather subscription page for guidance
# First, let's try all possible combinations

hosts = ['api.qweather.com', 'devapi.qweather.com']
endpoints = [
    '/v7/weather/3d',
    '/v7/weather/7d',
    '/v7/weather/now',
    '/weather/now',
    '/weather/3d',
]

location_id = '101010100'

for host in hosts:
    print(f'\n===== Testing {host} =====')
    for endpoint in endpoints:
        url = f'https://{host}{endpoint}'
        params = {
            'location': location_id,
            'key': api_key,
            'lang': 'zh',
        }
        headers = {'X-QW-Api-Key': api_key}
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()
            if data.get("code") == "200":
                print(f'  SUCCESS: {endpoint}')
                print(f'  Daily: {len(data.get("daily", []))} days')
                break
            else:
                error_type = data.get("error", {}).get("title", "") if isinstance(data, dict) else ""
                if error_type == "Invalid Host":
                    print(f'  INVALID HOST: {endpoint}')
                elif data.get("code"):
                    print(f'  Error {data.get("code")}: {endpoint}')
                else:
                    print(f'  {error_type}: {endpoint}')
        except Exception as e:
            print(f'  Exception: {e}')
