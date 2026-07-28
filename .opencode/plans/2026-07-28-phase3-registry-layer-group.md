# Phase 3+4: Registry 元模型扩展 + LayerGroup 动态化 + 下游清理

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.
>
> **Goal:** 将 `_assign_to_bundle` 33 分支 isinstance 链替换为 `bundle.add()`,将 `_TYPE_BINDINGS` 手写表替换为 YAML 派生,将 LayerGroup 硬编码字段替换为 `_layers` 动态 dict,更新所有下游消费者(约 45 文件)。
>
> **Architecture:** `GisLayerTypeEntry` 扩展嵌套模型(YAML 全量元数据);`_TYPE_BINDINGS` 删除;`build_registry_from_yaml()` 从 YAML 提取所有字段;`LayerGroup` 用 `_layers: dict[str, list[GisFeature]]` 替代硬编码字段;`VillageBundle.add(feature)` 通过 registry 的 `bundle_target` 路由;`to_geojson_dict()` 迭代 `_layers` 产出一致 GeoJSON。
>
> **Tech Stack:** Pydantic v2, YAML, isinstance→DU discriminator

## Global Constraints

- 不保留兼容 property,所有下游直接 `bundle.polygons.get("key")`
- `_TYPE_BINDINGS` 整块删除,不保留 fallback
- `_assign_to_bundle` 整块删除,不保留兼容 shim
- `_build_from_bindings_only()` 整块删除
- `register_gis_layer_type()` 函数签名简化(只保留 `gis_type_ref` + `meta: dict`)
- 所有测试必须通过;新增测试覆盖 registry 新模型 + LayerGroup.add + bundle.add + to_geojson_dict 兼容性

---

## File Structure

| 文件 | 角色 | 变更类型 |
|------|------|---------|
| `schema/types/layer_registry.py` | Registry 定义 + 工厂函数 | 重写 |
| `schema/types/gis_layer_registry.yaml` | Registry 数据(全量元模型) | 扩展 |
| `schema/types/canonical.py` | LayerGroup 动态化 + VillageBundle.add | 重写 |
| `schema/types/spatial_types.py` | GisFeature DU 定义 | 无需改(已有) |
| `data/ingest.py` | _init_feature_registry 适配新 registry | 修改 |
| `data/catalog/catalog.py` | 删除 _assign_to_bundle, 改用 bundle.add | 修改 |
| `data/__init__.py` | 导出 | 无需改 |
| `spatial_ops/context.py` | 15 处 bundle.polygons.* 访问 | 更新 |
| `spatial_ops/bridge.py` | 10 处 bundle.polygons.* 访问 | 更新 |
| `spatial_ops/grounding.py` | 4 处 bundle.polygons.landuse_current | 更新 |
| `spatial_ops/constraint_compiler.py` | 6 处 bundle.polygons.* 访问 | 更新 |
| `spatial_ops/road_planner.py` | 1 处 docstring | 更新 |
| `kg/builder/base.py` | 7 处 bundle.* 访问 | 更新 |
| `kg/builder/layer1.py` | 3 处 docstring + 2 处 getattr | 更新 |
| `kg/manager.py` | 1 处 bundle.polygons.landuse_current | 更新 |
| `kg/ontology.py` | 1 处 GIS_LAYER_REGISTRY 迭代 | 更新 |
| `agent/graph.py` | 5 处 bundle.* 访问 | 更新 |
| `agent/gis/layout_pipeline.py` | 4 处 bundle.* 访问 | 更新 |
| `agent/gis/execute/agent.py` | 2 处 bundle.* 访问 | 更新 |
| `agent/gis_context.py` | 2 处 bundle 引用(已走 get_data_by_type) | 更新 |
| `tools/gis_data/fetch.py` | 6 处 bundle.* 访问 | 更新 |
| `tools/gis/_analytics/coverage.py` | 4 处 bundle.* 访问 | 更新 |
| `api/session_routes.py` | 2 处 bundle.boundary | 更新 |
| `api/gis_test_routes.py` | 1 处 bundle.to_geojson_dict | 无需改(API 不变) |
| 测试文件 | 新测试 | 新增 |

---

### Task 1: Registry 元模型扩展

**Files:**
- Modify: `backend/app/modules/schema/types/layer_registry.py`
- Modify: `backend/app/modules/schema/types/gis_layer_registry.yaml`

**Interfaces:**
- Consumes: `gis_layer_registry.yaml` current structure, `_TYPE_BINDINGS` dict
- Produces: `GisLayerTypeEntry` with nested models, expanded YAML, `build_registry_from_yaml()` pure YAML

- [ ] **Step 1: Write failing test for new registry model**

