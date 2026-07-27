"""Verify BSM uniqueness after ingest fix."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from collections import Counter
from app.modules.data import DataCatalog

bundle = DataCatalog().load_village_bundle("金田村委会")
parcels = bundle.polygons.landuse_current
bsms = [getattr(p, "bsm", "") for p in parcels]
c = Counter(bsms)
multi = {k: v for k, v in c.items() if v > 1}

print(f"Parcels: {len(parcels)}")
print(f"Unique BSMs: {len(c)}")
print(f"Duplicated BSMs: {len(multi)}")

if multi:
    for k, v in sorted(multi.items(), key=lambda x: -x[1])[:5]:
        dlbms = Counter(getattr(p, "dlbm", "") for p in parcels if getattr(p, "bsm", "") == k)
        print(f"  {k}: {v} features, DLBMs={dict(dlbms)}")
else:
    print("All BSMs are unique!")

print()
print("Sample BSMs (first 10):")
for p in parcels[:10]:
    print(f"  {getattr(p, 'bsm', '')}  DLBM={getattr(p, 'dlbm', '')}")

# Also check that original BSM values are preserved for the first occurrence
print()
print("BSM dedup check (original BSM ...49933):")
orig = "441426211000049933"
for p in parcels:
    b = getattr(p, "bsm", "")
    if b.startswith(orig):
        print(f"  {b}  DLBM={getattr(p, 'dlbm', '')}  area={getattr(p, 'area_sqm', 0):.0f}")