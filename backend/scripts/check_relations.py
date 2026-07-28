"""Directly check if target parcel appears in any relation."""
import sys; sys.path.insert(0, 'backend')
from app.modules.data import DataCatalog
from app.modules.spatial_ops.geometry import compute_parcel_relations

catalog = DataCatalog()
bundle = catalog.load_village_bundle('jintian')
relations = compute_parcel_relations(bundle.polygons.landuse_current, roads=bundle.lines.roads_current)

target_bsm = "441426211000049106"
lu = bundle.polygons.landuse_current

# Check target parcel
for i, p in enumerate(lu):
    if getattr(p, 'bsm', '') == target_bsm:
        geom = getattr(p, 'geometry', None) or p.get('geometry')
        if isinstance(geom, dict):
            bounds = 'GeoJSON dict'
        elif geom:
            bounds = geom.bounds
        else:
            bounds = '?'
        print(f"Target parcel index={i}, bsm={target_bsm}")
        print(f"  area_sqm={getattr(p, 'area_sqm', '?')}")
        print(f"  dlbm={getattr(p, 'dlbm', '?')}")
        print(f"  zone_type={getattr(p, 'zone_type', '?')}")
        print(f"  planning_zone={getattr(p, 'planning_zone', '?')}")
        print(f"  bounds={bounds}")
        break

# Check all touches for target
touches = list(relations.touches)
found = [(t.bsm_a, t.bsm_b, t.shared_boundary_length_m) for t in touches 
         if t.bsm_a == target_bsm or t.bsm_b == target_bsm]
print(f"\ntouches containing {target_bsm}: {len(found)}")
if found:
    for a, b, l in found[:10]:
        print(f"  {a} <-> {b}  ({l}m)")
else:
    print("  NONE - target is truly isolated in touch relations")

# Check nearby - they use parcel URIs
nearby = list(relations.nearby)
n0 = nearby[0]
print(f"\nnearby[0] type: {type(n0)}")
print(f"nearby[0]: {n0}")
if hasattr(n0, '__dict__'):
    print(f"nearby[0].__dict__: {n0.__dict__}")
    
# Build KG and search
from app.modules.kg.builder import PlanningKG
from app.modules.kg.ontology import PLN, EntityTypes, Relations
from rdflib import RDF

kg = PlanningKG("test")
kg.build_from_bundle(bundle=bundle, parcel_relations=relations, constraint_index=None)

target_uri = None
for s in kg.g.subjects(RDF.type, EntityTypes.Parcel):
    for p, o in kg.g.predicate_objects(s):
        if str(p).endswith("bsm") and str(o) == target_bsm:
            target_uri = s
            break
    if target_uri:
        break

print(f"\n=== KG check ===")
if target_uri:
    for pred_uri, pname in [(Relations.touches, "touches"), (Relations.nearby, "nearby"),
                             (Relations.connected_via_road, "connected")]:
        cnt = len(list(kg.g.objects(target_uri, pred_uri)))
        print(f"  {pname}: {cnt}")

    # Find what parcels exist around it in the KG by coordinates
    print(f"\n  5 nearest parcels by KG coordinate predicate:")
    # Get lon/lat from SemanticPredicates or directly
    from app.modules.kg.ontology import SemanticPredicates
    lon_pred = SemanticPredicates.lon if hasattr(SemanticPredicates, 'lon') else PLN.lon
    lat_pred = SemanticPredicates.lat if hasattr(SemanticPredicates, 'lat') else PLN.lat
    bsm_pred = SemanticPredicates.bsm if hasattr(SemanticPredicates, 'bsm') else PLN.bsm
    label_pred = SemanticPredicates.has_semantic_label if hasattr(SemanticPredicates, 'has_semantic_label') else PLN.has_semantic_label

    target_lon = float(list(kg.g.objects(target_uri, lon_pred))[0])
    target_lat = float(list(kg.g.objects(target_uri, lat_pred))[0])
    print(f"  target coords: {target_lon}, {target_lat}")
    
    near = []
    for s in kg.g.subjects(RDF.type, EntityTypes.Parcel):
        if s == target_uri:
            continue
        try:
            sl = list(kg.g.objects(s, lon_pred))
            sla = list(kg.g.objects(s, lat_pred))
            if sl and sla:
                slon = float(sl[0])
                slat = float(sla[0])
                sbsm = str(list(kg.g.objects(s, bsm_pred))[0])
                slabel = str(list(kg.g.objects(s, label_pred))[0])
                dist = ((slon - target_lon)**2 + (slat - target_lat)**2)**0.5 * 111000
                # Check if they touch by looking for the target_uri in this parcel's relations
                in_touch = len(list(kg.g.objects(s, Relations.touches))) > 0
                is_near = len(list(kg.g.objects(s, Relations.nearby))) > 0
                near.append((dist, sbsm, slabel, in_touch, is_near))
        except:
            pass

    near.sort(key=lambda x: x[0])
    print(f"  {'BSM':30s} {'Label':10s} {'Dist(m)':8s} {'Touch':6s}")
    for dist, bsm, label, touch, nbr in near[:10]:
        print(f"  {bsm:30s} {label:10s} {dist:7.0f}  {str(touch):6s}")
else:
    print("  Target not found in KG")
