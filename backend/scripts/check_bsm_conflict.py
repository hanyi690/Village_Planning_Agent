"""Check if BSM duplicates cause wrong DLBM in rendered output."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from collections import defaultdict
from app.modules.data import DataCatalog
from app.modules.spatial_ops import build_spatial_index
from app.modules.spatial_ops.geometry import compute_parcel_relations
from app.modules.kg import PlanningKG

bundle = DataCatalog().load_village_bundle("金田村委会")
kg = PlanningKG(village_name="金田村委会")
kg.build_from_bundle(bundle=bundle, parcel_relations=compute_parcel_relations(
    bundle.polygons.landuse_current, roads=bundle.lines.roads_current))

# Find BSMs with multiple DLBMs
bsm_dlbms = defaultdict(set)
for p in bundle.polygons.landuse_current:
    bsm = getattr(p, "bsm", "") or ""
    dlbm = getattr(p, "dlbm", "") or ""
    if bsm:
        bsm_dlbms[bsm].add(dlbm)

conflicts = {bsm: dlbms for bsm, dlbms in bsm_dlbms.items() if len(dlbms) > 1}
print(f"BSMs with multiple DLBMs: {len(conflicts)}")
for bsm, dlbms in sorted(conflicts.items(), key=lambda x: -len(x[1]))[:10]:
    print(f"  {bsm}: {dlbms}")

# Check: 3100 DLBM parcels - what BSMs do they share?
print("\n=== 3100 parcels with shared BSMs ===")
for p in bundle.polygons.landuse_current:
    bsm = getattr(p, "bsm", "") or ""
    dlbm = getattr(p, "dlbm", "") or ""
    if dlbm == "3100" and bsm in conflicts:
        other_dlbms = bsm_dlbms[bsm] - {"3100"}
        if other_dlbms:
            area = getattr(p, "area_sqm", 0) or 0
            print(f"  BSM={bsm}  area={area:.0f} m²  3100 shares with {other_dlbms}")

# Check: for the largest BSM duplicates, what DLBMs?
print("\n=== Top 10 most duplicated BSMs ===")
bsm_counts = defaultdict(int)
for p in bundle.polygons.landuse_current:
    bsm = getattr(p, "bsm", "") or ""
    if bsm:
        bsm_counts[bsm] += 1
for bsm, cnt in sorted(bsm_counts.items(), key=lambda x: -x[1])[:10]:
    dlbms = bsm_dlbms[bsm]
    first_area = 0
    for p in bundle.polygons.landuse_current:
        if getattr(p, "bsm", "") == bsm:
            first_area = getattr(p, "area_sqm", 0) or 0
            break
    print(f"  BSM={bsm}  count={cnt}  DLBMs={dlbms}  first_area={first_area:.0f} m²")