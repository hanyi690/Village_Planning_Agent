"""Check KG queries work properly."""
from collections import defaultdict
import rdflib
from app.modules.data.catalog import DataCatalog
from app.modules.spatial_ops.bridge import build_constraint_index
from app.modules.kg.builder.base import PlanningKG
from app.modules.spatial_ops.geometry import compute_parcel_relations

catalog = DataCatalog()
bundle = catalog.load_village_bundle("金田村委会")
parcels = bundle.polygons.landuse_current
roads = bundle.lines.roads_current
relations = compute_parcel_relations(parcels, roads=roads)

kg = PlanningKG("金田村委会")
kg.build_from_bundle(
    bundle=bundle,
    parcel_relations=relations,
    constraint_index=build_constraint_index(bundle),
)

types = defaultdict(set)
for s, o in kg.g.subject_objects(rdflib.RDF.type):
    t = str(o).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    types[t].add(s)
print("=== Entity types in KG ===")
for t in sorted(types):
    print("  {}: {}".format(t, len(types[t])))
print("Total triples: {}".format(len(kg.g)))

adj = kg.get_adjacency_map()
total_adj = sum(len(v) for v in adj.values())
print("\nAdjacency map: {} parcels, {} edges".format(len(adj), total_adj))
for i, (k, v) in enumerate(sorted(adj.items())):
    if i >= 3:
        break
    print("  {}: {}".format(k, list(v)[:3]))

violations = kg.check_constraint_violations("v1")
print("\nConstraint violations: {}".format(len(violations)))
if violations:
    v = violations[0]
    print("  Sample: BSM={}, type={}".format(v.bsm, v.constraint_type))

r = kg.query("SELECT ?p ?bsm WHERE { ?p a pln:Parcel ; pln:bsm ?bsm } LIMIT 3")
print("\nSPARQL sample parcels:")
for row in r:
    print("  {} -> BSM={}".format(row.p, row.bsm))

from app.modules.kg.queries import query_parcels_by_bsm
results = list(query_parcels_by_bsm(kg.g, ["3020650"]))
print("Parcels with BSM=3020650: {}".format(len(results)))
