import os
import requests
from dotenv import load_dotenv

load_dotenv()

print('=== QWeather Host Header Analysis ===')

api_key = os.getenv('QWEATHER_API_KEY')

# The "Invalid Host" error from QWeather typically means the request's Host header
# doesn't match what the key is registered for. Let's check if maybe we need
# to use api.qweather.com but the Host header needs to be different.

import urllib3
urllib3.disable_warnings()

# Check if maybe there's a proxy interfering
print('=== Checking proxy settings ===')
proxies = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY') or os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
print(f'Proxy: {proxies}')

# Check if QWeather has a CN domain
print('\n=== Testing alternative domains ===')
for domain in ['qweather.com', 'qweatherapi.com', 'weather.com.cn']:
    try:
        resp = requests.head(f'https://www.{domain}', timeout=5)
        print(f'www.{domain}: {resp.status_code}')
    except Exception as e:
        print(f'www.{domain}: FAILED - {e}')

# Test if maybe the issue is specific to the /v7/ endpoint
print('\n=== Testing root endpoint ===')
for host in ['devapi.qweather.com', 'api.qweather.com']:
    try:
        resp = requests.get(f'https://{host}', timeout=10)
        print(f'{host}: status={resp.status_code}')
        print(f'  Headers: {dict(resp.headers)}')
    except Exception as e:
        print(f'{host}: FAILED - {e}')

# Test: Maybe the API needs to be called with specific Accept header
print('\n=== Testing with different Accept headers ===')
url = 'https://devapi.qweather.com/v7/weather/3d'
for accept in ['application/json', '*/*', 'application/json; charset=utf-8']:
    headers = {
        'X-QW-Api-Key': api_key,
        'Accept': accept,
    }
    params = {'location': '101010100', 'lang': 'zh'}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        error = data.get('error', {})
        if error:
            print(f'Accept={accept}: {error.get("title")}')
        else:
            print(f'Accept={accept}: SUCCESS - code={data.get("code")}')
    except Exception as e:
        print(f'Accept={accept}: Exception - {e}')

# The smoking gun: test from a known working API
print('\n=== Sanity check: test known working API ===')
try:
    resp = requests.get('https://httpbin.org/get', timeout=10)
    print(f'httpbin.org: {resp.status_code}')
except Exception as e:
    print(f'httpbin.org: FAILED - {e}')
