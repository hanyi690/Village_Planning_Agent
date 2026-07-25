"""Spatial cognition contracts — ContextBlock + SpatialCognitiveUnit hierarchy.

[v4.4] SpatialCognitiveUnit 三层抽象统一了所有空间认知元素：
  - 认知锚点（FacilityAnchor, NaturalVillageAnchor, ...）
  - 规划意图（ZoneTarget, FacilityTarget, RoadTarget）
  - 规划状态（PlannedState, PlannedParcelEntry）

与 Schema 层 SpatialFeature → PointFeature/LineFeature/PolygonFeature 对齐。
下游可按形态统一遍历（isinstance 分发），按语义具体处理。

Produced by: spatial_ops.compute_context_blocks(VillageBundle)
Consumed by: PARSE Agent, LAYOUT Pipeline, KG builder, prompt formatters
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple


# ── L0: SpatialCognitiveUnit — 跨层共通基类 ──


@dataclass
class SpatialCognitiveUnit:
    """Base class for ALL spatial cognitive elements.

    Mirrors Schema's SpatialFeature at the cognition/intent layer.
    Three geometry_type branches: point, line, polygon.
    """
    entity_uri: str = ""           # KG entity URI
    geometry_type: str = ""        # point / line / polygon
    name: str = ""
    confidence: float = 1.0
    source: str = ""


# ── L1: 形态化认知子类 ──


@dataclass
class PointBasedCognition(SpatialCognitiveUnit):
    geometry_type: str = "point"
    center: Tuple[float, float] = (0.0, 0.0)


@dataclass
class LineBasedCognition(SpatialCognitiveUnit):
    geometry_type: str = "line"
    path: List[Tuple[float, float]] = field(default_factory=list)
    length_m: float = 0.0


@dataclass
class PolygonBasedCognition(SpatialCognitiveUnit):
    geometry_type: str = "polygon"
    area_ha: float = 0.0
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


# ── L2: 具体语义子类（认知锚点） ──


@dataclass
class FacilityAnchor(PointBasedCognition):
    """Facility spatial anchor — precise location from annotation data."""
    facility_type: str = ""        # 公共服务, 教育, 文化, 体育
    category: str = ""             # 现状设施点 / 规划设施点


@dataclass
class TerrainSample(PointBasedCognition):
    """Elevation/slope sample point (P2 reserved)."""
    elevation_m: float = 0.0
    slope_degree: float = 0.0


@dataclass
class RoadAnchor(LineBasedCognition):
    """Road spatial anchor — from typed CurrentRoad."""
    road_level: str = ""           # 主干道, 次干道, 支路, 村道
    width_m: float = 0.0


@dataclass
class AxisAnchor(LineBasedCognition):
    """Development axis anchor — from PARSE intent."""
    connects: List[str] = field(default_factory=list)


@dataclass
class NaturalVillageAnchor(PolygonBasedCognition):
    """Natural village spatial anchor — clustered from residential parcels."""
    center: Tuple[float, float] = (0.0, 0.0)
    parcel_ids: List[str] = field(default_factory=list)
    dominant_landuse: str = ""
    adjacent_to: List[str] = field(default_factory=list)


@dataclass
class ConstraintZoneAnchor(PolygonBasedCognition):
    """Protection zone anchor — from CONSTRAINTS ContextBlock."""
    zone_type: str = ""            # farmland_protection, ecological_redline
    rule: str = ""                 # 禁止建设, 限制建设
    overlaps_with: List[str] = field(default_factory=list)


# ── L2: 规划意图子类（SpatialIntentUnit） ──


@dataclass
class LocationConstraint:
    """Spatial location constraint — replaces fuzzy string hints."""
    constraint_type: str = "near_entity"  # near_entity, within_zone, outside_zone, along_axis
    entity_uri: str = ""
    max_distance_m: float = 500


@dataclass
class SpatialIntentUnit(SpatialCognitiveUnit):
    """Base class for planning intent units — Layer 3."""
    priority: int = 1              # 1=mandatory, 2=expected, 3=optional
    constraints: List[LocationConstraint] = field(default_factory=list)


@dataclass
class ZoneTarget(SpatialIntentUnit):
    """Planning zone target — maps to MIP variables."""
    geometry_type: str = "polygon"
    land_use_code: str = ""
    target_area_ha: float = 0.0
    min_area_ha: float = 0.0
    max_area_ha: float = float("inf")
    adjacency_preference: Optional[Dict[str, float]] = field(default=None)


@dataclass
class FacilityTarget(SpatialIntentUnit):
    """Facility placement target — consumed by constraint satisfaction."""
    geometry_type: str = "point"
    facility_type: str = ""
    min_area_sqm: float = 0.0


@dataclass
class RoadTarget(SpatialIntentUnit):
    """Road planning target — programmatic generation parameters."""
    geometry_type: str = "line"
    road_level: str = ""
    width_m: float = 0.0
    start_entity_uri: str = ""
    end_entity_uri: str = ""


# ── ContextBlock（复合形态） ──


class ContextBlockType(str, Enum):
    """Type discriminator for spatial cognition cards."""
    VILLAGE_META = "village_meta"
    LANDUSE_DIST = "landuse_dist"
    NATURAL_VILLAGES = "natural_villages"
    SPATIAL_RELATIONS = "spatial_relations"
    CONSTRAINTS = "constraints"
    FACILITIES = "facilities"
    TERRAIN = "terrain"
    ZONE_ADJACENCY = "zone_adjacency"
    PLANNED_STATE = "planned_state"


@dataclass
class ContextBlock(SpatialCognitiveUnit):
    """Self-describing spatial cognition card — composite morphology.

    Contains typed units (e.g. FACILITIES block contains List[FacilityAnchor])
    for downstream isinstance-based dispatch.
    """
    block_type: ContextBlockType = ContextBlockType.VILLAGE_META
    title: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    priority: int = 50
    geometry_type: str = "composite"
    units: List[SpatialCognitiveUnit] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [f"## {self.title}"]
        for k, v in self.data.items():
            if isinstance(v, list):
                lines.append(f"- **{k}**:")
                for item in v:
                    if isinstance(item, dict):
                        lines.append(f"  - {item.get('name', item)}")
                    else:
                        lines.append(f"  - {item}")
            else:
                lines.append(f"- **{k}**: {v}")
        return "\n".join(lines)


# ── Block-internal structured sub-types ──


@dataclass
class LanduseEntry:
    """Single land-use category entry in spatial context."""
    dlbm: str = ""
    name: str = ""
    count: int = 0
    area_ha: float = 0.0
    zone_type: str = ""
    planning_zone: str = ""


@dataclass
class ConstraintSummary:
    """Spatial summary of protection zones — PARSE uses this to structure constraints."""
    zone_type: str = ""
    rule: str = ""
    area_ha: Optional[float] = None
    geometry_type: Optional[str] = None
    overlaps_with: List[str] = field(default_factory=list)


@dataclass
class SpatialRelation:
    """Spatial relation triple computed from GIS geometry."""
    subject: str = ""
    relation: str = "adjacent_to"
    object: str = ""
    confidence: float = 1.0
    source: str = "geometry_computed"


@dataclass
class TerrainProfile:
    """Terrain analysis summary — compact digest for LLM."""
    slope_area_pct: Dict[str, float] = field(default_factory=dict)
    aspect_area_pct: Dict[str, float] = field(default_factory=dict)
    suitability_area_pct: Dict[str, float] = field(default_factory=dict)


# ── PlanIntent（Layer 3） ──


@dataclass
class PlanningConstraint:
    """Hard or soft constraint with source traceability."""
    constraint_type: str = "hard"  # hard, soft
    rule: str = ""
    weight: float = 1.0
    source: str = ""


@dataclass
class PlanIntent:
    """Unified planning intent — targets are typed by SpatialIntentUnit subclasses.

    targets 统一管理 ZoneTarget, FacilityTarget, RoadTarget 等所有意图类型。
    新增意图类型只需增加 SpatialIntentUnit 子类，无需改动 PlanIntent 自身。
    """
    targets: List[SpatialIntentUnit] = field(default_factory=list)
    hard_constraints: List[PlanningConstraint] = field(default_factory=list)
    soft_constraints: List[PlanningConstraint] = field(default_factory=list)
    source_text_refs: List[str] = field(default_factory=list)


# ── Layer 4: PlanBlock (incremental change-set) ──
#
# PlanBlock is NOT a SpatialCognitiveUnit - it's a "change operation set".
# Only records CHANGES from L1; unchanged parcels have no L4 triples.
# Query semantics: effective_state(parcel) = L1(parcel) + L4_delta(parcel)
#
# Actions for ParcelChange:
#   reclassify - same bsm as L1, only land_use changed
#   modify     - same bsm as L1, area/geometry adjusted
#   split      - NEW bsm(s) for sub-parcels, derived_from_bsms = [parent_bsm]
#   merge      - NEW bsm for merged parcel, derived_from_bsms = [bsm_1, bsm_2, ...]


@dataclass
class ParcelChange:
    """Single parcel planning change (delta entry, not full copy)."""
    bsm: str
    action: str = "modify"
    derived_from_bsms: List[str] = field(default_factory=list)
    new_planning_land_use: str = ""
    new_area_ha: Optional[float] = None
    new_zone_type: str = ""


@dataclass
class FacilityChange:
    """Facility planning change."""
    name: str
    action: str = "new"
    facility_type: str = ""
    area_sqm: Optional[float] = None
    center: Optional[Tuple[float, float]] = None
    derived_from_name: str = ""


@dataclass
class RoadChange:
    """Road planning change."""
    name: str
    action: str = "new"
    road_level: str = ""
    width_m: float = 0.0
    path: Optional[List[Tuple[float, float]]] = None
    derived_from_name: str = ""


@dataclass
class SettlementChange:
    """Natural village settlement planning change."""
    settlement_name: str
    action: str = "retain"
    new_population: Optional[int] = None
    new_area_ha: Optional[float] = None
    target_location: Optional[Tuple[float, float]] = None
    merge_into: str = ""


@dataclass
class PlanBlock:
    """Planning change-set (delta) - Layer 4 container.

    Unlike a full-mirror PlannedState, PlanBlock only stores CHANGES.
    Unchanged parcels have no L4 triples; query falls back to L1.

    effective_state(parcel) = L1(parcel) + L4_delta(parcel)

    For split: multiple ParcelChange entries, each with a new bsm and
        derived_from_bsms = [parent_bsm].
    For merge: one ParcelChange with a new bsm and derived_from_bsms
        = [bsm_1, bsm_2, ...].
    """
    version: str = "v1"
    parcel_changes: List[ParcelChange] = field(default_factory=list)
    settlement_changes: List[SettlementChange] = field(default_factory=list)
    facility_changes: List[FacilityChange] = field(default_factory=list)
    road_changes: List[RoadChange] = field(default_factory=list)
    summary_metrics: Dict[str, float] = field(default_factory=dict)
    source: str = ""


__all__ = [
    # L0 base
    "SpatialCognitiveUnit",
    # L1 morphology
    "PointBasedCognition",
    "LineBasedCognition",
    "PolygonBasedCognition",
    # L2 cognition anchors
    "FacilityAnchor",
    "TerrainSample",
    "RoadAnchor",
    "AxisAnchor",
    "NaturalVillageAnchor",
    "ConstraintZoneAnchor",
    "ConstraintSummary",
    # L2 intent units
    "LocationConstraint",
    "SpatialIntentUnit",
    "ZoneTarget",
    "FacilityTarget",
    "RoadTarget",
    # ContextBlock
    "ContextBlockType",
    "ContextBlock",
    "LanduseEntry",
    "SpatialRelation",
    "TerrainProfile",
    # PlanIntent
    "PlanningConstraint",
    "PlanIntent",
    # PlanBlock (Layer 4 incremental change-set)
    "ParcelChange",
    "FacilityChange",
    "RoadChange",
    "SettlementChange",
    "PlanBlock",
]