```python
# In tests/unit/test_layer_registry.py (new file)
def test_ingest_spec_nested_model():
    from app.modules.schema.types.layer_registry import GisLayerTypeEntry, IngestSpec, Bundletarget
    spec = IngestSpec(adapter="features", feature_type="water")
    entry = GisLayerTypeEntry(
        gis_type_ref="water", geometry_kind="polygon",
        ingest=spec, bundle_target=Bundletarget(group="polygons", key="water_bodies"),
    )
    assert entry.ingest.adapter == "features"
    assert entry.bundle_target.key == "water_bodies"
    assert entry.model_dump()["gis_type_ref"] == "water"

def test_registry_built_from_yaml_only():
    from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY
    entry = GIS_LAYER_REGISTRY.get("landuse_current")
    assert entry is not None
    assert entry.ingest is not None
    assert entry.ingest.adapter == "parcels"
    assert entry.bundle_target is not None
    assert entry.bundle_target.key == "landuse_current"
    assert entry.spatial is not None
    assert not entry.spatial.is_constraint

def test_no_type_bindings_remain():
    import app.modules.schema.types.layer_registry as reg
    assert not hasattr(reg, "_TYPE_BINDINGS")

def test_no_build_from_bindings_only():
    import app.modules.schema.types.layer_registry as reg
    assert not hasattr(reg, "_build_from_bindings_only")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_layer_registry.py -v`
Expected: ImportError or AttributeError

- [ ] **Step 3: Rewrite `layer_registry.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class IngestSpec(BaseModel):
    adapter: str = "features"          # "parcels" | "features" | "raster" | "table" | "document"
    feature_type: str = ""             # e.g. "current_landuse", "water_feature"


class EncodingsSpec(BaseModel):
    dlbm_field: str = ""
    systems: List[str] = Field(default_factory=list)


class SpatialSpec(BaseModel):
    is_constraint: bool = False
    participates: List[str] = Field(default_factory=list)


class Bundletarget(BaseModel):
    group: str = "polygons"            # "points" | "lines" | "polygons" | "rasters" | "tables" | "documents"
    key: str = ""                      # e.g. "landuse_current", "water_bodies"


class KgSpec(BaseModel):
    entity_type: str = ""
    uri_policy: str = "L1:{type}_{bsm}"


class ValidationSpec(BaseModel):
    required_fields: List[str] = Field(default_factory=list)
    geometry: Dict[str, bool] = Field(default_factory=lambda: {"must_be_valid": True, "dlq_on_error": True})


class GisLayerTypeEntry(BaseModel):
    gis_type_ref: str
    geometry_kind: str = ""
    i18n: Dict[str, str] = Field(default_factory=dict)
    group: str = ""
    ingest: Optional[IngestSpec] = None
    encodings: Optional[EncodingsSpec] = None
    spatial: Optional[SpatialSpec] = None
    bundle_target: Optional[Bundletarget] = None
    kg: Optional[KgSpec] = None
    validation: Optional[ValidationSpec] = None
    default_gdb_path: str = ""
    is_reference_layer: bool = False
    description: str = ""


GIS_LAYER_REGISTRY: Dict[str, GisLayerTypeEntry] = {}


def register_gis_layer_type(gis_type_ref: str, meta: dict) -> None:
    entry = GisLayerTypeEntry(
        gis_type_ref=gis_type_ref,
        geometry_kind=meta.get("geometry_kind", ""),
        i18n=meta.get("i18n", {}),
        group=meta.get("group", ""),
        ingest=IngestSpec(**meta["ingest"]) if "ingest" in meta else None,
        encodings=EncodingsSpec(**meta["encodings"]) if "encodings" in meta else None,
        spatial=SpatialSpec(**meta["spatial"]) if "spatial" in meta else None,
        bundle_target=Bundletarget(**meta["bundle_target"]) if "bundle_target" in meta else None,
        kg=KgSpec(**meta["kg"]) if "kg" in meta else None,
        validation=ValidationSpec(**meta["validation"]) if "validation" in meta else None,
        default_gdb_path=meta.get("default_gdb_path", ""),
        is_reference_layer=meta.get("is_reference_layer", False),
        description=meta.get("description", ""),
    )
    GIS_LAYER_REGISTRY[gis_type_ref] = entry


def get_gis_layer_entry(gis_type_ref: str) -> Optional[GisLayerTypeEntry]:
    return GIS_LAYER_REGISTRY.get(gis_type_ref)


def get_all_gis_layer_types() -> List[str]:
    return list(GIS_LAYER_REGISTRY.keys())


def build_registry_from_yaml(yaml_path: Optional[str] = None) -> None:
    if yaml_path is None:
        yaml_path = str(Path(__file__).parent / "gis_layer_registry.yaml")
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return

    gis_layer_types = yaml_data.get("layer_types", {})
    for gis_type_ref, meta in gis_layer_types.items():
        register_gis_layer_type(gis_type_ref, meta)


build_registry_from_yaml()


__all__ = [
    "GisLayerTypeEntry", "IngestSpec", "EncodingsSpec", "SpatialSpec",
    "Bundletarget", "KgSpec", "ValidationSpec",
    "GIS_LAYER_REGISTRY", "register_gis_layer_type",
    "get_gis_layer_entry", "get_all_gis_layer_types", "build_registry_from_yaml",
]
```

