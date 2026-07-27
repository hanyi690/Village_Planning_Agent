"""Diagnose invalid parcel geometries."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.modules.data import DataCatalog
from shapely.geometry import shape
from shapely.validation import explain_validity

b = DataCatalog().load_village_bundle("金田村委会")
parcels = b.polygons.landuse_current

print(f"Total parcels: {len(parcels)}")
invalid_count = 0
for p in parcels:
    geom = getattr(p, "geometry", None)
    if not geom:
        continue
    try:
        s = shape(geom)
        if not s.is_valid:
            invalid_count += 1
            reason = explain_validity(s)
            # Get coordinate count to see complexity
            coords = geom.get("coordinates", [])
            n_coords = 0
            if geom.get("type") == "MultiPolygon":
                for poly in coords:
                    for ring in poly:
                        n_coords += len(ring)
            print(f"\n  BSM={p.bsm} DLBM={p.dlbm}")
            print(f"  Reason: {reason}")
            print(f"  Type: {geom.get('type')}, coords count: {n_coords}")
            # Show first few coords
            if geom.get("type") == "MultiPolygon" and coords:
                ring = coords[0][0] if coords[0] else []
                print(f"  First 3 coords: {ring[:3]}")
                print(f"  Last 3 coords: {ring[-3:]}")
    except Exception as e:
        invalid_count += 1
        print(f"  BSM={p.bsm} parse error: {e}")

print(f"\nTotal invalid: {invalid_count} / {len(parcels)}")
