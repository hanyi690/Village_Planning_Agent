# kg/builder - Four-Layer KG Construction (v5.0 Composition Pattern)

> **Purpose**: Builds the RDF knowledge graph from `VillageBundle` morphology groups.
> Orchestrates L1 (static entities) -> L2 (spatial relations) -> L3 (intent virtual entities) -> L4 (planned state).
> **Updated: 2026-07-30 (v5.0)** - KGBuilder composition replaces mixins

---

## Key files

| File | Role |
| --- | --- |
| `base.py` | `PlanningKG` data container (RDF graph + memory) + query methods. No build logic. |
| `builder.py` | `KGBuilder` composition orchestrator. Replaces `build_from_bundle` from mixins era. |
| `registry.py` | `@kg_builder` decorator, `_KG_BUILDERS` dict, `get_builder()`, `BuilderSpec`, `BuildContext`, `_get_bundle_features()` |
| `enrichment.py` | Derivation helpers (from ontology.py v4 era) + `add_gis_layer_groups` + `add_semantic_enrichment` |
| `geo_helpers.py` | WKT centroid/bbox helpers: `add_centroid`, `add_bbox`, `add_geo_feature_type`, `parse_wkt_point`, `parse_wkt_bbox`, `wkt_centroid`, `wkt_bbox_polygon` |
| `layer1_core.py` | Layer 1 core builders (parcels, roads, water, facilities, annotations, control lines, planning elements, residential clusters, terrain) |
| `layer1_extended.py` | Layer 1 extended geometry groups (protection polygons, terrain entities, boundaries, natural resource zones) |
| `layer2.py` | Layer 2: spatial relations (touches, nearby, connected, cross-type). Relation attributes → SemanticMemoryStore. |
| `layer3.py` | Layer 3: intent virtual entities (`build_intent_layer`, `clear_intent_layer`) |
| `layer4.py` | Layer 4: planned state (`apply_planned_state`, `ingest_planned_state_from_geojson`) |
| `mixins.py` | **DELETED** in v5.0. Use `KGBuilder` composition instead. |

## Four-layer architecture

| Layer | Content | Lifecycle | Writer | Consumer |
| --- | --- | --- | --- | --- |
| L1 | Static entities + encoding props + 3-dim predicates + GisLayerSet + semantic layer | Persistent (rebuilt on data update) | `KGBuilder.build()` | SPARQL queries, PARSE, EXECUTE |
| L2 | Spatial relations (touches/nearby/connected + cross-type located_in/intersects/contains) | Persistent | `KGBuilder.build()` | SPARQL, EXECUTE |
| L3 | Intent virtual entities (ZoneTarget/FacilityTarget/RoadTarget/AxisTarget) | Session-ephemeral | `KGBuilder.build_intent_layer()` | EXECUTE spatial reasoning |
| L4 | Planned state (PlannedParcel/PlannedZone/PlannedFacility/PlannedRoad/PlannedAxis) | Session-persistent | `KGBuilder.apply_planned_state()` | Export, compare, validate |

## KGBuilder composition

`KGBuilder` is the composition orchestrator. `PlanningKG` holds only data (RDF graph + SemanticMemoryStore).

```python
from app.modules.kg.builder import KGBuilder

kg = KGBuilder.build(
    "jintian", bundle,
    parcel_relations=parcel_relations,
    constraint_index=constraint_index,
    intent=intent,            # optional
    planned_state=planned,    # optional
)
```

The `kg_main` fixture in tests:
```python
from app.modules.kg.builder import KGBuilder
kg = KGBuilder.build("jintian", bundle, parcel_relations=relations, constraint_index=constraint_index)
```

## `@kg_builder` decorator and registry

```python
from .registry import kg_builder, BuildContext

@kg_builder("water", entity_type="WaterBody", layer=1, order=10)
def _add_water_bodies(kg, features, *, gtype_ref, entry, ctx: BuildContext) -> dict:
    # kg       = PlanningKG instance
    # features = list from bundle.<bundle_target.group>.<bundle_target.key>
    # gtype_ref = layer_type string ("water")
    # entry    = GisLayerTypeEntry from YAML
    # ctx      = BuildContext(village_name, bbox, constraint_index, provenance)
    ...
    return {"water": count}
```

