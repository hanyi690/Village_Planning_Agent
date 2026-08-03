"""读 boundary.geojson 看金田村实际边界"""
import json, sys, os
os.environ["LOG_LEVEL"] = "CRITICAL"
sys.path.insert(0, ".")

# 读 boundary.geojson
with open(r"data\gis\jintian\current\boundary.geojson") as f:
    data = json.load(f)
feats = data.get("features", [])
print(f"features count: {len(feats)}")
for i, feat in enumerate(feats[:5]):
    geom = feat.get("geometry", {})
    coords = geom.get("coordinates", [])
    gtype = geom.get("type")
    if coords:
        if gtype == "Polygon":
            ring = coords[0]
        elif gtype == "MultiPolygon":
            ring = coords[0][0]
        else:
            ring = []
        lons = [c[0] for c in ring]
        lats = [c[1] for c in ring]
        center = ((min(lons) + max(lons)) / 2,
                  (min(lats) + max(lats)) / 2)
        print(f"[{i}] type={gtype}, ring_points={len(ring)}, "
              f"center=({center[0]:.5f},{center[1]:.5f})")
        print(f"   bbox: [{min(lons):.5f},{max(lons):.5f}]/[{min(lats):.5f},{max(lats):.5f}]")

# 测试 points
from app.modules.spatial_ops.geometry import point_in_polygon
if feats:
    geom = feats[0].get("geometry", {})
    tests = [
        ("金田村委会", 116.0408, 24.8169),
        ("A Map 金田村委会", 116.0360, 24.8196),
        ("A Map 石窟河", 116.0684, 24.8352),
        ("A Map 长潭水库", 116.0697, 24.8406),
        ("A Map 牙子寨", 116.0690, 24.8521),
        ("百度 角坑村", 115.7965, 24.7465),
        ("百度 黄畲村", 115.8435, 24.8122),
        ("百度 梅畲村", 116.0471, 24.7250),
    ]
    print("\n=== point_in_polygon 测试 ===")
    for name, lon, lat in tests:
        inside = point_in_polygon((lon, lat), geom)
        print(f"  {'IN ' if inside else 'OUT'} {name}: ({lon:.4f},{lat:.4f})")