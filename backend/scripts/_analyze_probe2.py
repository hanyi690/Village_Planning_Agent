import json

with open('scripts/_amap_probe_jintian.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

print('=== P1 9 个命中的 first POI 详情 ===')
for name, r in d['p1'].items():
    if not r.get('hit'):
        continue
    f_poi = r.get('first') or {}
    pname = str(f_poi.get('name', ''))
    ptc = str(f_poi.get('typecode', ''))
    paddr = str(f_poi.get('address', ''))
    print('  name={} typecode={} addr={}'.format(name, ptc, paddr[:60]))
    print('    first_poi_name={}'.format(pname))

print()
print('=== P1 与 P2 是否一致 ===')
same = 0
for name in d['p1']:
    p1_names = d['p1'][name].get('all_names', [])
    p2_names = d['p2'][name].get('all_names', [])
    if p1_names == p2_names:
        same += 1
print('完全相同 {}/12'.format(same))

print()
print('=== P3 12 命中 (lon, lat) 列表 ===')
coords = set()
for name, r in d['p3'].items():
    coords.add((round(r.get('lon', 0), 4), round(r.get('lat', 0), 4)))
    print('  {}: ({:.5f}, {:.5f})'.format(
        name, r.get('lon', 0), r.get('lat', 0)))
print('不同坐标数: {}'.format(len(coords)))

print()
print('=== P3b 邻村 ===')
for name, r in d['p3b'].items():
    print('  {}: ({:.5f}, {:.5f}) level={} addr={}'.format(
        name, r.get('lon', 0), r.get('lat', 0),
        r.get('level'), r.get('formatted_address')))

print()
print('=== P5a 周边 村 typecode 分布 ===')
print('typecodes_seen:', d['p5a_village']['typecodes_seen'])
for n in d['p5a_village']['all_names']:
    print('  -', n)