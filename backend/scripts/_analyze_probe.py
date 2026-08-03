import json

with open('scripts/_amap_probe_jintian.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

print('=== P6 reverse_geocode (is_internal 异常排查) ===')
for name, r in d['p6_reverse_geocode'].items():
    fmt = r.get('formatted_address', '') or ''
    is_in = r.get('is_internal', None)
    has_jt = ('金田' in fmt)
    print('  {:<6}: is_internal={} has_jintian={} fmt={}'.format(
        name, is_in, has_jt, fmt))

print()
print('=== P3 full geocode level 分布 ===')
levels = {}
for name, r in d['p3'].items():
    lv = r.get('level', '')
    levels[lv] = levels.get(lv, 0) + 1
for name, r in d['p3'].items():
    ad = r.get('adcode', '')
    print('  {:<6}: level={:<10} adcode={}'.format(name, lv, ad))
print('Level 分布:', levels)

print()
print('=== P1 漏命中的 3 个 ===')
for name, r in d['p1'].items():
    if not r.get('hit'):
        print('  ', name, '=>', r)

print()
print('=== P3b 邻村 ===')
for name, r in d['p3b'].items():
    print('  {}: level={} addr={}'.format(
        name, r.get('level'), r.get('formatted_address')))

print()
print('=== P9 batched 完整 ===')
for k, v in d['p9_batched'].items():
    print('  {}: {}'.format(k, v))

print()
print('=== P5a 周边 村 完整名单 ===')
print('count:', d['p5a_village']['count'])
print('all_names:', d['p5a_village']['all_names'])
print('typecodes_seen:', d['p5a_village']['typecodes_seen'])

print()
print('=== P5c 河 完整 ===')
print('all_names:', d['p5c_river']['all_names'])

print()
print('=== P4 190000 类别样本 ===')
print('  count:', d['p4_typecodes']['190000']['count'])
print('  typecodes_seen:', d['p4_typecodes']['190000']['typecodes_seen'])
print('  first_10_names:', d['p4_typecodes']['190000']['all_names'][:10])