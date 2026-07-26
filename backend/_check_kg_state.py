"""Quick diagnostic: what's in the KG after Batch 1."""
import rdflib
from app.modules.data.catalog import DataCatalog
from app.modules.spatial_ops.bridge import build_constraint_index
from app.modules.kg.builder.base import PlanningKG
from app.modules.kg.ontology import PLN

catalog = DataCatalog()
bundle = catalog.load_village_bundle("金田村委会")

kg = PlanningKG("金田村委会")
kg.build_from_bundle(bundle, constraint_index=build_constraint_index(bundle))

# What entity types exist?
types = {}
for s, o in kg.g.subject_objects(rdflib.RDF.type):
    t = str(o).rsplit("/", 1)[-1]
    types.setdefault(t, set()).add(s)

print("=== Entity types in KG ===")
for t in sorted(types):
    print(f"  {t}: {len(types[t])}")
print(f"Total triples: {len(kg.g)}")

# Test get_adjacency_map
adj = kg.get_adjacency_map()
total_adj = sum(len(v) for v in adj.values())
print(f"\nAdjacency map: {len(adj)} parcels, {total_adj} edges")

# Test check_constraint_violations
violations = kg.check_constraint_violations("v1")
print(f"Constraint violations: {len(violations)}")

# Test SPARQL
results = kg.query("SELECT ?p WHERE { ?p a pln:Parcel }")
print(f"SPARQL Parcel count: {len(results)}")

# Check no ThreeZone/ThreeLine
tz = list(kg.g.triples((None, rdflib.RDF.type, PLN.ThreeZone)))
tl = list(kg.g.triples((None, rdflib.RDF.type, PLN.ThreeLine)))
print(f"\nThreeZone in KG: {len(tz)}, ThreeLine in KG: {len(tl)}")
