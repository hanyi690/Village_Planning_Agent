# kg/queries - Four-Namespace Query API (v5.0)

> **Purpose**: Query layer for `PlanningKG`. Provides SPARQL templates, LLM-friendly semantic queries, three-layer cognition summaries, and the v4.8 four-namespace API (analysis/parse/execute/shared).
> **Updated: 2026-07-30 (v5.0)** - Query functions now module-level (no mixin inheritance)

---

## Key files

| File | Role |
| --- | --- |
| `__init__.py` | Exports all query functions + four namespace dicts (`analysis_queries`, `parse_queries`, `execute_queries`, `shared_queries`) |
| `sparql.py` | `QUERY_TEMPLATES` registry (30+ named SPARQL templates) + `query_kg()` parameterized execution + `TOOL_META` (tool metadata for LLM) + standalone query functions |
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
from app.infrastructure.kg.queries import analysis_queries, parse_queries

# Analysis: coarse semantic queries for report generation
result = analysis_queries["get_village_cognition"]["func"](kg, village_name="金田村委会")

# PARSE: fine-grained structured queries
parcels = parse_queries["get_parcel_neighbors"]["func"](kg, bsm="001")
```

## SPARQL templates and `query_kg`

```python
from app.infrastructure.kg.queries import query_kg, QUERY_TEMPLATES

# Named template + parameters
result = query_kg(kg, "get_parcels_by_zone_type", zone_type_val="农业用地")
# -> [{"parcel": "...", "bsm": "001", "area": "0.5"}, ...]

# List all template names
print(list(QUERY_TEMPLATES.keys()))
# -> ['get_zone_restrictions', 'check_protected_parcels', 'get_parcels_by_dlbm', ...]
```

## Query functions (v5.0 - all module-level, take `kg` as first arg)

```python
from app.infrastructure.kg.queries import (
    query, get_adjacency_map,
    get_parcel_count, get_triple_count, serialize, to_turtle, from_turtle,
    get_parcels_within_distance_of_entity, get_adjacent_parcels_with_length,
    get_connected_parcels, get_parcels_by_bsm_list, validate_intent,
    get_effective_land_use, get_effective_area_ha,
    get_plan_changes, get_planned_parcels_in_zone,
    check_constraint_violations, compare_versions,
)

# PlanningKG instance methods (still on base.py)
kg = PlanningKG("jintian")
kg = KGBuilder.build("jintian", bundle, parcel_relations=relations, constraint_index=constraint_index)

# Query methods on PlanningKG
rows = kg.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o }")
adj = kg.get_adjacency_map()                       # BSM -> {neighbor BSMs}
count = kg.get_parcel_count()                      # int
triples = kg.get_triple_count()                    # int
turtle = kg.to_turtle()
kg.serialize("kg.ttl", fmt="turtle")

# Module-level query functions (import from queries.sparql)
nearby = get_parcels_within_distance_of_entity(kg, uri, 500)
connected = get_connected_parcels(kg, parcel_uri)
adj_with_len = get_adjacent_parcels_with_length(kg, bsm)

# L4 query functions (import from queries.sparql)
violations = check_constraint_violations(kg, "v1")
diff = compare_versions(kg, "v1", "v2")
changes = get_plan_changes(kg, "v1")
effective_lu = get_effective_land_use(kg, "001", "v1")
effective_area = get_effective_area_ha(kg, "001", "v1")
zone_parcels = get_planned_parcels_in_zone(kg, "村庄建设区", "v1")
```

## Semantic queries (LLM-friendly)

```python
from app.infrastructure.kg.queries import (
    get_entity_context, get_entity_relations,
    get_parcel_semantic_context, get_village_semantic_summary,
    get_entity_by_bsm, get_parcels_by_planning_zone,
    get_l4_derived_from_l1, get_village_constraint_coverage,
    get_entity_semantics,
)

# Returns human-readable description + structured data
ctx = get_entity_context(kg, entity_uri="pln:parcel_001")
# -> {"description": "P001: 水田(0101) 0.5ha 农田保护区", "attributes": {...}, ...}

# Semantic layer: taxonomy / legal constraint / allowed operations
sem = get_entity_semantics(kg, entity_label="水田")
# -> {"taxonomic_parent": "农业用地", "legal_constraint": "forbid_construction", ...}
```

## Cognition queries (v4.8)

```python
from app.infrastructure.kg.queries import get_village_cognition

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
from app.infrastructure.kg.queries import TOOL_META, TOOL_META_SEMANTIC

# TOOL_META: metadata for wrapping query_kg as a LangGraph @tool
# Describes available template names + parameter schema
```

## L3/L4 builder functions (in builder/layer3.py, builder/layer4.py)

```python
# Import from builder subpackage
from app.infrastructure.kg.builder.layer3 import build_intent_layer, clear_intent_layer
from app.infrastructure.kg.builder.layer4 import apply_planned_state

# Build L3 intent
build_intent_layer(kg, intent)

# Build L4 planned state
apply_planned_state(kg, planned_state)

# Clear L3 (end of session)
clear_intent_layer(kg)
```

## Dependencies

- `rdflib` (SPARQL execution)
- `app.infrastructure.kg.ontology` (PLN, EntityTypes, Relations)
- `app.infrastructure.kg.memory` (SemanticMemoryStore for write-on-read annotations)
- **No** deps on `data`, `app.spatial`, `agent`, `tools`

## How to extend

- **New SPARQL template**: add to `QUERY_TEMPLATES` in `sparql.py`, expose via `query_kg()`
- **New semantic query**: add function in `semantic.py`, export from `__init__.py`, optionally register in a namespace dict
- **New namespace entry**: add to the appropriate dict (`analysis_queries` / `parse_queries` / `execute_queries` / `shared_queries`) in `__init__.py`
- **New cognition summary field**: extend `get_village_cognition()` in `cognition.py`; respect `TokenBudget` truncation
