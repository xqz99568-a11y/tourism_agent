import os
import sys

# Ensure we can import from app
sys.path.insert(0, r'd:\Code\Tourism_Agent')

print('=== Testing Environment Variables ===')

# Check .env file exists
env_path = r'd:\Code\Tourism_Agent\.env'
if os.path.exists(env_path):
    print(f'.env file exists at {env_path}')
    with open(env_path, encoding='utf-8') as f:
        for line in f:
            if 'QWEATHER' in line:
                print(f'  Found in .env: {line.strip()}')
else:
    print('.env file NOT found')

# Check environment variable
key = os.getenv('QWEATHER_API_KEY')
print(f'\nQWEATHER_API_KEY from os.getenv: {key}')

# Check dotenv loading
try:
    from dotenv import load_dotenv
    load_dotenv()
    print('load_dotenv() called')
    key_after = os.getenv('QWEATHER_API_KEY')
    print(f'QWEATHER_API_KEY after load_dotenv: {key_after}')
except ImportError:
    print('dotenv not installed')
except Exception as e:
    print(f'dotenv error: {e}')

# Try importing weather client
print('\n=== Testing weather_client ===')
try:
    from app.services.weather_client import fetch_weather, _get_api_key, OpenMeteoWeatherClient
    api_key = _get_api_key()
    print(f'API Key from _get_api_key(): {api_key[:10]}...' if api_key and len(api_key) > 10 else f'API Key: {api_key}')

    # Test the fetch_weather function
    print('\nTesting fetch_weather("北京")...')
    result = fetch_weather("北京")
    print(f'fetch_weather result type: {type(result)}')
    print(f'fetch_weather result length: {len(result) if result else 0}')
    if result:
        print(f'First item: {result[0]}')
    else:
        print('Result is empty - API call likely failed')
except Exception as e:
    print(f'Error importing/using weather_client: {e}')
    import traceback
    traceback.print_exc()
