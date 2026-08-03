import requests

# 测试 kumi.systems (国内镜像) 是否可达
try:
    r = requests.post(
        'https://overpass.kumi.systems/api/interpreter',
        data={'data': '[out:json][timeout:15];node(116.04,24.81,116.05,24.82);out;'},
        headers={'User-Agent': 'VillagePlanningAgent/1.0'},
        timeout=20,
    )
    print(f'kumi.systems: HTTP {r.status_code}')
    if r.status_code == 200:
        data = r.json()
        print(f'  elements: {len(data.get("elements", []))}')
    else:
        print(f'  raw: {r.text[:200]}')
except Exception as e:
    print(f'kumi.systems ERROR: {e}')

print()

# 测试 overpass-api.de
try:
    r = requests.post(
        'https://overpass-api.de/api/interpreter',
        data={'data': '[out:json][timeout:15];node(116.04,24.81,116.05,24.82);out;'},
        headers={'User-Agent': 'VillagePlanningAgent/1.0'},
        timeout=20,
    )
    print(f'overpass-api.de: HTTP {r.status_code}')
    if r.status_code == 200:
        data = r.json()
        print(f'  elements: {len(data.get("elements", []))}')
    else:
        print(f'  raw: {r.text[:200]}')
except Exception as e:
    print(f'overpass-api.de ERROR: {e}')