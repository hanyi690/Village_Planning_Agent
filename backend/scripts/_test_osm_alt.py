"""OSM API 测试 — 直接试 Nominatim + Overpass (调试 query 格式)"""
import requests

# Test 1: Nominatim simple search
print("=== Test 1: Nominatim ===")
try:
    r = requests.get(
        'https://nominatim.openstreetmap.org/search',
        params={'q': '金田村, 平远县, 梅州市, 广东省', 'format': 'json',
                'limit': 3, 'countrycodes': 'cn'},
        headers={'User-Agent': 'VillagePlanningAgent/1.0'},
        timeout=15,
    )
    print(f'Status: {r.status_code}')
    if r.status_code == 200:
        data = r.json()
        print(f'Results: {len(data)}')
        for d in data:
            print(f'  {d.get("display_name","")[:80]}')
            print(f'    ({d["lat"]}, {d["lon"]}) type={d.get("type")} class={d.get("class")}')
    else:
        print(f'Raw: {r.text[:300]}')
except Exception as e:
    print(f'ERROR: {e}')

print()

# Test 2: Overpass - simplest query
print("=== Test 2: Overpass simplest ===")
try:
    q = '[out:json];node(24.81,116.04,24.82,116.05);out;'
    r = requests.post(
        'https://overpass-api.de/api/interpreter',
        data={'data': q},
        headers={'User-Agent': 'VillagePlanningAgent/1.0'},
        timeout=15,
    )
    print(f'Status: {r.status_code}')
    if r.status_code == 200:
        data = r.json()
        print(f'  elements: {len(data.get("elements", []))}')
    else:
        print(f'  Raw: {r.text[:300]}')
except Exception as e:
    print(f'ERROR: {e}')

print()

# Test 3: Overpass - with place tag
print("=== Test 3: Overpass place=village ===")
try:
    q = '''[out:json];
node["place"="village"](24.77,116.00,24.87,116.10);
out center;'''
    r = requests.post(
        'https://overpass-api.de/api/interpreter',
        data={'data': q},
        headers={'User-Agent': 'VillagePlanningAgent/1.0'},
        timeout=15,
    )
    print(f'Status: {r.status_code}')
    if r.status_code == 200:
        data = r.json()
        elements = data.get('elements', [])
        print(f'  elements: {len(elements)}')
        for e in elements[:5]:
            tags = e.get('tags', {})
            print(f'    {tags.get("name", "")} ({e.get("lat")}, {e.get("lon")})')
    else:
        print(f'  Raw: {r.text[:500]}')
except Exception as e:
    print(f'ERROR: {e}')