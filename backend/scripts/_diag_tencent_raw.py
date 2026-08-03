import requests
import json

# raw curl 看腾讯 place/v1/search 真实响应
url = 'https://apis.map.qq.com/ws/place/v1/search'
params = {
    'keyword': '金田',
    'boundary': 'region(441426,0)',
    'page_size': 3,
    'coord_type': 'wgs84',
    'key': '7NMBZ-TX4L7-QFHXG-HLJGK-K5OGO-JQBDL',
}
resp = requests.get(url, params=params, timeout=10)
print('Status:', resp.status_code)
data = resp.json()
print('Top-level keys:', list(data.keys()))
print('status:', data.get('status'), 'message:', data.get('message'))
print()
print('=== Raw data[0] (if exists) ===')
if data.get('data'):
    print(json.dumps(data['data'][0], ensure_ascii=False, indent=2)[:1000])
else:
    print('No data field')
    print('Raw:', json.dumps(data, ensure_ascii=False, indent=2)[:500])