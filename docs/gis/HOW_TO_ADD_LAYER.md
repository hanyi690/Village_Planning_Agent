# How to Add a GIS Layer

> **Authoritative guide** for adding new GIS layer types to the Village Planning Agent.
> Cross-referenced from module READMEs in `schema/`, `data/`, and `kg/`.

There are four patterns, in order of increasing complexity. **90% of new layers need only Pattern 1.**

---

## Pattern 1 — Standard layer (YAML entry only)

The common case. The 6 built-in adapters (`parcels`, `features`, `raster`, `table`, `document`, `wfs`) already cover vector features, rasters, tables, and documents. If your layer fits one of those, just add a YAML entry.

**File**: `backend/app/modules/schema/types/gis_layer_registry.yaml`

```yaml
layer_types:
  my_new_layer:
    i18n:
      zh: 新图层中文名
      en: New layer English name
    geometry_kind: polygon          # polygon | line | point | raster | table | document | annotation
    group: protection               # see groups list in YAML header comment
    ingest:
      adapter: features             # one of: parcels | features | raster | table | document | wfs
      feature_type: my_new_layer    # passed to adapter; usually equals the layer_type key
    bundle_target:
      group: polygons               # points | lines | polygons | rasters | tables | documents
      key: my_new_layer             # field name on the Group dataclass
    spatial:
      is_constraint: false          # true if it's a protection/control layer
    kg:
      entity_type: MyNewLayer       # RDF type label (informational; KG builder decides actual type)
      uri_policy: "L1:my_new_layer_{bsm}"
    validation:
      required_fields: [bsm]
      geometry:
        must_be_valid: true
        dlq_on_error: true          # invalid features -> DLQ instead of crashing
    is_reference_layer: false       # true for central-government approved layers (read-only)
```

Then restart. `build_registry_from_yaml()` runs at import time and registers the entry in `GIS_LAYER_REGISTRY`. `DataCatalog` will discover it, `VillageBundle._assign_to_bundle` will route typed features into `bundle.<group>.<key>`, and `kg.builder` will pick up the `bundle_target` for the registry-driven builder loop.

No Python edits required.

---

## Pattern 2 — Layer with a Python model class

Use this when you want a dedicated `@dataclass` subclass (e.g. `MyNewLayer(PolygonFeature)`) so downstream code can `isinstance`-check it and access typed fields.

**Step 1 — YAML**: same as Pattern 1.

**Step 2 — define the class** in `backend/app/modules/schema/types/spatial_types.py` (vector) or `raster_types.py` (raster) or `table_types.py` (table):

```python
@dataclass
class MyNewLayer(PolygonFeature):
    """New layer with typed fields."""
    protection_level: str = ""
    control_measure: str = ""
```

Export it from `types/__init__.py`.

**Step 3 — register the model class** in `backend/app/modules/data/ingest.py::_infer_model_class()`:

```python
def _infer_model_class(layer_type: str) -> str:
    _CLASS_MAP = {
        # ...existing entries...
        "my_new_layer": "MyNewLayer",
    }
    return _CLASS_MAP.get(layer_type, "")
```

The `features` adapter reads `entry.ingest.feature_type`, calls `_infer_model_class()` to get the class name, and constructs typed instances. `_assign_to_bundle` then routes them via `isinstance`.

Restart. That's it — no KG changes needed unless you want custom KG behavior (Pattern 4).

---

## Pattern 3 — Layer with a custom adapter

Use this when your raw data isn't standard GeoJSON / GeoTIFF / CSV and needs bespoke parsing logic. Example: a WFS service returning GML, or a multi-sheet Excel workbook.

**Step 1 — YAML**: set `ingest.adapter` to your new adapter name.

```yaml
my_new_layer:
  ingest:
    adapter: my_custom_adapter
    feature_type: my_new_layer
```

**Step 2 — implement the adapter** in `backend/app/modules/data/adapters/my_custom_adapter.py`:

```python
from . import IngestAdapter, AdapterResult

class MyCustomAdapter(IngestAdapter):
    def load(self, data: dict, entry, *, strict: bool = False) -> AdapterResult:
        # data = raw payload from DataResult.data (GeoJSON dict, raster path, etc.)
        # entry = GisLayerTypeEntry from YAML
        features = [...]   # build typed schema model instances
        warnings = [...]
        dlq = [...]        # DlqEntry for items that failed validation
        return AdapterResult(features=features, warnings=warnings, dlq=dlq)
```

