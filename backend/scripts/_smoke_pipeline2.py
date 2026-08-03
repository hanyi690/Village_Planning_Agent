"""Smoke test (redirected stderr)"""
import sys, os
# 静音所有 log
os.environ['LOG_LEVEL'] = 'CRITICAL'
sys.path.insert(0, '.')

# 把 stderr 重定向
sys.stderr = open(os.devnull, 'w')

from app.modules.data import DataCatalog

catalog = DataCatalog()
bundle = catalog.load_village_bundle('金田')

def get_source(f):
    raw = getattr(f, '_raw', None) or {}
    if isinstance(raw, dict):
        return raw.get('anchor_source', 'local')
    return 'local'

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
print('=== 去重验证 ===')
seen = set()
dups = []
for f in pts:
    coords = f.geometry.get('coordinates', [0, 0]) if hasattr(f, 'geometry') else [0, 0]
    raw = getattr(f, '_raw', None) or {}
    name = (getattr(f, 'text', '') or raw.get('name', '') or raw.get('name_norm', ''))
    key = (name, round(coords[0], 3), round(coords[1], 3))
    if name:
        if key in seen:
            dups.append((name, coords))
        seen.add(key)
print(f'  unique: {len(seen)}, duplicates: {len(dups)}')
if dups[:5]:
    print(f'  sample dups: {dups[:5]}')

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
print('=== _external sub-key (应为 0) ===')
ext_count = 0
for gn in ('points','lines','polygons'):
    for k in getattr(bundle, gn)._layers:
        if k.endswith('_external'):
            ext_count += 1
print(f'  count: {ext_count}')

print()
print('=== annotations_current 前 20 ===')
for i, f in enumerate(pts[:20]):
    raw = getattr(f, '_raw', None) or {}
    name = (getattr(f, 'text', '') or raw.get('name', '') or raw.get('name_norm', ''))
    src = raw.get('anchor_source', 'local')
    cat = raw.get('category', 'n/a')
    coords = f.geometry.get('coordinates', [0, 0])
    print(f'  [{i+1:2}] {name[:18]:<18} src={src:<10} cat={cat:<22} ({coords[0]:.4f}, {coords[1]:.4f})')