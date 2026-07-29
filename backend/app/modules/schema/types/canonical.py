from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CRS(str, Enum):
    WGS84 = "EPSG:4326"
    CGCS2000 = "EPSG:4490"
    GCJ02 = "GCJ02"


class BBox(BaseModel):
    west: float
    south: float
    east: float
    north: float
    crs: str = Field(default="EPSG:4326", frozen=True)

    @property
    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.west, self.south, self.east, self.north)

    @property
    def center_lon(self) -> float:
        return (self.west + self.east) / 2.0

    @property
    def center_lat(self) -> float:
        return (self.south + self.north) / 2.0

    def is_valid(self) -> bool:
        return (
            -180.0 <= self.west <= 180.0
            and -180.0 <= self.east <= 180.0
            and -90.0 <= self.south <= 90.0
            and -90.0 <= self.north <= 90.0
            and self.west < self.east
            and self.south < self.north
        )


def _spatial_feature_to_geojson(feat: Any) -> dict:
    if feat is None:
        return {"type": "Feature", "geometry": {}, "properties": {}}
    if isinstance(feat, dict):
        return feat
    if hasattr(feat, "model_dump"):
        d = feat.model_dump()
        return {
            "type": "Feature",
            "geometry": d.get("geometry", {}),
            "properties": {k: v for k, v in d.items() if k != "geometry"},
        }
    return {"type": "Feature", "geometry": {}, "properties": {}}


def _features_to_fc(features: List[Any]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [_spatial_feature_to_geojson(f) for f in features if f is not None],
    }


def _bundle_key_for(feature: Any) -> str:
    from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY

    lt = feature.layer_type
    entry = GIS_LAYER_REGISTRY.get(lt)
    if entry and entry.bundle_target:
        return entry.bundle_target.key
    return "inferred"


def _geometry_group_for(feature: Any) -> str:
    from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY

    lt = feature.layer_type
    entry = GIS_LAYER_REGISTRY.get(lt)
    if entry and entry.bundle_target:
        return entry.bundle_target.group
    geom = feature.geometry
    gtype = geom.get("type", "") if isinstance(geom, dict) else ""
    if gtype in ("Point", "MultiPoint"):
        return "points"
    elif gtype in ("LineString", "MultiLineString"):
        return "lines"
    elif gtype in ("Polygon", "MultiPolygon"):
        return "polygons"
    return "polygons"


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

    def set(self, key: str, features: List[Any]) -> None:
        self._layers[key] = features

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


class RasterLayerGroup(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dem: Any = None
    dom: Any = None
    slope: Any = None
    aspect: Any = None
    suitability: Any = None

    @property
    def all_rasters(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for field_name in ("dem", "dom", "slope", "aspect", "suitability"):
            val = getattr(self, field_name)
            if val is not None:
                result[field_name] = val
        return result

    def has_elevation_data(self) -> bool:
        return self.dem is not None


class TableLayerGroup(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    population: Any = None
    construction_projects: Any = None
    control_rules: Any = None
    planning_indicators: Any = None
    land_use_structure: Any = None

    @property
    def all_tables(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for field_name in ("population", "construction_projects", "control_rules",
                           "planning_indicators", "land_use_structure"):
            val = getattr(self, field_name)
            if val is not None:
                result[field_name] = val
        return result


class DocumentGroup(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    planning_texts: List[Any] = Field(default_factory=list)
    l3_reports: List[Any] = Field(default_factory=list)


class VillageMetadata(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    village_name: str = ""
    bbox_wgs84: Optional[BBox] = None
    crs: str = "EPSG:4326"
    provider_sources: List[str] = Field(default_factory=list)
    crs_warnings: List[str] = Field(default_factory=list)


class VillageBundle(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    village_name: str
    points: PointLayerGroup = Field(default_factory=PointLayerGroup)
    lines: LineLayerGroup = Field(default_factory=LineLayerGroup)
    polygons: PolygonLayerGroup = Field(default_factory=PolygonLayerGroup)
    rasters: RasterLayerGroup = Field(default_factory=RasterLayerGroup)
    tables: TableLayerGroup = Field(default_factory=TableLayerGroup)
    documents: DocumentGroup = Field(default_factory=DocumentGroup)
    metadata: VillageMetadata = Field(default_factory=VillageMetadata)
    standard_version: str = "4.4"

    def __init__(self, **data):
        super().__init__(**data)
        object.__setattr__(self, "_bsm_counter", {})

    def add(self, feature: Any) -> None:
        self._assign_bsm(feature)
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

    def _resolve_village_code(self, feature: Any) -> str:
        """从要素属性中提取 12 位行政村行政区划码。"""
        if self._bsm_counter:
            return next(iter(self._bsm_counter))
        props = getattr(feature, "properties", {}) or {}
        xzqhdm = str(props.get("XZQHDM", "") or "").strip()
        if len(xzqhdm) == 12 and xzqhdm.isdigit():
            return xzqhdm
        bsm = str(getattr(feature, "bsm", "") or "").strip()
        if len(bsm) == 20 and bsm.isdigit():
            return bsm[:12]
        return "441426110202"

    def _assign_bsm(self, feature: Any) -> None:
        """为要素分配 20 位标准 BSM（12 位村码 + 8 位顺序号）。"""
        bsm = str(getattr(feature, "bsm", "") or "").strip()
        if len(bsm) == 20 and bsm.isdigit():
            return
        village_code = self._resolve_village_code(feature)
        seq = self._bsm_counter.get(village_code, 1)
        self._bsm_counter[village_code] = seq + 1
        feature.bsm = f"{village_code}{seq:08d}"

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
            p.area_sqm / 10000.0
            for p in self.polygons.get("landuse_current") + self.polygons.get("landuse_planned")
        )

    def get_parcels_by_dlbm(self, dlbm: str) -> List[Any]:
        all_parcels = self.polygons.get("landuse_current") + self.polygons.get("landuse_planned")
        return [p for p in all_parcels if p.dlbm == dlbm]

    def get_parcels_by_zone(self, zone_type: str) -> List[Any]:
        all_parcels = self.polygons.get("landuse_current") + self.polygons.get("landuse_planned")
        return [p for p in all_parcels if p.zone_type == zone_type]

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


class ProjectMetadata(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    project_id: str = ""
    bbox_wgs84: Optional[BBox] = None
    crs: str = "EPSG:4326"
    villages: List[str] = Field(default_factory=list)


class ProjectDataView(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    project_id: str
    villages: Dict[str, VillageBundle] = Field(default_factory=dict)
    cross_village_layers: Dict[str, List[Any]] = Field(default_factory=dict)
    rasters: Dict[str, Any] = Field(default_factory=dict)
    extra_rasters: Dict[str, Any] = Field(default_factory=dict)
    tables: Dict[str, Any] = Field(default_factory=dict)
    documents: Dict[str, Any] = Field(default_factory=dict)
    project_metadata: ProjectMetadata = Field(default_factory=ProjectMetadata)

    def get_village(self, village_name: str) -> Optional[VillageBundle]:
        return self.villages.get(village_name)

    @property
    def layer_tree(self) -> List[Dict[str, Any]]:
        return []


__all__ = [
    "CRS",
    "BBox",
    "PointLayerGroup",
    "LineLayerGroup",
    "PolygonLayerGroup",
    "RasterLayerGroup",
    "TableLayerGroup",
    "DocumentGroup",
    "VillageMetadata",
    "VillageBundle",
    "ProjectMetadata",
    "ProjectDataView",
    "_spatial_feature_to_geojson",
    "_features_to_fc",
]