`KGBuilder._build_entities()` iterates `_ordered_builders()` (sorted by `layer` then `order`), fetches features via `_get_bundle_features(bundle, entry)`, and calls each builder.

Current `@kg_builder` registrations (in layer1_core.py, layer1_extended.py):
- `@kg_builder("landuse_current", entity_type="Parcel")` - 660 parcels
- `@kg_builder("water", entity_type="WaterBody")`
- `@kg_builder("current_road", entity_type="Road")`
- `@kg_builder("current_annotation", entity_type="Facility")` - annotation points
- `@kg_builder("farmland_protection", entity_type="Zone")`
- `@kg_builder("ecological_redline", entity_type="Zone")`
- `@kg_builder("historical_protection", entity_type="Zone")`
- `@kg_builder("admin_area", entity_type="AdministrativeVillage")`
- etc.

## `BuildContext`

```python
@dataclass
class BuildContext:
    village_name: str
    bbox: Optional[tuple[float, float, float, float]] = None
    constraint_index: Any = None        # ConstraintIndex from spatial_ops.bridge
    provenance: dict[str, Any] = field(default_factory=dict)
```

## `BuilderSpec`

```python
@dataclass
class BuilderSpec:
    gis_type_ref: str      # layer_type key (e.g. "landuse_current")
    fn: Callable           # builder function
    entity_type: str       # RDF type (e.g. "Parcel")
    layer: int = 1         # KG layer (1-4)
    order: int = 50        # execution order within layer
```

## Public API

```python
from app.modules.kg.builder import (
    PlanningKG, KGInputParcels, KGBuilder,
    BuildContext, kg_builder, get_builder, BuilderSpec,
)
```

## GeoSPARQL alignment (v5.0)

Entities typed as `geo:Feature`. Centroid/bbox stored as WKT:

```python
# Old (v4.x): pln:lon/lat + pln:bbox_minx/maxy/etc.
# New (v5.0): geo:hasCentroid + geo:asWKT "POINT(...)"
#              geo:hasBoundingBox + geo:asWKT "POLYGON((minx miny, maxx miny, ...))"
```

See `geo_helpers.py` for WKT format/parse functions.

## Relation attributes → SemanticMemoryStore (v5.0)

Relation quantitative attributes (shared_boundary_length, centroid_distance, road_segment_length, via_road, overlap_pct) are stored in `SemanticMemoryStore` instead of RDF triples.

```python
# RDF: only pure relations
kg.g.add((a, Relations.sfTouches, b))

# SemanticMemoryStore: quantitative details
kg.memory.add_relation_annotation(RelationAnnotation(
    subject_uri=str(a), predicate=str(Relations.sfTouches),
    object_uri=str(b), description="",
    derived_from="spatial_ops_computed",
    quantitative_detail={"shared_boundary_m": t.shared_boundary_length_m},
))
```

## Dependencies

- `rdflib` (Graph, Literal, URIRef, RDF, XSD)
- `app.modules.schema.types` (VillageBundle, feature classes)
- `app.modules.kg.ontology` (PLN, GEO, EntityTypes, Relations, EntityIdPolicy)
- `app.modules.kg.memory` (SemanticMemoryStore)
- `app.modules.kg.dlq` (DlqEntry, DlqReport)
- **No** deps on `data`, `spatial_ops`, `agent`, `tools` (KG receives spatial_ops outputs as injected params)

## How to extend

- **New KG entity for existing layer**: add `@kg_builder("layer_type", entity_type="...", layer=1, order=N)` function in `layer1_core.py` or `layer1_extended.py`
- **New spatial relation**: add to `layer2.py:add_parcel_relations` or `add_cross_type_relations`
- **New L3/L4 function**: add to `layer3.py` / `layer4.py`, call via `KGBuilder.build_intent_layer()` / `KGBuilder.apply_planned_state()`
- **New semantic predicate**: add to `ontology.py:SemanticPredicates`, write in `enrichment.py:add_semantic_enrichment()`
- See `docs/gis/HOW_TO_ADD_LAYER.md` Pattern 4 for the full `@kg_builder` workflow
