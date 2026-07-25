"""Canonical GIS data models — the single normative representation for all GIS data.

[v4.3] Morphology-first VillageBundle replaces flat GISDataBundle.
All data entering the agent pipeline MUST be normalized to typed dataclass models.
Downstream consumers access data through morphology groups (points/lines/polygons/rasters).

CRS Policy: All coordinates in WGS84 (EPSG:4326). Metric operations use
crs_engine.get_metric_crs() for on-demand CGCS2000 projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CRS(str, Enum):
    """Supported coordinate reference systems."""
    WGS84 = "EPSG:4326"
    CGCS2000 = "EPSG:4490"
    GCJ02 = "GCJ02"


class BBox(BaseModel):
    """Canonical bounding box — always WGS84 (EPSG:4326).

    Order: (west, south, east, north) matching OSMnx 2.x bbox convention.
    """

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


# ── GeoJSON serialization helpers ──

def _spatial_feature_to_geojson(feat: Any) -> dict:
    """Convert a typed spatial feature to a GeoJSON Feature dict."""
    if feat is None:
        return {"type": "Feature", "geometry": {}, "properties": {}}
    if isinstance(feat, dict):
        return feat
    if hasattr(feat, "geometry") and isinstance(getattr(feat, "geometry", None), dict):
        geom = feat.geometry
        props = {}
        for k, v in feat.__dict__.items():
            if k not in ("geometry", "_raw"):
                props[k] = v
        return {"type": "Feature", "geometry": geom, "properties": props}
    if hasattr(feat, "model_dump"):
        d = feat.model_dump()
        return {
            "type": "Feature",
            "geometry": d.get("geometry", {}),
            "properties": {k: v for k, v in d.items() if k != "geometry"},
        }
    return {"type": "Feature", "geometry": {}, "properties": {}}


def _features_to_fc(features: List[Any]) -> dict:
    """Convert a list of typed features to a GeoJSON FeatureCollection dict."""
    return {
        "type": "FeatureCollection",
        "features": [_spatial_feature_to_geojson(f) for f in features if f is not None],
    }


# ── [v4.3] Morphology Layer Groups ──


@dataclass
class PointLayerGroup:
    """All PointFeature subclass features, grouped by semantic role.

    Annotations are stored here (morphologically they are points) but
    excluded from all_features (semantically they are expression elements, not spatial entities).
    """

    # Facilities & buildings
    facilities_current: List[Any] = field(default_factory=list)   # List[CurrentFacility]
    facilities_planned: List[Any] = field(default_factory=list)    # List[PlannedFacility]
    buildings: List[Any] = field(default_factory=list)             # List[CurrentBuilding]

    # Terrain
    elevation_points: List[Any] = field(default_factory=list)      # List[ElevationPoint]

    # Hazard
    hazard_points: List[Any] = field(default_factory=list)         # List[GeologicalHazardPoint]

    # Annotations (expression elements, not spatial entities — excluded from all_features)
    annotations_current: List[Any] = field(default_factory=list)   # List[CurrentAnnotation]
    annotations_planned: List[Any] = field(default_factory=list)   # List[PlannedAnnotation]

    # Inferred layers (dynamic models, PointFeature subclass but unknown semantic type)
    inferred: List[Any] = field(default_factory=list)              # List[PointFeature]

    @property
    def all_features(self) -> List[Any]:
        """All point features excluding annotations (expression elements)."""
        return [
            *self.facilities_current,
            *self.facilities_planned,
            *self.buildings,
            *self.elevation_points,
            *self.hazard_points,
            *self.inferred,
        ]

    @property
    def facilities(self) -> List[Any]:
        """All facilities (current + planned)."""
        return [*self.facilities_current, *self.facilities_planned]


@dataclass
class LineLayerGroup:
    """All LineFeature subclass features."""

    roads_current: List[Any] = field(default_factory=list)         # List[CurrentRoad]
    roads_planned: List[Any] = field(default_factory=list)         # List[PlannedRoad]
    contour_lines: List[Any] = field(default_factory=list)         # List[ContourLine]
    admin_boundaries: List[Any] = field(default_factory=list)      # List[AdminBoundaryLine]

    # Inferred layers
    inferred: List[Any] = field(default_factory=list)              # List[LineFeature]

    @property
    def all_features(self) -> List[Any]:
        return [
            *self.roads_current,
            *self.roads_planned,
            *self.contour_lines,
            *self.admin_boundaries,
            *self.inferred,
        ]

    @property
    def roads(self) -> List[Any]:
        """All roads (current + planned)."""
        return [*self.roads_current, *self.roads_planned]


@dataclass
class PolygonLayerGroup:
    """All PolygonFeature subclass features, grouped by semantic role."""

    # Land use parcels
    landuse_current: List[Any] = field(default_factory=list)       # List[CurrentLandUseParcel]
    landuse_planned: List[Any] = field(default_factory=list)       # List[PlannedLandUseParcel]

    # Protection & control (constraint polygons — cannot be occupied in spatial planning)
    farmland_protection: List[Any] = field(default_factory=list)   # List[FarmlandProtection]
    ecological_redline: List[Any] = field(default_factory=list)    # List[EcologicalRedline]
    historical_protection: List[Any] = field(default_factory=list) # List[HistoricalProtection]
    cultivated_land_target: List[Any] = field(default_factory=list) # List[CultivatedLandTarget]
    urban_dev_boundary: List[Any] = field(default_factory=list)    # List[UrbanDevBoundary]
    village_dev_boundary: List[Any] = field(default_factory=list)  # List[VillageDevBoundary]
    hazard_control_lines: List[Any] = field(default_factory=list)  # List[HazardControlLine]
    flood_control_lines: List[Any] = field(default_factory=list)   # List[FloodControlLine]
    construction_zone: List[Any] = field(default_factory=list)     # List[ConditionalConstructionZone]

    # Zoning & administration
    admin_areas: List[Any] = field(default_factory=list)           # List[AdminArea]
    planning_scope: List[Any] = field(default_factory=list)        # List[PlanningScope]
    land_use_zones: List[Any] = field(default_factory=list)        # List[LandUseZone]
    construction_ctrl_zones: List[Any] = field(default_factory=list) # List[ConstructionCtrlZone]
    three_zones: List[Any] = field(default_factory=list)           # List[ThreeZoneItem]

    # Natural features
    water_bodies: List[Any] = field(default_factory=list)          # List[WaterFeature]
    soil_types: List[Any] = field(default_factory=list)            # List[SoilType]
    soil_erosions: List[Any] = field(default_factory=list)         # List[SoilErosion]
    watersheds: List[Any] = field(default_factory=list)            # List[Watershed]
    nature_reserves: List[Any] = field(default_factory=list)       # List[NatureReserve]
    hydrogeology_zones: List[Any] = field(default_factory=list)    # List[HydrogeologyZone]

    # Inferred layers
    inferred: List[Any] = field(default_factory=list)              # List[PolygonFeature]

    @property
    def constraint_polygons(self) -> List[Any]:
        """All constraint/protection polygons — areas that cannot be occupied."""
        return [
            *self.farmland_protection,
            *self.ecological_redline,
            *self.historical_protection,
            *self.cultivated_land_target,
            *self.hazard_control_lines,
            *self.flood_control_lines,
            *self.nature_reserves,
        ]

    @property
    def all_features(self) -> List[Any]:
        """All polygon features."""
        return [
            *self.landuse_current,
            *self.landuse_planned,
            *self.constraint_polygons,
            *self.urban_dev_boundary,
            *self.village_dev_boundary,
            *self.construction_zone,
            *self.admin_areas,
            *self.planning_scope,
            *self.land_use_zones,
            *self.construction_ctrl_zones,
            *self.three_zones,
            *self.water_bodies,
            *self.soil_types,
            *self.soil_erosions,
            *self.watersheds,
            *self.hydrogeology_zones,
            *self.inferred,
        ]

    @property
    def parcels(self) -> List[Any]:
        """All land use parcels (current + planned)."""
        return [*self.landuse_current, *self.landuse_planned]


@dataclass
class RasterLayerGroup:
    """All raster data, organized by semantic role."""

    dem: Any = None                   # Optional[DEMInput]
    dom: Any = None                   # Optional[DOMInput]
    slope: Any = None                 # Optional[SlopeRaster]
    aspect: Any = None                # Optional[AspectRaster]
    suitability: Any = None           # Optional[SuitabilityRaster]

    @property
    def all_rasters(self) -> Dict[str, Any]:
        """All available rasters keyed by field name."""
        result: Dict[str, Any] = {}
        for field_name in ("dem", "dom", "slope", "aspect", "suitability"):
            val = getattr(self, field_name)
            if val is not None:
                result[field_name] = val
        return result

    def has_elevation_data(self) -> bool:
        return self.dem is not None


@dataclass
class TableLayerGroup:
    """All tabular data (non-spatial structured rows/columns)."""

    population: Any = None                       # Optional[PopulationTable]
    construction_projects: Any = None            # Optional[ConstructionProjectTable]
    control_rules: Any = None                    # Optional[ControlRuleTable]
    planning_indicators: Any = None              # Optional[PlanningIndicatorTable]
    land_use_structure: Any = None               # Optional[LandUseStructureTable]

    @property
    def all_tables(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for field_name in ("population", "construction_projects", "control_rules",
                           "planning_indicators", "land_use_structure"):
            val = getattr(self, field_name)
            if val is not None:
                result[field_name] = val
        return result


@dataclass
class DocumentGroup:
    """All document data (semi-structured text)."""

    planning_texts: List[Any] = field(default_factory=list)   # List[PlanningText]
    l3_reports: List[Any] = field(default_factory=list)       # List[L3Report]


# ── [v4.3] VillageBundle — the sole village data container ──


@dataclass
class VillageMetadata:
    """Metadata for a single village bundle."""

    village_name: str = ""
    bbox_wgs84: Optional[BBox] = None
    crs: str = "EPSG:4326"
    provider_sources: List[str] = field(default_factory=list)
    crs_warnings: List[str] = field(default_factory=list)


@dataclass
class VillageBundle:
    """Single village data bundle — morphology-first organization.

    [v4.3] Replaces flat GISDataBundle. All features are organized by geometry
    morphology (points/lines/polygons/rasters) rather than by file source.
    Downstream consumers access features through morphology groups directly.
    """

    village_name: str

    # Four-morphology views
    points: PointLayerGroup = field(default_factory=PointLayerGroup)
    lines: LineLayerGroup = field(default_factory=LineLayerGroup)
    polygons: PolygonLayerGroup = field(default_factory=PolygonLayerGroup)
    rasters: RasterLayerGroup = field(default_factory=RasterLayerGroup)

    # Table & document (v4.3 skeleton, to be fleshed out)
    tables: TableLayerGroup = field(default_factory=TableLayerGroup)
    documents: DocumentGroup = field(default_factory=DocumentGroup)

    # Metadata
    metadata: VillageMetadata = field(default_factory=VillageMetadata)
    standard_version: str = "4.3"

    # ── Convenience properties ──

    @property
    def boundary(self) -> Any:
        """Village boundary — derived from admin_areas or planning_scope."""
        if self.polygons.admin_areas:
            return self.polygons.admin_areas[0]
        if self.polygons.planning_scope:
            return self.polygons.planning_scope[0]
        return None

    @property
    def all_features(self) -> List[Any]:
        """All spatial features across all morphologies (excluding annotations)."""
        return [
            *self.points.all_features,
            *self.lines.all_features,
            *self.polygons.all_features,
        ]

    @property
    def parcel_count(self) -> int:
        return len(self.polygons.landuse_current) + len(self.polygons.landuse_planned)

    @property
    def total_area_ha(self) -> float:
        return sum(
            getattr(p, "area_ha", 0.0)
            for p in self.polygons.landuse_current + self.polygons.landuse_planned
        )

    def get_parcels_by_dlbm(self, dlbm: str) -> List[Any]:
        all_parcels = self.polygons.landuse_current + self.polygons.landuse_planned
        return [p for p in all_parcels if getattr(p, "dlbm", "") == dlbm]

    def get_parcels_by_zone(self, zone_type: str) -> List[Any]:
        all_parcels = self.polygons.landuse_current + self.polygons.landuse_planned
        return [p for p in all_parcels if getattr(p, "zone_type", "") == zone_type]

    def is_complete(self) -> bool:
        return self.boundary is not None and self.parcel_count > 0

    def to_geojson_dict(self) -> Dict[str, Any]:
        """Convert typed bundle to raw GeoJSON dict (legacy bridge).

        Produces keys like 'landuse_current_geojson', 'boundary_geojson',
        'farmland_protection_geojson', etc.

        [v4.3] Preferred path: compute_context_blocks(bundle) directly
        consumes typed morphology groups. This method remains for renderer/
        export consumers that still need raw GeoJSON.
        """
        gis_data: Dict[str, Any] = {}

        # Boundary
        if self.boundary is not None:
            gis_data["boundary_geojson"] = _features_to_fc([self.boundary])

        # Current landuse
        if self.polygons.landuse_current:
            gis_data["landuse_current_geojson"] = _features_to_fc(self.polygons.landuse_current)

        # Planned landuse
        if self.polygons.landuse_planned:
            gis_data["landuse_planned_geojson"] = _features_to_fc(self.polygons.landuse_planned)

        # Roads
        all_roads = self.lines.roads_current + self.lines.roads_planned
        if all_roads:
            gis_data["road_geojson"] = _features_to_fc(all_roads)

        # Water bodies
        if self.polygons.water_bodies:
            gis_data["water_geojson"] = _features_to_fc(self.polygons.water_bodies)

        # Annotations
        all_annotations = self.points.annotations_current + self.points.annotations_planned
        if all_annotations:
            gis_data["annotation_geojson"] = _features_to_fc(all_annotations)

        # Constraint/protection layers
        constraint_map = {
            "farmland_protection": self.polygons.farmland_protection,
            "ecological_protection": self.polygons.ecological_redline,
            "ecological_redline": self.polygons.ecological_redline,
            "historical_protection": self.polygons.historical_protection,
            "construction_zone": self.polygons.construction_zone,
            "geological_hazard_points": self.points.hazard_points,
        }
        for key, features in constraint_map.items():
            if features:
                gis_data[f"{key}_geojson"] = _features_to_fc(features)

        # Metadata
        gis_data["_metadata"] = {
            "village_name": self.metadata.village_name,
            "bbox": self.metadata.bbox_wgs84.as_tuple if self.metadata.bbox_wgs84 else None,
        }

        return gis_data


# ── [v4.1] ProjectDataView (project-level container) ──


@dataclass
class ProjectMetadata:
    """Metadata for a project-level data view."""

    project_id: str = ""
    bbox_wgs84: Optional[BBox] = None
    crs: str = "EPSG:4326"
    villages: List[str] = field(default_factory=list)


@dataclass
class ProjectDataView:
    """Project-level data view — holds multiple villages and shared layers.

    [v4.1] Multi-village + cross-village layers + shared rasters/tables/documents.
    """

    project_id: str
    villages: Dict[str, VillageBundle] = field(default_factory=dict)
    cross_village_layers: Dict[str, List[Any]] = field(default_factory=dict)
    rasters: Dict[str, Any] = field(default_factory=dict)
    extra_rasters: Dict[str, Any] = field(default_factory=dict)
    tables: Dict[str, Any] = field(default_factory=dict)
    documents: Dict[str, Any] = field(default_factory=dict)
    project_metadata: ProjectMetadata = field(default_factory=ProjectMetadata)

    def get_village(self, village_name: str) -> Optional[VillageBundle]:
        return self.villages.get(village_name)

    @property
    def layer_tree(self) -> List[Dict[str, Any]]:
        """Layer tree: list all layers with name/source/geometry_kind/feature_count."""
        return []


__all__ = [
    # Core types
    "CRS",
    "BBox",
    # Morphology groups
    "PointLayerGroup",
    "LineLayerGroup",
    "PolygonLayerGroup",
    "RasterLayerGroup",
    "TableLayerGroup",
    "DocumentGroup",
    # Village
    "VillageMetadata",
    "VillageBundle",
    # Project
    "ProjectMetadata",
    "ProjectDataView",
    # GeoJSON helpers
    "_spatial_feature_to_geojson",
    "_features_to_fc",
]
