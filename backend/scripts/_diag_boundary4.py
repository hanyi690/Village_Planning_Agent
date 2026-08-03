"""诊断 village_boundary_geometry"""
import sys, os
os.environ["LOG_LEVEL"] = "CRITICAL"
sys.path.insert(0, ".")
from app.modules.data import DataCatalog
from app.modules.spatial_ops.geometry import village_boundary_geometry
catalog = DataCatalog()
catalog.set_admin_meta("金田", province="广东省", city="梅州市",
                       county="平远县", township="泗水镇",
                       adcode_12="441426110000")
bundle = catalog.load_village_bundle("金田")
print("admin_areas count:", len(bundle.polygons.get("admin_areas") or []))
print("planning_scope count:", len(bundle.polygons.get("planning_scope") or []))
b = village_boundary_geometry(bundle)
print("boundary is None:", b is None)
if b:
    coords = b.get("coordinates", [])
    print("type:", b.get("type"), "rings:", len(coords))
    if coords:
        ring = coords[0]
        lons = [c[0] for c in ring]
        lats = [c[1] for c in ring]
        print(f"ring_pts={len(ring)} bbox=[{min(lons):.5f},{max(lons):.5f}]/[{min(lats):.5f},{max(lats):.5f}]")