"""检查 boundary 文件 + 跑 point_in_polygon 测试"""
import json, os
for root, dirs, files in os.walk("."):
    for f in files:
        if "boundary" in f.lower() and f.endswith(".geojson"):
            print(os.path.join(root, f))

# 找 boundary.geojson
import glob
boundary_files = glob.glob("data/gis/jintian/**/boundary.geojson", recursive=True)
print("Found:", boundary_files)

if boundary_files:
    with open(boundary_files[0]) as f:
        data = json.load(f)
    feats = data.get('features', [])
    print(f"features count: {len(feats)}")
    for i, feat in enumerate(feats[:3]):
        geom = feat.get('geometry', {})
        coords = geom.get('coordinates', [])
        gtype = geom.get('type')
        if coords:
            ring = coords[0] if gtype == 'Polygon' else coords[0][0]
            lons = [c[0] for c in ring]
            lats = [c[1] for c in ring]
            center = ((min(lons)+max(lons))/2, (min(lats)+max(lats))/2)
            print(f"[{i}] type={gtype}, ring_points={len(ring)}, center=({center[0]:.4f},{center[1]:.4f})")
            print(f"   bbox: lon [{min(lons):.5f}, {max(lons):.5f}]")
            print(f"         lat [{min(lats):.5f}, {max(lats):.5f}]")

# 测试 point_in_polygon
import sys
sys.path.insert(0, ".")
from app.modules.spatial_ops.geometry import point_in_polygon
if boundary_files:
    geom = feats[0].get('geometry', {})
    tests = [
        ('金田村委会', 116.0408, 24.8169),
        ('A Map 金田村委会', 116.0360, 24.8196),
        ('A Map 石窟河', 116.0684, 24.8352),
        ('A Map 长潭水库', 116.0697, 24.8406),
        ('A Map 牙子寨', 116.0690, 24.8521),
        ('百度 角坑村', 115.7965, 24.7465),
        ('百度 黄畲村', 115.8435, 24.8122),
        ('百度 梅畲村', 116.0471, 24.7250),
    ]
    print("\n=== point_in_polygon 测试 ===")
    for name, lon, lat in tests:
        inside = point_in_polygon((lon, lat), geom)
        print(f"  {'IN ' if inside else 'OUT'} {name}: ({lon:.4f},{lat:.4f})")