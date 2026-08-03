"""raw curl 测试 region=441426110000 是否被腾讯 API 接受"""
import requests
import json

# 测试 1: 6位 adcode
r1 = requests.get('https://apis.map.qq.com/ws/place/v1/search', params={
    'keyword': '村', 'boundary': 'region(441426,0)', 'page_size': 5,
    'coord_type': 'wgs84', 'key': '7NMBZ-TX4L7-QFHXG-HLJGK-K5OGO-JQBDL',
}, timeout=10)
d1 = r1.json()
print(f'region(441426,0): count={d1.get("count")}, returned={len(d1.get("data", []))}')

# 测试 2: 12 位 adcode
r2 = requests.get('https://apis.map.qq.com/ws/place/v1/search', params={
    'keyword': '村', 'boundary': 'region(441426110000,0)', 'page_size': 5,
    'coord_type': 'wgs84', 'key': '7NMBZ-TX4L7-QFHXG-HLJGK-K5OGO-JQBDL',
}, timeout=10)
d2 = r2.json()
print(f'region(441426110000,0): count={d2.get("count")}, returned={len(d2.get("data", []))}')
print(f'  status={d2.get("status")}, message={d2.get("message")}')

# 测试 3: 用 city+county 中文名
r3 = requests.get('https://apis.map.qq.com/ws/place/v1/search', params={
    'keyword': '村', 'boundary': 'region(梅州市平远县,0)', 'page_size': 5,
    'coord_type': 'wgs84', 'key': '7NMBZ-TX4L7-QFHXG-HLJGK-K5OGO-JQBDL',
}, timeout=10)
d3 = r3.json()
print(f'region(梅州市平远县,0): count={d3.get("count")}, returned={len(d3.get("data", []))}')