**Step 3 — register the adapter** in `backend/app/modules/data/adapters/__init__.py::_register_builtin_adapters()`:

```python
def _register_builtin_adapters() -> None:
    from .parcels import ParcelsAdapter
    # ...existing...
    from .my_custom_adapter import MyCustomAdapter
    register_adapter("my_custom_adapter", MyCustomAdapter())
```

Restart. `DataCatalog` will dispatch to your adapter based on the YAML `ingest.adapter` name.

---

## Pattern 4 — Layer with a KG builder

Use this when the layer needs custom RDF triples beyond what the default `kg.entity_type` mapping produces. Example: water bodies need overlap-deduplication; DEM rasters need a `RasterDataset` entity with band metadata.

**Step 1 — YAML**: ensure `kg.entity_type` and `bundle_target` are set (Patterns 1-3).

**Step 2 — write the builder** in `backend/app/modules/kg/builder/layer1.py` (or a new file imported by it):

```python
from .registry import kg_builder, BuildContext

@kg_builder("my_new_layer", entity_type="MyNewLayer")
def _add_my_new_layer(self, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    """Build RDF entities for my_new_layer.

    Args:
        self: PlanningKG instance (use self.g, self._parcel_count, etc.)
        features: list of typed schema models from bundle.<group>.<key>
        gtype_ref: layer_type string (e.g. "my_new_layer")
        entry: GisLayerTypeEntry from YAML
        ctx: BuildContext (village_name, bbox, constraint_index, provenance)

    Returns:
        dict report (logged at debug level)
    """
    count = 0
    for feat in features:
        bsm = str(feat.bsm).strip()
        uri = EntityIdPolicy.uri("my_new_layer", bsm)
        self.g.add((uri, RDF.type, EntityTypes.MyNewLayer))
        self.g.add((uri, PLN.bsm, Literal(bsm)))
        # ...add properties, relations...
        count += 1
    return {"my_new_layer": count}
```

The `@kg_builder` decorator registers the function in `_KG_BUILDERS`. During `build_from_bundle()`, the registry loop (see `builder/base.py:126`) iterates `_KG_BUILDERS`, fetches features from `bundle.<group>.<key>` via `_get_bundle_features()`, and calls each builder.

Restart. No further wiring — the registry handles discovery and dispatch.

---

## Worked example: adding a DEM raster layer

This example traces the full path for the `dem` layer type, which already exists in the codebase. It references the clip script at `backend/scripts/clip_dem_to_aoi.py` and the `dem_local` source in `sources.yaml`.

### Step 1 — Prepare the raster file

Province-wide DEM rasters (e.g. NASA ASTGTM v3, 30m) are too large to load directly. Clip to the village AOI first:

```bash
python backend/scripts/clip_dem_to_aoi.py \
    --input data/gis/广东DEM30M.zip \
    --aoi data/gis/jintian/current/boundary.geojson \
    --output data/gis/jintian/terrain/dem.tif
```

The script reads the AOI bbox from the boundary GeoJSON, selects the ASTGTM tiles overlapping the bbox, and either clips with `rasterio.mask` (if available) or copies a single tile verbatim. Output is an EPSG:4326 GeoTIFF.

### Step 2 — YAML registry entry

Already present in `gis_layer_registry.yaml`:

```yaml
dem:
  i18n:
    zh: 数字高程模型
    en: Digital elevation model
  geometry_kind: raster
  group: raster
  ingest:
    adapter: raster
    feature_type: dem
  bundle_target:
    group: rasters
    key: dem
  spatial:
    is_constraint: false
  kg:
    entity_type: RasterDataset
    uri_policy: "L1:dem_{bsm}"
  validation:
    required_fields: []
    geometry:
      must_be_valid: true
      dlq_on_error: true
```

### Step 3 — Python model class

`DEMInput` is defined in `backend/app/modules/schema/types/raster_types.py` and mapped in `ingest.py::_infer_model_class()`:

```python
_CLASS_MAP = {
    # ...
    "dem": "DEMInput",
}
```

### Step 4 — Data source in `sources.yaml`

