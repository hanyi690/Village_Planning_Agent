"""Smoke test: 跑 ExternalAnchorPipeline on 金田村 bundle"""
import sys, os
os.environ['LOG_LEVEL'] = 'ERROR'
sys.path.insert(0, '.')

from app.modules.data import DataCatalog

catalog = DataCatalog()
bundle = catalog.load_village_bundle('金田')

def get_source(f):
    """Safe get of anchor_source from feature."""
    raw = getattr(f, '_raw', None) or {}
    if isinstance(raw, dict):
        return raw.get('anchor_source', 'local')
    return 'local'

print('=== annotations_current 内容 (注入后) ===')
pts = bundle.points.get('annotations_current') or []
sources = {}
for f in pts:
    src = get_source(f)
    sources[src] = sources.get(src, 0) + 1
print(f'  total: {len(pts)}')
for src, n in sorted(sources.items()):
    print(f'  {src}: {n}')

print()
print('=== 验证去重 (annotations_current 内 name+coord 唯一) ===')
seen = set()
dups = []
for f in pts:
    coords = f.geometry.get('coordinates', [0, 0]) if hasattr(f, 'geometry') else [0, 0]
    name = (getattr(f, 'text', '') or
            (getattr(f, '_raw', None) or {}).get('name_norm', '') or
            (getattr(f, '_raw', None) or {}).get('name', ''))
    key = (name, round(coords[0], 3), round(coords[1], 3))
    if name:
        if key in seen:
            dups.append((name, coords))
        seen.add(key)
print(f'  unique: {len(seen)}, duplicates: {len(dups)}')
if dups[:5]:
    print(f'  sample dups: {dups[:5]}')

print()
print('=== 水库/道路外源注入 ===')
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
print('=== 所有 _external sub-key (验证已注入到现有 sub-key) ===')
external_count = 0
for group_name in ('points', 'lines', 'polygons'):
    group = getattr(bundle, group_name)
    for k in group._layers:
        if k.endswith('_external'):
            print(f'  ⚠ {group_name}.{k} (应没有)')
            external_count += 1
print(f'  ({"空 = 正确, " if external_count == 0 else ""}外部 sub-key 数: {external_count})')

print()
print('=== annotations_current 中前 15 个 POI (验证注入) ===')
for i, f in enumerate(pts[:15]):
    raw = getattr(f, '_raw', None) or {}
    name = (getattr(f, 'text', '') or
            raw.get('name', '') or raw.get('name_norm', ''))
    src = raw.get('anchor_source', 'local')
    cat = raw.get('category', 'n/a')
    coords = f.geometry.get('coordinates', [0, 0])
    print(f'  [{i+1:2}] {name[:18]:<18} src={src:<10} cat={cat:<22} ({coords[0]:.4f}, {coords[1]:.4f})')