- [ ] **Step 4: Expand `gis_layer_registry.yaml` with full metadata**

Each entry gets `ingest`, `bundle_target`, `spatial`, `kg`, `validation` blocks. Example:

```yaml
layer_types:
  landuse_current:
    i18n: {zh: 现状地类, en: Current Land Use}
    geometry_kind: polygon
    group: landuse
    ingest:
      adapter: parcels
      feature_type: current_landuse
    encodings:
      dlbm_field: dlbm
      systems: [gbt21010]
    spatial:
      is_constraint: false
    bundle_target: {group: polygons, key: landuse_current}
    kg:
      entity_type: Parcel
      uri_policy: "L1:parcel_{bsm}"
    validation:
      required_fields: [dlbm, bsm]
      geometry: {must_be_valid: true, dlq_on_error: true}

  water:
    i18n: {zh: 水系, en: Water}
    geometry_kind: polygon
    group: natural
    ingest:
      adapter: features
      feature_type: water_feature
    spatial:
      is_constraint: false
      participates: [water_overlap]
    bundle_target: {group: polygons, key: water_bodies}
    kg:
      entity_type: WaterBody
      uri_policy: "L1:water_{bsm}"

  farmland_protection:
    i18n: {zh: 永久基本农田, en: Farmland Protection}
    geometry_kind: polygon
    group: protection
    ingest:
      adapter: features
      feature_type: farmland_protection
    spatial:
      is_constraint: true
    bundle_target: {group: polygons, key: farmland_protection}
    kg:
      entity_type: ConstraintZone
      uri_policy: "L1:constraint_{bsm}"

  # ... all 40+ entries with the same structure
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_layer_registry.py -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/schema/types/layer_registry.py
git add backend/app/modules/schema/types/gis_layer_registry.yaml
git add tests/unit/test_layer_registry.py
git commit -m "feat(phase3): registry meta-model with nested specs, delete _TYPE_BINDINGS"
```

---

### Task 2: _init_feature_registry 适配新 registry

**Files:**
- Modify: `backend/app/modules/data/ingest.py`

**Interfaces:**
- Consumes: `GIS_LAYER_REGISTRY` with new `IngestSpec` nested model
- Produces: `_FEATURE_TYPE_REGISTRY` still populated with `(model_class, gdb_path)` tuples

- [ ] **Step 1: Write failing test**

Already covered by `test_registry_built_from_yaml_only` above — the ingest.py file must import without error after the registry change.

- [ ] **Step 2: Update `_init_feature_registry()` in `ingest.py`**

Change from `entry.ingest_port` / `entry.ingest_arg` / `entry.model_class_name` to `entry.ingest.feature_type` / `entry.ingest.adapter`:

```python
def _init_feature_registry():
    if _FEATURE_TYPE_REGISTRY:
        return
    from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY
    from app.modules.schema import spatial_types as _st
    for lt, entry in GIS_LAYER_REGISTRY.items():
        if entry.ingest is None:
            continue
        model_class = getattr(_st, _infer_model_class(lt), None)
        if model_class is None:
            continue
        key = entry.ingest.feature_type or lt
        _FEATURE_TYPE_REGISTRY[key] = (model_class, entry.default_gdb_path)


def _infer_model_class(layer_type: str) -> str:
    _CLASS_MAP = {
        "landuse_current": "CurrentLandUseParcel",
        "landuse_planned": "PlannedLandUseParcel",
        "water": "WaterFeature",
        "road": "CurrentRoad",
        "road_planned": "PlannedRoad",
        "admin_area": "AdminArea",
        "admin_boundary_line": "AdminBoundaryLine",
        "farmland_protection": "FarmlandProtection",
        "ecological_redline": "EcologicalRedline",
        "urban_dev_boundary": "UrbanDevBoundary",
        "village_dev_boundary": "VillageDevBoundary",
        "cultivated_land_target": "CultivatedLandTarget",
        "historical_protection": "HistoricalProtection",
        "construction_zone": "ConditionalConstructionZone",
        "geological_hazard_points": "GeologicalHazardPoint",
        "planning_scope": "PlanningScope",
        "land_use_zone": "LandUseZone",
        "space_control_zone": "ConstructionCtrlZone",
        "hazard_control_line": "HazardControlLine",
        "flood_control_line": "FloodControlLine",
        "contour_line": "ContourLine",
        "elevation_point": "ElevationPoint",
        "current_building": "CurrentBuilding",
        "current_facility": "CurrentFacility",
        "facility_planned": "PlannedFacility",
        "annotation": "CurrentAnnotation",
        "annotation_planned": "PlannedAnnotation",
        "three_zone": "ThreeZoneItem",
        "soil_type": "SoilType",
        "soil_erosion": "SoilErosion",
        "watershed": "Watershed",
        "nature_reserve": "NatureReserve",
        "hydrogeology_zone": "HydrogeologyZone",
        "dem": "DEMInput",
        "dom": "DOMInput",
        "population": "PopulationTable",
        "construction_projects": "ConstructionProjectTable",
        "control_rules": "ControlRuleTable",
        "planning_indicators": "PlanningIndicatorTable",
        "land_use_structure": "LandUseStructureTable",
    }
    return _CLASS_MAP.get(layer_type, "")
```

