"""检查金田村 bundle 的 admin_areas"""
import sys, os
os.environ['LOG_LEVEL'] = 'CRITICAL'
sys.path.insert(0, '.')
from app.modules.data import DataCatalog
catalog = DataCatalog()
catalog.set_admin_meta('金田', province='广东省', city='梅州市',
                       county='平远县', township='泗水镇',
                       adcode_12='441426110000')
bundle = catalog.load_village_bundle('金田')
print('admin_areas:', bundle.polygons.get('admin_areas'))
print('boundary_layer:', bundle.polygons.get('boundary'))
print('admin_boundaries (line):', len(bundle.lines.get('admin_boundaries') or []))

# 测试 point_in_polygon
from app.modules.spatial_ops.geometry import point_in_polygon, village_boundary_geometry
boundary = village_boundary_geometry(bundle)
print('boundary:', boundary is not None)
if boundary:
    # 测试 12 个邻村坐标
    tests = [
        ("金田村委会", 116.0408, 24.8169),
        ("八社村", 116.0473, 24.8504),
        ("上举村", 115.9964, 24.8126),
        ("大柘镇东兴村 (百度 first)", 115.9469, 24.6238),
    ]
    for name, lon, lat in tests:
        inside = point_in_polygon((lon, lat), boundary)
        print(f'  {name} ({lon:.4f},{lat:.4f}): inside={inside}')