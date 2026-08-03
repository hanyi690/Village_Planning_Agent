import sys, os
os.environ['LOG_LEVEL'] = 'CRITICAL'
sys.path.insert(0, '.')
from app.modules.data import DataCatalog

catalog = DataCatalog()
# 预设 admin meta (梅州市平远县泗水镇金田村)
catalog.set_admin_meta(
    '金田',
    province='广东省', city='梅州市',
    county='平远县', township='泗水镇',
    adcode_12='441426110000',
)
bundle = catalog.load_village_bundle('金田')

print('=== metadata 自动填充 ===')
print(f'  province: {bundle.metadata.province!r}')
print(f'  city: {bundle.metadata.city!r}')
print(f'  county: {bundle.metadata.county!r}')
print(f'  township: {bundle.metadata.township!r}')
print(f'  adcode_12: {bundle.metadata.adcode_12!r}')

def get_source(f):
    raw = getattr(f, '_raw', None) or {}
    if isinstance(raw, dict):
        return raw.get('anchor_source', 'local')
    return 'local'

print()
print('=== annotations_current 内容 ===')
pts = bundle.points.get('annotations_current') or []
sources = {}
for f in pts:
    src = get_source(f)
    sources[src] = sources.get(src, 0) + 1
print(f'  total: {len(pts)}')
for src, n in sorted(sources.items()):
    print(f'  {src}: {n}')

print()
print('=== water_bodies / roads_current ===')
wb = bundle.polygons.get('water_bodies') or []
roads = bundle.lines.get('roads_current') or []
wb_sources = {}
for f in wb:
    wb_sources[get_source(f)] = wb_sources.get(get_source(f), 0) + 1
print(f'  water_bodies: total={len(wb)}, sources={wb_sources}')
roads_sources = {}
for f in roads:
    roads_sources[get_source(f)] = roads_sources.get(get_source(f), 0) + 1
print(f'  roads_current: total={len(roads)}, sources={roads_sources}')

print()
print('=== 外部 source 前 30 个 ===')
external_count = 0
for f in pts[:60]:
    src = get_source(f)
    raw = getattr(f, '_raw', None) or {}
    if isinstance(raw, dict) and src != 'local':
        external_count += 1
        coords = f.geometry.get('coordinates', [0, 0])
        name = (raw.get('name') or raw.get('name_norm') or '')[:20]
        cat = raw.get('category', 'n/a')
        print(f'  EXT: {name:<20} src={src:<14} cat={cat:<22} ({coords[0]:.4f},{coords[1]:.4f})')
print(f'  external sample shown: {external_count}')

print()
print('=== _external sub-key (应为 0) ===')
ext_count = 0
for gn in ('points','lines','polygons'):
    for k in getattr(bundle, gn)._layers:
        if k.endswith('_external'):
            ext_count += 1
            print(f'  ⚠ {gn}.{k}')
print(f'  count: {ext_count}')