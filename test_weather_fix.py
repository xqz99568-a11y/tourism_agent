import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, r'd:\Code\Tourism_Agent')
load_dotenv()

print('=== Testing weather_client after fix ===')

# Reload the module to get fresh values
import importlib
import app.services.weather_client as wc
importlib.reload(wc)

from app.services.weather_client import fetch_weather, _get_api_key, QWEATHER_API_HOST, BASE_URL

print(f'API Host: {QWEATHER_API_HOST}')
print(f'BASE_URL: {BASE_URL}')
print(f'API Key: {_get_api_key()[:10]}...')

# Test fetch_weather
print('\nTesting fetch_weather("北京")...')
result = fetch_weather("北京")
print(f'Result type: {type(result)}')
print(f'Result length: {len(result) if result else 0}')
if result:
    print(f'First item: {result[0]}')
else:
    print('Result is empty!')
