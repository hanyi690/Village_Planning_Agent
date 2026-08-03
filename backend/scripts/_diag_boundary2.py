"""检查金田村 boundary 的精确范围"""
import sys, os
os.environ['LOG_LEVEL'] = 'CRITICAL'
sys.path.insert(0, '.')
from app.modules.data import DataCatalog
from app.modules.spatial_ops.geometry import village_boundary_geometry, point_in_polygon
catalog = DataCatalog()
catalog.set_admin_meta('金田', province='广东省', city='梅州市',
                       county='平远县', township='泗水镇',
                       adcode_12='441426110000')
bundle = catalog.load_village_bundle('金田')
boundary = village_boundary_geometry(bundle)
print('boundary is None:', boundary is None)
if boundary:
    gtype = boundary.get('type')
    coords = boundary.get('coordinates', [])
    print(f'  type={gtype}, rings={len(coords)}')
    if coords:
        ring = coords[0]
        lons = [c[0] for c in ring]
        lats = [c[1] for c in ring]
        print(f'  bbox: lon [{min(lons):.5f}, {max(lons):.5f}], lat [{min(lats):.5f}, {max(lats):.5f}]')

# 测试多个点
tests = [
    ('本地金田村委会', 116.0408, 24.8169),
    ('本地八社村', 116.0473, 24.8504),
    ('本地符坑村', 116.0155, 24.8022),
    ('本地文贵村', 116.0487, 24.8048),
    ('A Map 金田村委会', 116.0360, 24.8196),
    ('A Map 石窟河', 116.0684, 24.8352),
    ('A Map 长潭水库', 116.0697, 24.8406),
    ('A Map 牙子寨', 116.0690, 24.8521),
    ('百度 角坑村', 115.7965, 24.7465),
    ('百度 黄畲村', 115.8435, 24.8122),
    ('百度 梅畲村', 116.0471, 24.7250),
    ('腾讯 东兴村', 115.9469, 24.6238),
]
print('\n=== point_in_polygon 测试 ===')
for name, lon, lat in tests:
    if boundary:
        inside = point_in_polygon((lon, lat), boundary)
        print(f'  {"IN " if inside else "OUT"} {name}: ({lon:.4f},{lat:.4f})')
    else:
        print(f'  ??? {name}: no boundary')