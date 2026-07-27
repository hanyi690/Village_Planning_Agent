"""Check DLBM distribution in KG vs color mapping."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.modules.data import DataCatalog
from app.modules.spatial_ops import build_spatial_index
from app.modules.spatial_ops.geometry import compute_parcel_relations
from app.modules.kg import PlanningKG

bundle = DataCatalog().load_village_bundle("金田村委会")
relations = compute_parcel_relations(bundle.polygons.landuse_current, roads=bundle.lines.roads_current)
kg = PlanningKG(village_name="金田村委会")
kg.build_from_bundle(bundle=bundle, parcel_relations=relations)

rows = kg.query("""PREFIX pln: <http://village-planning.org/ontology#>
SELECT ?dlbm (COUNT(?dlbm) AS ?cnt) WHERE {
  ?p a pln:Parcel ; pln:dlbm ?dlbm .
} GROUP BY ?dlbm ORDER BY DESC(?cnt)""")

print("=== KG DLBM distribution ===")
for r in rows:
    print(f"  {r['dlbm']:6s}: {r['cnt']:4s}")

DLBM_COLORS = {
    "1100": "#95d5b2", "1200": "#b7e4c7", "1340": "#52b788", "1350": "#2d6a4f",
    "1400": "#d8f3dc", "1510": "#d8f3dc", "2121": "#ffd166", "2122": "#ffa45c",
    "2123": "#f4845f", "2124": "#e85d75", "2125": "#a8dadc", "2126": "#adb5bd",
    "2200": "#6c757d", "2270": "#457b9d", "3100": "#4ea8de", "3200": "#ced4da",
}
DEFAULT = "#e9ecef"
unmapped = [r["dlbm"] for r in rows if r["dlbm"] not in DLBM_COLORS]
if unmapped:
    print(f"\n*** UNMAPPED DLBMs (will render as {DEFAULT}): {unmapped} ***")
else:
    print(f"\nAll {len(rows)} DLBM types have color mappings OK")

# Check area distribution (from bundle, not KG)
print("\n=== Area distribution from bundle ===")
from collections import defaultdict
area_by_dlbm = defaultdict(float)
for p in bundle.polygons.landuse_current:
    dlbm = getattr(p, "dlbm", "") or ""
    area = getattr(p, "area_sqm", 0) or 0
    area_by_dlbm[dlbm] += area
total = sum(area_by_dlbm.values())
for dlbm, area in sorted(area_by_dlbm.items(), key=lambda x: -x[1]):
    pct = area / total * 100
    color = DLBM_COLORS.get(dlbm, DEFAULT)
    bar = "#" * int(pct / 2)
    print(f"  {dlbm:6s} {area:12.0f} m²  {pct:5.1f}%  {color}  {bar}")