"""诊断百度/腾讯 pipeline 注入 0 features 的根因"""
import sys, os
os.environ['LOG_LEVEL'] = 'CRITICAL'
sys.path.insert(0, '.')
from app.modules.data.providers.baidu.provider import BaiduProvider
from app.modules.data.providers.tencent.provider import TencentMapProvider

print('=== 百度 v3 region (query=村, region=梅州市平远县) ===')
b = BaiduProvider()
r = b.search_region('村', region='梅州市平远县', region_limit=True, page_size=5)
print(f'  success={r.success}, error={r.error}')
results = (r.data or {}).get('results', [])
print(f'  results count: {len(results)}')
if results:
    p = results[0]
    print(f'  first: name={p.get("name")}, lon={p.get("lon")}, lat={p.get("lat")}')
    print(f'  addr: {p.get("address", "")[:80]}')

print()
print('=== 百度 v3 region (region=441426 adcode) ===')
r = b.search_region('村', region='441426', region_limit=True, page_size=5)
print(f'  success={r.success}, error={r.error}')
results = (r.data or {}).get('results', [])
print(f'  results count: {len(results)}')

print()
print('=== 腾讯 v1 region (boundary=region(441426,0)) ===')
t = TencentMapProvider()
r = t.search_region('村', region='441426', page_size=5)
print(f'  success={r.success}, error={r.error}')
results = (r.data or {}).get('pois', [])
print(f'  pois count: {len(results)}')
if results:
    p = results[0]
    print(f'  first: title={p.get("title")}')
    print(f'  location: {p.get("location")}')

print()
print('=== 腾讯 v1 region (boundary=region(梅州市平远县,0)) ===')
r = t.search_region('村', region='梅州市平远县', page_size=5)
print(f'  success={r.success}, error={r.error}')
print(f'  pois count: {len((r.data or {}).get("pois", []))}')

print()
print('=== 百度 AMap geocode (金田村委会) ===')
from app.modules.data.providers.amap.provider import AmapProvider
a = AmapProvider()
r = a.geocode('广东省梅州市平远县泗水镇金田村委会', city='梅州市')
print(f'  success={r.success}, error={r.error}')
print(f'  location: {r.data.get("lon") if r.data else None}, {r.data.get("lat") if r.data else None}')
print(f'  level: {r.data.get("level") if r.data else None}')