- [ ] **Step 3: Remove `_TYPE_BINDINGS` import references in `build_registry_from_yaml`**

The `build_registry_from_yaml()` in `layer_registry.py` no longer reads `_TYPE_BINDINGS`. The `ingest.py` `_init_feature_registry()` now uses `_infer_model_class()` instead of `entry.model_class_name`.

- [ ] **Step 4: Run all existing tests to verify nothing breaks**

Run: `python -m pytest tests/unit/ -v --tb=short -q`
Expected: 135+ PASS (should still pass since registry API change is backward-compatible at the import level)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/data/ingest.py
git add backend/app/modules/schema/types/layer_registry.py
git commit -m "feat(phase3): _init_feature_registry reads from new registry model"
```

---

### Task 3: LayerGroup 动态化 + VillageBundle.add()

**Files:**
- Modify: `backend/app/modules/schema/types/canonical.py`

**Interfaces:**
- Consumes: `GIS_LAYER_REGISTRY` with `Bundletarget`, `GisFeature` DU
- Produces: `LayerGroup._layers: dict`, `LayerGroup.add()`, `LayerGroup.get()`, `VillageBundle.add()`, `to_geojson_dict()` from `_layers`

- [ ] **Step 1: Write failing tests**

```python
# In tests/unit/test_canonical_dynamic_layers.py (new file)
def test_layer_group_add_and_get():
    from app.modules.schema.types.canonical import PolygonLayerGroup
    from app.modules.schema.types.spatial_types import CurrentLandUseParcel
    group = PolygonLayerGroup()
    p = CurrentLandUseParcel(geometry={"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, bsm="001", dlbm="0101")
    group.add(p)
    parcels = group.get("landuse_current")
    assert len(parcels) == 1
    assert parcels[0].bsm == "001"

def test_unknown_layer_type_goes_to_inferred():
    from app.modules.schema.types.canonical import PolygonLayerGroup
    from app.modules.schema.types.spatial_types import PolygonFeature
    feat = PolygonFeature(geometry={"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, layer_type="unknown_type")
    group = PolygonLayerGroup()
    group.add(feat)
    inferred = group.get("inferred")
    assert len(inferred) == 1

def test_village_bundle_add_routes_by_geometry():
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.schema.types.spatial_types import CurrentLandUseParcel, CurrentRoad, CurrentFacility
    bundle = VillageBundle(village_name="test")
    parcel = CurrentLandUseParcel(geometry={"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, bsm="001")
    road = CurrentRoad(geometry={"type": "LineString", "coordinates": [[0,0],[1,1]]}, bsm="002")
    facility = CurrentFacility(geometry={"type": "Point", "coordinates": [0.5, 0.5]}, bsm="003")
    bundle.add(parcel)
    bundle.add(road)
    bundle.add(facility)
    assert len(bundle.polygons.get("landuse_current")) == 1
    assert len(bundle.lines.get("roads_current")) == 1
    assert len(bundle.points.get("facilities_current")) == 1

def test_village_bundle_boundary():
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.schema.types.spatial_types import AdminArea
    bundle = VillageBundle(village_name="test")
    a = AdminArea(geometry={"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, bsm="001")
    bundle.add(a)
    assert bundle.boundary is not None
    assert bundle.boundary.bsm == "001"

def test_to_geojson_dict_from_layers():
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.schema.types.spatial_types import CurrentLandUseParcel, WaterFeature
    bundle = VillageBundle(village_name="test")
    p = CurrentLandUseParcel(geometry={"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, bsm="001", dlbm="0101")
    w = WaterFeature(geometry={"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, bsm="002")
    bundle.add(p)
    bundle.add(w)
    result = bundle.to_geojson_dict()
    assert "landuse_current_geojson" in result
    assert "water_geojson" in result

def test_parcel_count_from_layers():
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.schema.types.spatial_types import CurrentLandUseParcel, PlannedLandUseParcel
    bundle = VillageBundle(village_name="test")
    bundle.add(CurrentLandUseParcel(geometry={"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, bsm="001"))
    bundle.add(PlannedLandUseParcel(geometry={"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, bsm="002"))
    assert bundle.parcel_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_canonical_dynamic_layers.py -v`
Expected: FAIL (no `add()` method yet)

- [ ] **Step 3: Rewrite `canonical.py` LayerGroup classes**

```python
class PointLayerGroup(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _layers: Dict[str, List[Any]] = {}

    def add(self, feature: Any) -> None:
        key = _bundle_key_for(feature)
        self._layers.setdefault(key, []).append(feature)

    def get(self, key: str) -> List[Any]:
        return self._layers.get(key, [])

    def keys(self) -> List[str]:
        return list(self._layers.keys())

    @property
    def all_features(self) -> List[Any]:
        result = []
        for k, v in self._layers.items():
            if k not in ("annotations_current", "annotations_planned"):
                result.extend(v)
        return result

    @property
    def facilities(self) -> List[Any]:
        return self.get("facilities_current") + self.get("facilities_planned")


class LineLayerGroup(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _layers: Dict[str, List[Any]] = {}

    def add(self, feature: Any) -> None:
        key = _bundle_key_for(feature)
        self._layers.setdefault(key, []).append(feature)

    def get(self, key: str) -> List[Any]:
        return self._layers.get(key, [])

    def keys(self) -> List[str]:
        return list(self._layers.keys())

    @property
    def all_features(self) -> List[Any]:
        result = []
        for v in self._layers.values():
            result.extend(v)
        return result

    @property
    def roads(self) -> List[Any]:
        return self.get("roads_current") + self.get("roads_planned")


class PolygonLayerGroup(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _layers: Dict[str, List[Any]] = {}

    def add(self, feature: Any) -> None:
        key = _bundle_key_for(feature)
        self._layers.setdefault(key, []).append(feature)

    def get(self, key: str) -> List[Any]:
        return self._layers.get(key, [])

    def keys(self) -> List[str]:
        return list(self._layers.keys())

    @property
    def constraint_polygons(self) -> List[Any]:
        from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY
        result = []
        for lt, entry in GIS_LAYER_REGISTRY.items():
            if entry.spatial and entry.spatial.is_constraint and entry.bundle_target:
                result.extend(self.get(entry.bundle_target.key))
        return result

    @property
    def all_features(self) -> List[Any]:
        result = []
        for v in self._layers.values():
            result.extend(v)
        return result

    @property
    def parcels(self) -> List[Any]:
        return self.get("landuse_current") + self.get("landuse_planned")
```

- [ ] **Step 4: Add `_bundle_key_for()` helper and `VillageBundle.add()`**

```python
def _bundle_key_for(feature: Any) -> str:
    from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY
    lt = getattr(feature, "layer_type", "")
    entry = GIS_LAYER_REGISTRY.get(lt)
    if entry and entry.bundle_target:
        return entry.bundle_target.key
    return "inferred"


def _geometry_group_for(feature: Any) -> str:
    from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY
    lt = getattr(feature, "layer_type", "")
    entry = GIS_LAYER_REGISTRY.get(lt)
    if entry and entry.bundle_target:
        return entry.bundle_target.group
    geom = getattr(feature, "geometry", {})
    gtype = geom.get("type", "") if isinstance(geom, dict) else ""
    if gtype in ("Point", "MultiPoint"):
        return "points"
    elif gtype in ("LineString", "MultiLineString"):
        return "lines"
    elif gtype in ("Polygon", "MultiPolygon"):
        return "polygons"
    return "polygons"
```

- [ ] **Step 5: Update `VillageBundle` class**

```python
class VillageBundle(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    village_name: str
    points: PointLayerGroup = Field(default_factory=PointLayerGroup)
    lines: LineLayerGroup = Field(default_factory=LineLayerGroup)
    polygons: PolygonLayerGroup = Field(default_factory=PolygonLayerGroup)
    rasters: RasterLayerGroup = Field(default_factory=RasterLayerGroup)
    tables: TableLayerGroup = Field(default_factory=TableLayerGroup)
    documents: DocumentGroup = Field(default_factory=DocumentGroup)
    metadata: VillageMetadata = Field(default_factory=VillageMetadata)
    standard_version: str = "4.4"

    def add(self, feature: Any) -> None:
        group = _geometry_group_for(feature)
        if group == "points":
            self.points.add(feature)
        elif group == "lines":
            self.lines.add(feature)
        elif group == "polygons":
            self.polygons.add(feature)
        elif group == "rasters":
            pass
        elif group == "tables":
            pass
        elif group == "documents":
            pass

    @property
    def boundary(self) -> Any:
        admin = self.polygons.get("admin_areas")
        if admin:
            return admin[0]
        scope = self.polygons.get("planning_scope")
        if scope:
            return scope[0]
        return None

    @property
    def all_features(self) -> List[Any]:
        return [
            *self.points.all_features,
            *self.lines.all_features,
            *self.polygons.all_features,
        ]

    @property
    def parcel_count(self) -> int:
        return len(self.polygons.get("landuse_current")) + len(self.polygons.get("landuse_planned"))

    @property
    def total_area_ha(self) -> float:
        return sum(
            getattr(p, "area_ha", 0.0)
            for p in self.polygons.get("landuse_current") + self.polygons.get("landuse_planned")
        )

    def get_parcels_by_dlbm(self, dlbm: str) -> List[Any]:
        all_parcels = self.polygons.get("landuse_current") + self.polygons.get("landuse_planned")
        return [p for p in all_parcels if getattr(p, "dlbm", "") == dlbm]

    def get_parcels_by_zone(self, zone_type: str) -> List[Any]:
        all_parcels = self.polygons.get("landuse_current") + self.polygons.get("landuse_planned")
        return [p for p in all_parcels if getattr(p, "zone_type", "") == zone_type]

    def is_complete(self) -> bool:
        return self.boundary is not None and self.parcel_count > 0

    def to_geojson_dict(self) -> Dict[str, Any]:
        gis_data: Dict[str, Any] = {}
        if self.boundary is not None:
            gis_data["boundary_geojson"] = _features_to_fc([self.boundary])
        lu = self.polygons.get("landuse_current")
        if lu:
            gis_data["landuse_current_geojson"] = _features_to_fc(lu)
        lp = self.polygons.get("landuse_planned")
        if lp:
            gis_data["landuse_planned_geojson"] = _features_to_fc(lp)
        all_roads = self.lines.get("roads_current") + self.lines.get("roads_planned")
        if all_roads:
            gis_data["road_geojson"] = _features_to_fc(all_roads)
        wb = self.polygons.get("water_bodies")
        if wb:
            gis_data["water_geojson"] = _features_to_fc(wb)
        all_annotations = self.points.get("annotations_current") + self.points.get("annotations_planned")
        if all_annotations:
            gis_data["annotation_geojson"] = _features_to_fc(all_annotations)
        for key in self.polygons.keys():
            feats = self.polygons.get(key)
            if feats and key not in ("landuse_current", "landuse_planned", "water_bodies"):
                gis_data[f"{key}_geojson"] = _features_to_fc(feats)
        gis_data["_metadata"] = {
            "village_name": self.metadata.village_name,
            "bbox": self.metadata.bbox_wgs84.as_tuple if self.metadata.bbox_wgs84 else None,
        }
        return gis_data
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_canonical_dynamic_layers.py -v`
Expected: 6 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/schema/types/canonical.py
git add tests/unit/test_canonical_dynamic_layers.py
git commit -m "feat(phase3+4): dynamic _layers dict, bundle.add(), to_geojson_dict from _layers"
```

---

### Task 4: catalog.py — 删除 _assign_to_bundle, 改用 bundle.add()

**Files:**
- Modify: `backend/app/modules/data/catalog/catalog.py`

**Interfaces:**
- Consumes: `VillageBundle.add()` from canonical.py
- Produces: Clean `load_village_bundle()` without isinstance chain

- [ ] **Step 1: Write failing test**

```python
# In tests/unit/test_catalog_routing.py
def test_catalog_uses_bundle_add_not_assign():
    from app.modules.data.catalog.catalog import DataCatalog
    assert not hasattr(DataCatalog, "_assign_to_bundle")
```

- [ ] **Step 2: Update `load_village_bundle()` in `catalog.py`**

Remove the isinstance import aliases at the top of catalog.py:
```python
# DELETE these lines:
# from app.modules.schema.types.spatial_types import (
#     CurrentLandUseParcel as _CurrentLandUseParcel,
#     PlannedLandUseParcel as _PlannedLandUseParcel,
#     ... 33 aliases ...
# )
```

Update `load_village_bundle()`:
- Replace `self._assign_to_bundle(bundle, parcels)` → `for p in parcels: bundle.add(p)`
- Replace `self._assign_to_bundle(bundle, features)` → `for f in features: bundle.add(f)`
- Replace water body fallback:
```python
if not bundle.polygons.get("water_bodies") and bundle.polygons.get("landuse_current"):
    from app.modules.schema.types.spatial_types import WaterFeature
    for p in bundle.polygons.get("landuse_current"):
        dlbm = getattr(p, "dlbm", "") or ""
        if dlbm.startswith("31"):
            wf = WaterFeature(
                geometry=p.geometry, bsm=p.bsm, ysdm=p.ysdm,
                layer_type="water",
                water_type={"3101": "河流", "3102": "湖泊", "3103": "水库",
                            "3104": "坑塘", "3105": "沟渠"}.get(dlbm[:4], "坑塘"),
                water_name=getattr(p, "name", "") or "",
            )
            bundle.add(wf)
```

- Delete the entire `_assign_to_bundle` static method (lines 537-625)

- Update logging line:
```python
logger.info(
    "[DataCatalog] load_village_bundle('%s'): %d parcels, %d roads, %d annotations",
    village_name, bundle.parcel_count,
    len(bundle.lines.get("roads_current")) + len(bundle.lines.get("roads_planned")),
    len(bundle.points.get("annotations_current")) + len(bundle.points.get("annotations_planned")),
)
```

- [ ] **Step 3: Run all tests**

Run: `python -m pytest tests/ -v --tb=short -q -x`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/modules/data/catalog/catalog.py
git commit -m "feat(phase3): delete _assign_to_bundle, use bundle.add() in catalog"
```

---

### Task 5: spatial_ops/ 模块更新

**Files:**
- Modify: `backend/app/modules/spatial_ops/context.py` (~15 lines)
- Modify: `backend/app/modules/spatial_ops/bridge.py` (~10 lines)
- Modify: `backend/app/modules/spatial_ops/grounding.py` (~4 lines)
- Modify: `backend/app/modules/spatial_ops/constraint_compiler.py` (~6 lines)
- Modify: `backend/app/modules/spatial_ops/road_planner.py` (~1 line docstring)

**Pattern:**
- `bundle.polygons.landuse_current` → `bundle.polygons.get("landuse_current")`
- `bundle.polygons.water_bodies` → `bundle.polygons.get("water_bodies")`
- `bundle.polygons.farmland_protection` → `bundle.polygons.get("farmland_protection")`
- `bundle.polygons.ecological_redline` → `bundle.polygons.get("ecological_redline")`
- `bundle.polygons.admin_areas` → `bundle.polygons.get("admin_areas")`
- `bundle.polygons.planning_scope` → `bundle.polygons.get("planning_scope")`
- `bundle.polygons.construction_zone` → `bundle.polygons.get("construction_zone")`
- `bundle.polygons.constraint_polygons` → `bundle.polygons.constraint_polygons` (property stays)
- `bundle.lines.roads_current` → `bundle.lines.get("roads_current")`
- `bundle.lines.roads_planned` → `bundle.lines.get("roads_planned")`
- `bundle.points.facilities_current` → `bundle.points.get("facilities_current")`
- `bundle.points.annotations_current` → `bundle.points.get("annotations_current")`
- `bundle.parcel_count` → `bundle.parcel_count` (property stays)
- `bundle.total_area_ha` → `bundle.total_area_ha` (property stays)
- `bundle.boundary` → `bundle.boundary` (property stays)
- `bundle.village_name` → `bundle.village_name` (field stays)
- `bundle.metadata` → `bundle.metadata` (field stays)

- [ ] **Step 1: Update context.py using the pattern above**
- [ ] **Step 2: Update bridge.py using the pattern above**
- [ ] **Step 3: Update grounding.py using the pattern above**
- [ ] **Step 4: Update constraint_compiler.py using the pattern above**
- [ ] **Step 5: Update road_planner.py docstring**
- [ ] **Step 6: Run all tests**

Run: `python -m pytest tests/unit/ -v --tb=short -q -x`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/spatial_ops/context.py
git add backend/app/modules/spatial_ops/bridge.py
git add backend/app/modules/spatial_ops/grounding.py
git add backend/app/modules/spatial_ops/constraint_compiler.py
git add backend/app/modules/spatial_ops/road_planner.py
git commit -m "feat(phase3): spatial_ops uses .get() instead of direct field access"
```

---

### Task 6: kg/builder/ 模块更新

**Files:**
- Modify: `backend/app/modules/kg/builder/base.py`
- Modify: `backend/app/modules/kg/builder/layer1.py`
- Modify: `backend/app/modules/kg/manager.py`
- Modify: `backend/app/modules/kg/ontology.py`

- [ ] **Step 1: Update base.py**

```python
# base.py:85-100
# BEFORE -> AFTER
# self._add_parcels(bundle.polygons.landuse_current)
# -> self._add_parcels(bundle.polygons.get("landuse_current"))
# self.add_roads(bundle.lines.roads_current)
# -> self.add_roads(bundle.lines.get("roads_current"))
# self._add_water_bodies(bundle.polygons.water_bodies, ...)
# -> self._add_water_bodies(bundle.polygons.get("water_bodies"), ...)
# self._add_facilities_from_typed(bundle.points.facilities_current)
# -> self._add_facilities_from_typed(bundle.points.get("facilities_current"))
# self._add_buildings(getattr(bundle.points, 'buildings', []))
# -> self._add_buildings(bundle.points.get("buildings"))
```

- [ ] **Step 2: Update layer1.py**

```python
# layer1.py:1025
# BEFORE: getattr(polygons_layer, "admin_areas", [])
# AFTER:  polygons_layer.get("admin_areas") if hasattr(polygons_layer, "get") else []

# layer1.py:511
# BEFORE: getattr(polygons_layer, "planning_scope", [])
# AFTER:  polygons_layer.get("planning_scope") if hasattr(polygons_layer, "get") else []

# layer1.py:971
# BEFORE: getattr(lines_layer, "contour_lines", [])
# AFTER:  lines_layer.get("contour_lines") if hasattr(lines_layer, "get") else []
```

- [ ] **Step 3: Update kg/manager.py**

```python
# manager.py:186
# BEFORE: parcels = bundle.polygons.landuse_current if bundle else landuse_geojson
# AFTER:  parcels = bundle.polygons.get("landuse_current") if bundle else landuse_geojson
```

- [ ] **Step 4: Update kg/ontology.py**

```python
# ontology.py:261-262 — access pattern becomes:
# BEFORE: entry.ingest_port
# AFTER:  entry.ingest.adapter if entry.ingest else None
```

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests/unit/ -v --tb=short -q -x`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/kg/builder/base.py
git add backend/app/modules/kg/builder/layer1.py
git add backend/app/modules/kg/manager.py
git add backend/app/modules/kg/ontology.py
git commit -m "feat(phase3): kg/builder uses .get() instead of direct field access"
```

---

### Task 7: agent/ + tools/gis/ + api/ 模块更新

**Files:**
- Modify: `backend/app/agent/graph.py` (~5 lines)
- Modify: `backend/app/agent/gis/layout_pipeline.py` (~4 lines)
- Modify: `backend/app/agent/gis/execute/agent.py` (~2 lines)
- Modify: `backend/app/tools/gis_data/fetch.py` (~6 lines)
- Modify: `backend/app/tools/gis/_analytics/coverage.py` (~4 lines)
- Modify: `backend/app/api/session_routes.py` (~2 lines)

- [ ] **Step 1: Update agent/graph.py**

```python
# graph.py:266-275
# BEFORE: bundle.polygons.admin_areas.append(feat)
#         bundle.lines.inferred.append(feat)
#         bundle.points.inferred.append(feat)
#         bundle.polygons.water_bodies.append(feat)
# AFTER:  bundle.add(feat)
```

- [ ] **Step 2: Update agent/gis/layout_pipeline.py**

```python
# layout_pipeline.py:43-48
# BEFORE: len(bundle.lines.roads_current)
#         len(bundle.points.annotations_current)
# AFTER:  len(bundle.lines.get("roads_current"))
#         len(bundle.points.get("annotations_current"))
```

- [ ] **Step 3: Update agent/gis/execute/agent.py**

```python
# execute/agent.py:71
# BEFORE: gis_bundle.polygons.landuse_current or gis_bundle.polygons.landuse_planned
# AFTER:  gis_bundle.polygons.get("landuse_current") or gis_bundle.polygons.get("landuse_planned")
```

- [ ] **Step 4: Update tools/gis_data/fetch.py**

```python
# fetch.py:33-43
# BEFORE -> AFTER
# bundle.polygons.landuse_current -> bundle.polygons.get("landuse_current")
# bundle.polygons.landuse_planned -> bundle.polygons.get("landuse_planned")
# bundle.lines.roads_current -> bundle.lines.get("roads_current")
# bundle.points.annotations_current -> bundle.points.get("annotations_current")
# bundle.lines.roads_planned -> bundle.lines.get("roads_planned")
```

- [ ] **Step 5: Update tools/gis/_analytics/coverage.py**

```python
# coverage.py:52-55
# BEFORE -> AFTER
# bundle.polygons.landuse_current -> bundle.polygons.get("landuse_current")
# bundle.polygons.landuse_planned -> bundle.polygons.get("landuse_planned")
# bundle.lines.roads_current -> bundle.lines.get("roads_current")
# bundle.lines.roads_planned -> bundle.lines.get("roads_planned")
```

- [ ] **Step 6: Update api/session_routes.py**

`bundle.boundary` — property stays, no change needed.

- [ ] **Step 7: Run all tests**

Run: `python -m pytest tests/unit/ -v --tb=short -q -x`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/agent/graph.py
git add backend/app/agent/gis/layout_pipeline.py
git add backend/app/agent/gis/execute/agent.py
git add backend/app/tools/gis_data/fetch.py
git add backend/app/tools/gis/_analytics/coverage.py
git commit -m "feat(phase3): agent/tools/api uses .get() instead of direct field access"
```

---

### Task 8: 最终验证

- [ ] **Step 1: Run all unit tests**

Run: `python -m pytest tests/unit/ -v --tb=short -q`
Expected: 170+ PASS (35 new tests + 135+ existing)

- [ ] **Step 2: Run all integration tests**

Run: `python -m pytest tests/ -v --tb=short -q -x`
Expected: All PASS

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat(phase3+4): complete registry extension + dynamic LayerGroup + bundle.add()"
```