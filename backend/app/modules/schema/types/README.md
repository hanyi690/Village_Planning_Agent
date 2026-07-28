# schema/types - Pydantic v2 Typed Feature Models

> **Purpose**: Defines the typed dataclass hierarchy for all spatial/non-spatial features in the system. The type layer that Data ingests into, KG builds from, and Agent reasons over.
> **Updated: 2026-07-28 (v4.8.1)**

---

## Key files

| File | Role |
| --- | --- |
| `base.py` | L0 abstract bases: `SpatialFeature`, `PointFeature`, `LineFeature`, `PolygonFeature`, `RasterDataset` |
| `spatial_types.py` | L2 vector semantic subclasses (Group A-F, ~33 concrete classes: parcels, roads, facilities, control zones, natural resources, annotations) |
| `raster_types.py` | Raster subclasses: `DEMInput`, `DOMInput`, `SlopeRaster`, `AspectRaster`, `SuitabilityRaster`, `TerrainAnalysisResult` |
| `table_types.py` | `TableDataset` + 7 subclasses (PopulationTable, ControlRuleTable, PlanningIndicatorTable, etc.) |
| `document_types.py` | `Document` + `PlanningText` + `L3Report` |
| `canonical.py` | `VillageBundle` (morphology-first container) + 6 Group dataclasses + `ProjectDataView` + `VillageMetadata` |
| `layer_registry.py` | `GIS_LAYER_REGISTRY` + `GisLayerTypeEntry` + `build_registry_from_yaml()` |
| `gis_layer_registry.yaml` | Single source of truth for layer metadata (40+ entries) |

## Type hierarchy (DU discriminator)

```
L0  SpatialFeature                  (geometry + bsm + ysdm + layer_type + _raw)
 ├── L1  PointFeature / LineFeature / PolygonFeature   (geometry_type validated at construction)
 └── L2  semantic subclasses (CurrentLandUseParcel, CurrentRoad, FarmlandProtection, ...)

L0  RasterDataset                   (path + crs + bounds + bands)
 └── L1  DEMInput / DOMInput / SlopeRaster / ...

L0  TableDataset                    (rows + columns + schema)
 └── L1  PopulationTable / ControlRuleTable / ...

L0  Document                        (text + doc_type + source)
 └── L1  PlanningText / L3Report
```

The DU (discriminated union) discriminator is `layer_type` (embedded on each feature). `_assign_to_bundle` in `data/ingest.py` uses `isinstance` chains, not string matching, to route features into `VillageBundle` morphology groups.

## Public API

```python
from app.modules.schema.types import (
    # Bases
    SpatialFeature, PointFeature, LineFeature, PolygonFeature, RasterDataset,
    TableDataset, Document,
    # Semantic subclasses
    CurrentLandUseParcel, PlannedLandUseParcel, CurrentRoad, PlannedRoad,
    FarmlandProtection, EcologicalRedline, CurrentFacility, PlannedFacility,
    # ... 33 total
    # Containers
    VillageBundle, ProjectDataView, VillageMetadata,
    PointLayerGroup, LineLayerGroup, PolygonLayerGroup,
    RasterLayerGroup, TableLayerGroup, DocumentGroup,
    # Registry
    GIS_LAYER_REGISTRY, GisLayerTypeEntry, get_gis_layer_entry, get_all_gis_layer_types,
)
```

## Dependencies

- `pydantic` (for `GisLayerTypeEntry` validation)
- `yaml` (for loading `gis_layer_registry.yaml`)
- Standard library only (`dataclasses`, `typing`, `pathlib`)
- **Zero** deps on `data`, `kg`, `agent`, `tools` (Schema is the bottom of the four-layer architecture)

## How to extend

See [`docs/gis/HOW_TO_ADD_LAYER.md`](../../../../../docs/gis/HOW_TO_ADD_LAYER.md) for the full guide. Short version:

1. **New layer type**: add YAML entry to `gis_layer_registry.yaml`
2. **New Python class**: define subclass in `spatial_types.py` / `raster_types.py` / `table_types.py`, export from `__init__.py`, add mapping in `data/ingest.py::_infer_model_class()`
3. **New bundle field**: add field to the appropriate Group dataclass in `canonical.py` (e.g. `PolygonLayerGroup.my_new_layer: List[MyNewLayer]`)
