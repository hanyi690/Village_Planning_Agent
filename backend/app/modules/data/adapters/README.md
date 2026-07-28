# data/adapters - Ingest Adapter Strategy Pattern

> **Purpose**: Converts raw fetch data (dict / path) into typed schema models. Each GIS layer type declares an adapter name in `gis_layer_registry.yaml` (`ingest.adapter`); the adapter registry maps that name to a callable.
> **Updated: 2026-07-28 (v4.8.1)**

---

## Key files

| File | Role |
| --- | --- |
| `__init__.py` | `IngestAdapter` Protocol, `AdapterResult` envelope, `ADAPTERS` registry, `register_adapter()`, `_register_builtin_adapters()` |
| `parcels.py` | `ParcelsAdapter` - land-use parcels with encoding validation (DLBM/GHYTBM) |
| `features.py` | `FeaturesAdapter` - generic vector features (roads, facilities, annotations, control zones, ...) |
| `raster.py` | `RasterAdapter` - GeoTIFF/ raster -> `RasterDataset` subclasses (DEM/DOM/slope) |
| `table.py` | `TableAdapter` - CSV/Excel -> `TableDataset` subclasses |
| `document.py` | `DocumentAdapter` - Markdown/JSON/TXT -> `Document` subclasses |

## Built-in adapters (6)

| Name | Input | Output | Use case |
| --- | --- | --- | --- |
| `parcels` | GeoJSON FeatureCollection | `List[CurrentLandUseParcel \| PlannedLandUseParcel]` | Land parcels requiring encoding validation |
| `features` | GeoJSON FeatureCollection | `List[SpatialFeature subclass]` | Generic vector (roads, facilities, annotations, zones, ...) |
| `raster` | GeoTIFF path string | `List[RasterDataset subclass]` | DEM, DOM, slope, aspect rasters |
| `table` | CSV/Excel path or dict | `List[TableDataset subclass]` | Population, industry, control rules |
| `document` | Markdown/JSON path | `List[Document subclass]` | Planning text, L3 reports |
| `wfs` | WFS GeoJSON response | `List[SpatialFeature subclass]` | WFS API sources (registered dynamically) |

## Protocol

```python
@runtime_checkable
class IngestAdapter(Protocol):
    def load(
        self,
        data: dict,                    # raw payload from DataResult.data
        entry: GisLayerTypeEntry,      # YAML-derived metadata
        *,
        strict: bool = False,          # if True, raise instead of warn on validation failure
    ) -> AdapterResult: ...

@dataclass
class AdapterResult:
    features: list          # typed schema model instances
    warnings: list[str]     # non-blocking validation warnings
    dlq: list[DlqEntry]     # dead-letter entries for failed features
```

## How adapters are dispatched

```
DataCatalog.fetch()
  └── DataResult.data (raw dict/path)
       └── adapter = ADAPTERS[entry.ingest.adapter]   # lookup by YAML name
            └── AdapterResult(features, warnings, dlq)
                 └── _assign_to_bundle(bundle, features)  # isinstance dispatch to morphology groups
```

## How to register a custom adapter

1. Create `adapters/<name>.py` implementing `IngestAdapter`
2. Import and register in `adapters/__init__.py::_register_builtin_adapters()`:
   ```python
   from .my_adapter import MyAdapter
   register_adapter("my_adapter", MyAdapter())
   ```
3. Reference `adapter: my_adapter` in `gis_layer_registry.yaml`

See [`docs/gis/HOW_TO_ADD_LAYER.md`](../../../../../docs/gis/HOW_TO_ADD_LAYER.md) Pattern 3 for a full example.

## Dependencies

- `app.modules.schema.types.layer_registry` (`GisLayerTypeEntry`)
- `app.modules.kg.dlq` (`DlqEntry` - shared dead-letter queue type)
- No deps on `catalog/`, `sources/`, or `connections/` (adapters are pure data transforms)

## How to extend

- **New adapter**: implement `IngestAdapter`, call `register_adapter()`, reference in YAML
- **Adapter returning multiple types**: use `entry.ingest.feature_type` to discriminate
- **Strict mode**: set `strict=True` in `load()` for pipelines that should fail-fast on bad data
