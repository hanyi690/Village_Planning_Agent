# kg/builder - Four-Layer KG Construction

> **Purpose**: Builds the RDF knowledge graph from `VillageBundle` morphology groups. Orchestrates L1 (static entities) -> L2 (spatial relations) -> L3 (intent virtual entities) -> L4 (planned state).
> **Updated: 2026-07-28 (v4.8.1)**

---

## Key files

| File | Role |
| --- | --- |
| `base.py` | `PlanningKG` skeleton class + `build_from_bundle()` orchestrator + `clone_static_layer()` + `KGInputParcels` |
| `registry.py` | `@kg_builder` decorator, `_KG_BUILDERS` dict, `get_builder()`, `BuildContext`, `_get_bundle_features()` |
| `layer1.py` | Layer 1 builders: static entities (parcels, roads, facilities, water, control zones, protection polygons, buildings, terrain, boundaries, natural resources) + three-dimension predicates + `GisLayerSet` virtual entities + semantic enrichment |
| `layer2.py` | Layer 2: spatial relations (delegates to layer1 methods) |
| `layer3.py` | Layer 3: intent virtual entities (`build_intent_layer`, `_add_structured_intent`, `clear_intent_layer`) - structured anchoring attributes, no raw geometry |
| `layer4.py` | Layer 4: planned state (`_apply_planned_state`, `get_effective_land_use`, `get_plan_changes`, `check_constraint_violations`, `compare_versions`) |
| `mixins.py` | `Layer1Mixin`, `Layer2Mixin`, `Layer3Mixin`, `Layer4Mixin`, `QueryMixin` - bind module-level functions to `PlanningKG` via inheritance |

## Four-layer architecture

| Layer | Content | Lifecycle | Writer | Consumer |
| --- | --- | --- | --- | --- |
| L1 | Static entities + encoding props + 3-dim predicates + GisLayerSet + semantic layer | Persistent (rebuilt on data update) | `build_from_bundle()` | SPARQL queries, PARSE, EXECUTE |
| L2 | Spatial relations (touches/nearby/connected + cross-type located_in/intersects/contains) | Persistent | `spatial_ops` pre-computed | SPARQL, EXECUTE |
| L3 | Intent virtual entities (ZoneTarget/FacilityTarget/RoadTarget/AxisTarget) | Session-ephemeral | PARSE -> `build_intent_layer()` | EXECUTE spatial reasoning |
| L4 | Planned state (PlannedParcel/PlannedZone/PlannedFacility/PlannedRoad/PlannedAxis) | Session-persistent | EXECUTE -> `_apply_planned_state()` | Export, compare, validate |

## `@kg_builder` decorator and registry

```python
from .registry import kg_builder, BuildContext

@kg_builder("water", entity_type="WaterBody")
def _add_water_bodies(self, features, *, gtype_ref, entry, ctx: BuildContext) -> dict:
    # self     = PlanningKG instance
    # features = list from bundle.<bundle_target.group>.<bundle_target.key>
    # gtype_ref = layer_type string ("water")
    # entry    = GisLayerTypeEntry from YAML
    # ctx      = BuildContext(village_name, bbox, constraint_index, provenance)
    ...
    return {"water": count}  # report dict (logged at debug)
```

`build_from_bundle()` iterates `_KG_BUILDERS` (see `base.py:126`), fetches features via `_get_bundle_features(bundle, entry)`, and calls each builder. This is the registry-driven extension point - new layers with custom KG behavior register here.

Current `@kg_builder` registrations:
- `@kg_builder("water", entity_type="WaterBody")` - water bodies with overlap dedup
- `@kg_builder("current_road", entity_type="Road")` - road entities
- `@kg_builder("dem", entity_type="RasterDataset")` - DEM raster as single RasterDataset entity
- `@kg_builder("current_building", entity_type="Building")` - building entities

## `build_from_bundle` entry point

```python
kg = PlanningKG("金田村委会")
kg.build_from_bundle(
    bundle=bundle,                 # VillageBundle - typed morphology view
    parcel_relations=relations,    # ParcelRelations (L1/L2/L3 spatial relations)
    intent=intent,                 # SpatialPlanningIntent -> L3 (optional)
    planned_state=planned,         # PlannedState -> L4 (optional)
    constraint_index=ci,           # ConstraintIndex from spatial_ops.bridge (optional)
    water_overlap=wo,              # water dedup map (optional)
    cross_type_relations=ctr,      # located_in/intersects/contains (optional, auto-computed if None)
)
```

The builder reads directly from `bundle.polygons.landuse_current`, `bundle.lines.roads_current`, etc. - no `ContextBlock` dependency. ContextBlock is only for PARSE prompt context.

## `BuildContext`

```python
@dataclass
class BuildContext:
    village_name: str
    bbox: Optional[tuple[float, float, float, float]] = None
    constraint_index: Any = None        # ConstraintIndex from spatial_ops.bridge
    provenance: dict[str, Any] = field(default_factory=dict)  # e.g. {"water_overlap": {...}}
```

Passed to every `@kg_builder` function. Carries cross-cutting context without polluting the KG class.

## Public API

```python
from app.modules.kg.builder import (
    PlanningKG, KGInputParcels,
    Layer1Mixin, Layer2Mixin, Layer3Mixin, Layer4Mixin, QueryMixin,
    BuildContext, kg_builder, get_builder,
)
```

## Dependencies

- `rdflib` (Graph, Literal, URIRef, RDF, XSD)
- `app.modules.schema.types` (VillageBundle, feature classes)
- `app.modules.kg.ontology` (PLN, GEO, EntityTypes, Relations, EntityIdPolicy)
- `app.modules.kg.memory` (SemanticMemoryStore)
- `app.modules.kg.dlq` (DlqEntry, DlqReport)
- **No** deps on `data`, `spatial_ops`, `agent`, `tools` (KG receives spatial_ops outputs as injected params)

## How to extend

- **New KG entity for existing layer**: add `@kg_builder("layer_type", entity_type="...")` function in `layer1.py`
- **New L4 query method**: add to `layer4.py`, expose via `Layer4Mixin`
- **New semantic predicate**: add to `ontology.py:SemanticPredicates`, write in `_add_semantic_enrichment()`
- See [`docs/gis/HOW_TO_ADD_LAYER.md`](../../../../../docs/gis/HOW_TO_ADD_LAYER.md) Pattern 4 for the full `@kg_builder` workflow
