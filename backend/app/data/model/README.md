# schema/types - Pydantic v2 Typed Feature Models

> **Purpose**: Defines the typed dataclass hierarchy for all spatial/non-spatial features in the system. The type layer that Data ingests into, KG builds from, and Agent reasons over.
> **Updated: 2026-07-28 (v4.8.1)**

---

## Key files

| File | Role |
| --- | --- |
| `base.py` | L0 abstract bases: `SpatialFeature`, `PointFeature`, `LineFeature`, `PolygonFeature`, `RasterDataset` (all Pydantic v2 `BaseModel` with `field_validator` geometry checks) |
| `spatial_types.py` | L2 vector semantic subclasses (Group A-F, ~33 concrete classes: parcels, roads, facilities, control zones, natural resources, annotations) + `GisFeature` Discriminated Union |
| `raster_types.py` | Raster subclasses: `DEMInput`, `DOMInput`, `SlopeRaster`, `AspectRaster`, `SuitabilityRaster`, `TerrainAnalysisResult` |
| `table_types.py` | `TableDataset` + 7 subclasses (PopulationTable, ControlRuleTable, PlanningIndicatorTable, etc.) |
| `document_types.py` | `Document` + `ReferencePlanningText` + `L3Report` |
| `canonical.py` | Existing upper-layer typed value objects and historical response models; not a DATA admission input or catalog writer |
| `layer_registry.py` | `GIS_LAYER_REGISTRY` + `GisLayerTypeEntry` + `build_registry_from_yaml()` |
| `gis_layer_registry.yaml` | Single source of truth for layer metadata (40+ entries) |

## Type hierarchy (DU discriminator)

```
L0  SpatialFeature                  (Pydantic BaseModel: geometry + bsm + ysdm + layer_type)
 ├── L1  PointFeature / LineFeature / PolygonFeature   (geometry_type validated at construction)
 └── L2  semantic subclasses (CurrentLandUseParcel, CurrentRoad, FarmlandProtection, ...)

L0  RasterDataset                   (Pydantic BaseModel: path + crs + bounds + bands)
 └── L1  DEMInput / DOMInput / SlopeRaster / ...

L0  TableDataset                    (rows + columns + schema)
 └── L1  PopulationTable / ControlRuleTable / ...

L0  Document                        (text + doc_type + source)
 └── L1  ReferencePlanningText / L3Report
```

The active DATA discriminator is the generic resource metadata in
`resource_catalog.py`: dataset, layer, source feature, representation and capability.
The typed classes in this directory remain only where an upper planning contract still
uses them; they are not exported by `app.data.ingestion` and cannot be used to bypass
`DataAdmissionFacade`.

## Public API

```python
from app.data.model import (
    # Bases
    SpatialFeature, PointFeature, LineFeature, PolygonFeature, RasterDataset,
    TableDataset, Document,
    # Semantic subclasses
    CurrentLandUseParcel, PlannedLandUseParcel, CurrentRoad, PlannedRoad,
    FarmlandProtection, EcologicalRedline, CurrentFacility, PlannedFacility,
    # ... 33 total
    # Upper-layer typed models, where explicitly required
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

See [`docs/guides/how-to-add-layer.md`](../../../../docs/guides/how-to-add-layer.md) for the full guide. Short version:

1. **New layer type**: add YAML entry to `gis_layer_registry.yaml`
2. **New Python class**: add it only for an explicit upper-layer contract; do not add a DATA ingest mapping. DATA inputs remain generic mappings and are normalized by `DataResourceCatalog`.
3. **New DATA layer**: add a declarative source/layer entry and test its admission, representation and capability contract; do not add Bundle fields or typed ingest adapters.