Already present in `backend/app/modules/data/catalog/sources.yaml`:

```yaml
dem_local:
  driver: local_raster
  path: "data/gis/jintian/terrain/dem.tif"
  format: GeoTIFF
  crs: EPSG:4326
  layer_type: dem
```

### Step 5 — KG builder (optional, Pattern 4)

The `dem` layer has a dedicated builder because it produces a single `RasterDataset` entity with band metadata rather than per-feature entities. See `backend/app/modules/kg/builder/layer1.py:953`:

```python
@kg_builder("dem", entity_type="RasterDataset")
def _add_dem_raster(self, features, *, gtype_ref, entry, ctx) -> dict:
    # features = [dem_raster] (single element, since RasterLayerGroup.dem is a scalar)
    ...
```

### Result

`catalog.load_village_bundle("金田村委会")` now loads `dem.tif` via `LocalRasterDriver`, the `raster` adapter constructs a `DEMInput` instance, `_bundle_key_for()` YAML routing places it at `bundle.rasters.dem`, and `kg.build_from_bundle()` invokes the `@kg_builder("dem")` function to emit the RDF entity.

---

## Pattern 5 — L4 planned output layer (规划产出)

For GeoJSON files that represent **planning outputs** (not L1 reference layers), use the L4 planned state path. These are currently:
- `planned/landuse.geojson` → `PlannedParcelEntry`
- `planned/road.geojson` → `PlannedRoadEntry`
- `planned/construction_zone.geojson` → `PlannedZoneEntry`

### Step 1 — YAML registration

Mark the layer as `is_planned_output: true` so the L1 builder loop skips it:

```yaml
my_planned_layer:
    geometry_kind: polygon
    group: planned_output           # NOT a standard L1 group
    bundle_target:
      group: polygons
      key: my_planned_layer
    spatial:
      is_planned_output: true
```

### Step 2 — L4 ingestion function

Add a handler in `ingest_planned_state_from_geojson()` in `backend/app/modules/kg/builder/layer4.py`. The function reads GeoJSON directly, maps fields to `PlannedParcelEntry`/`PlannedRoadEntry`/`PlannedZoneEntry`, and returns a `PlannedState`:

```python
# In ingest_planned_state_from_geojson():
cz_path = data_dir / "planned" / "my_planned_layer.geojson"
if cz_path.exists():
    # ... read GeoJSON, map fields, append to state.zones / state.parcels / state.roads
```

### Step 3 — Pass to build_from_bundle

The render script and test fixture pass `planned_state` to `build_from_bundle()`:

```python
from app.modules.kg.builder.layer4 import ingest_planned_state_from_geojson
planned_state = ingest_planned_state_from_geojson(data_dir)
kg.build_from_bundle(..., planned_state=planned_state)
```

L4 entities appear as `PlannedParcel`/`PlannedRoad`/`PlannedZone` in the KG with dashed-line styling on the map.

---

## Checklist

Before submitting a new layer:

- [ ] YAML entry in `gis_layer_registry.yaml` with `geometry_kind`, `group`, `ingest.adapter`, `bundle_target`, `kg.entity_type`
- [ ] (If Pattern 2) Python class defined and exported; mapping added to `_infer_model_class()`
- [ ] (If Pattern 3) Custom adapter implemented and registered in `_register_builtin_adapters()`
- [ ] (If Pattern 4) `@kg_builder` function written; features flow from `bundle.<group>.<key>`
- [ ] Data source entry in `sources.yaml` (or upload path configured)
- [ ] `_assign_to_bundle` handles the new type (automatic for Pattern 2; falls into `inferred` list for Pattern 1)
- [ ] Restart and verify: `catalog.load_village_bundle()` returns the layer in the right bundle group

## See also

- `backend/app/modules/schema/README.md` §5 — registry design
- `backend/app/modules/schema/types/layer_registry.py` — `GisLayerTypeEntry` schema + `build_registry_from_yaml()`
- `backend/app/modules/data/adapters/__init__.py` — `IngestAdapter` protocol + `register_adapter()`
- `backend/app/modules/data/ingest.py` — `_infer_model_class()` and ingest ports
- `backend/app/modules/kg/builder/registry.py` — `@kg_builder` decorator + `BuildContext`
