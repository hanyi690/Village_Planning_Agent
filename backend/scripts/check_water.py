"""Check 3100 water parcels - are they really water or misclassified?"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.modules.data import DataCatalog
from shapely.geometry import shape
from shapely.ops import unary_union

b = DataCatalog().load_village_bundle("金田村委会")
parcels = b.polygons.landuse_current

# Total area by DLBM
from collections import defaultdict
area_by_dlbm = defaultdict(float)
for p in parcels:
    g = shape(p.geometry)
    if not g.is_valid:
        g = g.buffer(0)
    area_by_dlbm[p.dlbm] += g.area

total = sum(area_by_dlbm.values())
print("=== Area by DLBM (sorted by area) ===")
for code, area in sorted(area_by_dlbm.items(), key=lambda x: -x[1]):
    pct = area / total * 100
    print(f"  {code}: {area*111000*111000*0.92:.0f} m² ({pct:.1f}%)")

# Focus on 3100
print(f"\n=== 3100 (水域) details ===")
water_parcel = None
for p in parcels:
    if p.dlbm == "3100":
        g = shape(p.geometry)
        if not g.is_valid:
            g = g.buffer(0)
        area_m2 = g.area * 111000 * 111000 * 0.92
        if area_m2 > 10000:
            print(f"  BSM={p.bsm} area={area_m2:.0f} m² ({area_m2/10000:.1f} ha)")
            # Check raw properties
            raw = getattr(p, "_raw", {})
            print(f"    DLMC={raw.get('DLMC','')} BZ={raw.get('BZ','')} SDDLMC={raw.get('SDDLMC','')}")
            if area_m2 > 50000:
                water_parcel = p

# Check the big water parcel geometry
if water_parcel:
    g = shape(water_parcel.geometry)
    if not g.is_valid:
        g = g.buffer(0)
    print(f"\n=== Biggest water parcel ===")
    print(f"  BSM={water_parcel.bsm}")
    print(f"  bounds={g.bounds}")
    print(f"  geom_type={g.geom_type}")
    coords = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
    print(f"  parts: {len(coords)}")
    for i, part in enumerate(coords[:5]):
        print(f"    part[{i}]: area={part.area*111000*111000*0.92:.0f} m² bounds={part.bounds}")

# Check: is the big "water" actually the river?
# Look at road network - does it cross the water?
roads = b.lines.roads_current
print(f"\n=== Road crossings ===")
if water_parcel:
    wg = shape(water_parcel.geometry)
    if not wg.is_valid:
        wg = wg.buffer(0)
    crossing_count = 0
    for r in roads:
        rg = getattr(r, "geometry", None)
        if rg:
            try:
                rs = shape(rg)
                if rs.intersects(wg):
                    crossing_count += 1
            except:
                pass
    print(f"  Roads crossing big water parcel: {crossing_count}")

# Check raw GeoJSON to see original DLBM/DLMC
import json
with open("F:/project/Village_Planning_Agent/data/gis/jintian/current/landuse.geojson", encoding="utf-8") as f:
    data = json.load(f)
print(f"\n=== Raw GeoJSON 3100 samples ===")
count = 0
for feat in data["features"]:
    props = feat["properties"]
    if props.get("DLBM") == "3100":
        area_raw = props.get("DLMJ", 0) or props.get("SHAPE_Area", 0)
        print(f"  BSM={props.get('BSM','')} DLMC={props.get('DLMC','')} DLMJ={area_raw} BZ={props.get('BZ','')}")
        count += 1
        if count >= 10:
            break
