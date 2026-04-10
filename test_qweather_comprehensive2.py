import os
import requests
from dotenv import load_dotenv

load_dotenv()

print('=== QWeather Comprehensive Check ===')

api_key = os.getenv('QWEATHER_API_KEY')
print(f'API Key: {api_key}')
print(f'Key length: {len(api_key)}')

# Check all possible QWeather hosts and auth methods
print('\n===== Testing different auth combinations =====')

# Method 1: X-QW-Api-Key header
print('\n--- Method 1: X-QW-Api-Key header ---')
for host in ['devapi.qweather.com', 'api.qweather.com']:
    url = f'https://{host}/v7/weather/3d'
    headers = {'X-QW-Api-Key': api_key}
    params = {'location': '101010100', 'lang': 'zh'}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        print(f'{host}: status={resp.status_code}')
        if resp.status_code != 200:
            data = resp.json()
            error = data.get('error', {})
            print(f'  Error: {error.get("title")} - {error.get("detail")}')
    except Exception as e:
        print(f'{host}: Exception - {e}')

# Method 2: key parameter only
print('\n--- Method 2: key parameter only ---')
for host in ['devapi.qweather.com', 'api.qweather.com']:
    url = f'https://{host}/v7/weather/3d'
    params = {'location': '101010100', 'key': api_key, 'lang': 'zh'}
    try:
        resp = requests.get(url, params=params, timeout=10)
        print(f'{host}: status={resp.status_code}')
        if resp.status_code != 200:
            data = resp.json()
            error = data.get('error', {})
            print(f'  Error: {error.get("title")} - {error.get("detail")}')
    except Exception as e:
        print(f'{host}: Exception - {e}')

# Method 3: Both header and param
print('\n--- Method 3: Both header and param ---')
for host in ['devapi.qweather.com', 'api.qweather.com']:
    url = f'https://{host}/v7/weather/3d'
    headers = {'X-QW-Api-Key': api_key, 'Accept-Encoding': 'gzip'}
    params = {'location': '101010100', 'key': api_key, 'lang': 'zh'}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        print(f'{host}: status={resp.status_code}')
        if resp.status_code != 200:
            data = resp.json()
            error = data.get('error', {})
            print(f'  Error: {error.get("title")} - {error.get("detail")}')
    except Exception as e:
        print(f'{host}: Exception - {e}')

# Method 4: Check what happens with wrong key
print('\n--- Method 4: Wrong key test (to compare error messages) ---')
wrong_key = '00000000000000000000000000000000'
url = 'https://devapi.qweather.com/v7/weather/3d'
headers = {'X-QW-Api-Key': wrong_key}
params = {'location': '101010100', 'lang': 'zh'}
try:
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    print(f'Status: {resp.status_code}')
    data = resp.json()
    error = data.get('error', {})
    print(f'Wrong key error: {error.get("title")} - {error.get("detail")}')
except Exception as e:
    print(f'Exception - {e}')

# Method 5: Compare with working example from docs
print('\n--- Method 5: Check if curl works (if available) ---')
import subprocess
try:
    result = subprocess.run(
        ['curl', '-s', '-w', '\\n%{http_code}', f'https://devapi.qweather.com/v7/weather/3d?location=101010100&key={api_key}'],
        capture_output=True, text=True, timeout=15
    )
    print(f'curl status: {result.stdout[-3:]}')
    print(f'curl response: {result.stdout[:200]}')
except FileNotFoundError:
    print('curl not available')
except Exception as e:
    print(f'curl error: {e}')
