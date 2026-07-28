# kg/queries - Four-Namespace Query API

> **Purpose**: Query layer for `PlanningKG`. Provides SPARQL templates, LLM-friendly semantic queries, three-layer cognition summaries, and the v4.8 four-namespace API (analysis/parse/execute/shared).
> **Updated: 2026-07-28 (v4.8.1)**

---

## Key files

| File | Role |
| --- | --- |
| `__init__.py` | Exports all query functions + four namespace dicts (`analysis_queries`, `parse_queries`, `execute_queries`, `shared_queries`) |
| `sparql.py` | `QUERY_TEMPLATES` registry (30+ named SPARQL templates) + `query_kg()` parameterized execution + `TOOL_META` (tool metadata for LLM) + instance methods mixed into `PlanningKG` via `QueryMixin` |
| `semantic.py` | LLM-friendly semantic queries (`get_entity_context`, `get_parcel_semantic_context`, `get_village_semantic_summary`, `get_entity_semantics`, ...) + write-on-read annotation filling + `TOOL_META_SEMANTIC` |
| `cognition.py` | Three-layer cognition summary: `get_village_cognition()` (village overview + layer cards + constraint brief) + `get_layer_group_semantics()` |
| `contracts.py` | `DualPayload` (semantic + structured dual return) + `TokenBudget` (CJK-aware) + `TopKSampler` (stratified + spatial grid + outliers, no embeddings) |

## Four-namespace API (v4.8)

| Namespace | Consumer | Granularity | Writes KG | Status |
| --- | --- | --- | --- | --- |
| `analysis_queries` | analysis (report generation) | Coarse (layer-group / village / zone level) | No | Available |
| `parse_queries` | PARSE (intent compilation) | Fine (single parcel / adjacency / candidate set) | Yes (L3) | Available |
| `execute_queries` | EXECUTE (execution) | Medium (L4 read/write, constraint verify, conflict) | Yes (L4) | Partial |
| `shared_queries` | Cross-stage | - | No | Available |

Usage:
```python
from app.modules.kg.queries import analysis_queries, parse_queries

# Analysis: coarse semantic queries for report generation
result = analysis_queries["get_village_cognition"]["func"](kg, village_name="金田村委会")

# PARSE: fine-grained structured queries
parcels = parse_queries["get_parcel_neighbors"]["func"](kg, bsm="001")
```

## SPARQL templates and `query_kg`

```python
from app.modules.kg.queries import query_kg, QUERY_TEMPLATES

# Named template + parameters
result = query_kg(kg, "get_parcels_by_zone_type", zone_type_val="农业用地")
# -> [{"parcel": "...", "bsm": "001", "area": "0.5"}, ...]

# List all template names
print(list(QUERY_TEMPLATES.keys()))
# -> ['get_zone_restrictions', 'check_protected_parcels', 'get_parcels_by_dlbm', ...]
```

## Instance methods (mixed into PlanningKG)

```python
kg = PlanningKG("金田村委会")
kg.build_from_bundle(bundle=bundle, parcel_relations=relations)

# SPARQL instance methods
rows = kg.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o }")
adj = kg.get_adjacency_map()                       # BSM -> {neighbor BSMs}
nearby = kg.get_parcels_within_distance_of_entity(uri, 500)
connected = kg.get_connected_parcels(parcel_uri)
count = kg.get_parcel_count()                      # int
triples = kg.get_triple_count()                    # int
turtle = kg.to_turtle()
kg.serialize("kg.ttl", fmt="turtle")

# Constraint verification (uses injected ConstraintIndex)
violations = kg.check_constraint_violations("v1")
conflicts = kg.validate_intent(intent)

# L4 queries
changes = kg.get_plan_changes("v1")
effective_landuse = kg.get_effective_land_use("001")
effective_area = kg.get_effective_area_ha("001")
```

## Semantic queries (LLM-friendly)

```python
from app.modules.kg.queries import (
    get_entity_context, get_entity_relations,
    get_parcel_semantic_context, get_village_semantic_summary,
    get_entity_by_bsm, get_parcels_by_planning_zone,
    get_l4_derived_from_l1, get_village_constraint_coverage,
    get_entity_semantics,
)

# Returns human-readable description + structured data
ctx = get_entity_context(kg, entity_uri="pln:Parcel_P001")
# -> {"description": "P001: 水田(0101) 0.5ha 农田保护区", "attributes": {...}, ...}

# Semantic layer (v4.8): taxonomy / legal constraint / allowed operations
sem = get_entity_semantics(kg, entity_label="水田")
# -> {"taxonomic_parent": "农业用地", "legal_constraint": "forbid_construction", ...}
```

## Cognition queries (v4.8)

```python
from app.modules.kg.queries import get_village_cognition

payload = get_village_cognition(kg, "金田村委会")
# payload.semantic = {
#     "context_block": {"overview": "金田村委会，总面积..."},
#     "layer_cards": [...],
#     "constraint_block": {"adjacency_total": 1549, ...},
# }
# payload.structured = {
#     "layer_group_bsms": {...},
#     "bbox": (...),
#     "representative_bsms": [...],
# }
# payload.token_estimate = 1234  # CJK-aware
# payload.truncated = False
```

## `TOOL_META`

```python
from app.modules.kg.queries import TOOL_META, TOOL_META_SEMANTIC

# TOOL_META: metadata for wrapping query_kg as a LangGraph @tool
# Describes available template names + parameter schema
```

## Dependencies

- `rdflib` (SPARQL execution)
- `app.modules.kg.ontology` (PLN, EntityTypes, Relations)
- `app.modules.kg.memory` (SemanticMemoryStore for write-on-read annotations)
- **No** deps on `data`, `spatial_ops`, `agent`, `tools`

## How to extend

- **New SPARQL template**: add to `QUERY_TEMPLATES` in `sparql.py`, expose via `query_kg()`
- **New semantic query**: add function in `semantic.py`, export from `__init__.py`, optionally register in a namespace dict
- **New namespace entry**: add to the appropriate dict (`analysis_queries` / `parse_queries` / `execute_queries` / `shared_queries`) in `__init__.py`
- **New cognition summary field**: extend `get_village_cognition()` in `cognition.py`; respect `TokenBudget` truncation
