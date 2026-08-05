"""PARSE contract schemas — data models shared between PARSE Agent and KG.

These Pydantic models define the data contract between the PARSE Agent
(text-to-intent) and downstream consumers (KG, EXECUTE tools). They are
pure data models with no agent logic, so they live in schema rather than
in the agent package.

This breaks the reverse dependency where KG previously imported
SpatialPlanningIntent from app.agent.select.parse_state.

EXECUTE sub-task field mapping:
  layout:   ZoneTarget.land_use/area_ratio/density/adjacency_rules/vne_code
  facility: FacilityTarget.type/status/direction/location_hint/candidate_bsms/anchor_point
  axis:     AxisTarget.direction/axis_type/label/connects/start_anchor/end_anchor
  road:     RoadTarget.road_level/width_m/connects/start_anchor/end_anchor
  ops:      SpatialOperation.action/target_parcels/spatial_anchor.candidate_parcels

Semantic anchors (human-readable, stored in SemanticMetadata):
  natural_language_description, spatial_hint, reasoning_trace, raw_text
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, computed_field

from .provenance import SemanticMetadata


# ── Zone spatial preference ─────────────────────────────────────────


class SpatialPreference(BaseModel):
    """Zone spatial preference — from PARSE's understanding of planning text.

    Canonical source of spatial preference. ZoneIntent is a derived view
    that maps direction to Direction enum and reference to reference_feature.
    """

    direction: Optional[str] = None
    reference: Optional[str] = None
    reference_feature: Optional[str] = None  # from ZoneIntent.reference_feature


class AdjacencyRules(BaseModel):
    """Zone adjacency rules — from PARSE's understanding of regulations."""

    prefer: List[str] = Field(default_factory=list)
    avoid: List[str] = Field(default_factory=list)


class ZoneTarget(BaseModel):
    """Zone target with controlled vocabulary and spatial preference.

    VNE codes follow 住建部《村庄规划用地分类指南》:
      V=村庄建设用地, N=非村庄建设用地, E=非建设用地
      V1=村民住宅用地, V11=住宅用地, V12=混合式住宅用地, ...

    === 事实(Facts) vs 判断(Judgments) 区分 ===

    land_use (事实): 地类名称，LLM 从文本提取，经 normalize_landuse() 归一化。
      原始文本保留在 raw_term 供审计。

    planning_zone (判断): 规划分区，应由 PARSE/LLM 根据规划意图明确产出。
      例如 "乔木林地" 可以规划为 "林业发展区"(商品林) 或 "生态保护区"(生态林)。
      当 PARSE 未指定时，ConstraintCompiler 使用 LANDUSE_TO_ZONE 启发规则作为 fallback。

    candidate_bsms/bbox (空间接地结果): spatial_ops.grounding 填充的客观计算结果。
    """

    land_use: Optional[str] = None
    raw_term: str = ""                           # 文档原词，留审计
    planning_zone: Optional[str] = None # PARSE 判断，非派生。LLM 决定此地块应属哪个规划分区
    area_ratio: float = 0.0
    area_ha: Optional[float] = None
    dlbm: Optional[str] = None
    vne_code: Optional[str] = None               # e.g. "V11", "V21", "E1"
    spatial_preference: Optional[SpatialPreference] = None
    adjacency_rules: Optional[AdjacencyRules] = None
    density: Literal["high", "medium", "low"] = "medium"
    zone_id: str = ""                             # from ZoneIntent (EXECUTE identifier)
    source_instruction_id: str = ""
    source_report_key: str = ""
    preserve_existing: bool = True                # from ZoneIntent
    # === 空间锚定（spatial_ops.grounding 填充）===
    candidate_bsms: List[str] = Field(default_factory=list)
    candidate_bbox: Optional[Tuple[float, float, float, float]] = None
    excluded_bsms: List[str] = Field(default_factory=list)
    proximity_weights: Dict[str, float] = Field(default_factory=dict)
    # Semantic anchors (human-readable, not stored as RDF)
    semantic: SemanticMetadata = Field(default_factory=SemanticMetadata)

    @computed_field
    @property
    def vne_category(self) -> Optional[str]:
        """Derive VNE major category from code: V/N/E."""
        return self.vne_code[0] if self.vne_code else None


class FacilityTarget(BaseModel):
    """Facility requirement with spatial anchoring.

    candidate_bsms and anchor_point are filled by spatial_ops.grounding post-format.
    direction drives FacilityPlacer's _place_new placement decision.
    SemanticMetadata.spatial_hint retains the original text (e.g. "村北") for traceability.
    """

    type: str = ""
    status: Literal[
        "existing_preserve",
        "planned_new",
        "planned_expand",
        "planned_relocate",
    ] = "existing_preserve"
    location_hint: str = ""
    service_radius: Optional[int] = None
    anchor_village: Optional[str] = None
    source_project_id: str = ""
    source_instruction_id: str = ""
    source_report_key: str = ""
    # === 空间方向（FacilityPlacer 用）===
    direction: str = "center"                # "north"/"south"/"east"/"west"/"center"
    # === 空间锚定（spatial_ops.grounding 填充，具体集合而非文本）===
    candidate_bsms: List[str] = Field(default_factory=list)
    anchor_point: Optional[Tuple[float, float]] = None  # 精确坐标 (lon, lat)
    # Semantic anchors (human-readable, not stored as RDF)
    semantic: SemanticMetadata = Field(default_factory=SemanticMetadata)


class AxisTarget(BaseModel):
    """Development axis with connectivity.

    start_anchor/end_anchor provide precise coordinate anchors for axis line
    generation. corridor_bsms are candidate parcels along the corridor.
    axis_type/label drive AxisBuilder classification.
    SemanticMetadata.natural_language_description retains labels like "南北发展轴".
    """

    reference_feature: str = ""
    connects: List[str] = Field(default_factory=list)
    # === 轴线类型（AxisBuilder 用）===
    direction: str = ""                      # "north-south"/"east-west"/"radial"
    axis_type: str = "primary"              # "primary"/"secondary"/"spatial_control"
    label: str = ""                          # e.g. "南北发展轴"
    source_project_id: str = ""
    source_instruction_id: str = ""
    source_report_key: str = ""
    # === 空间锚定（spatial_ops.grounding 填充）===
    start_anchor: Optional[Tuple[float, float]] = None
    end_anchor: Optional[Tuple[float, float]] = None
    corridor_bsms: List[str] = Field(default_factory=list)
    requires_human_confirmation: bool = False
    # Semantic anchors (human-readable, not stored as RDF)
    semantic: SemanticMetadata = Field(default_factory=SemanticMetadata)


class RoadTarget(BaseModel):
    """Road planning target — fills the road sub-task gap.

    PARSE extracts road info from planning text (level, width, connectivity).
    spatial_ops.grounding fills start_anchor/end_anchor/path_bsms.
    EXECUTE road sub-task consumes this for planned road network generation.
    """

    road_level: str = ""                         # "主干道"/"次干道"/"支路"/"村道"
    width_m: float = 0.0
    connects: List[str] = Field(default_factory=list)  # ["村北", "村南"]
    source_project_id: str = ""
    source_instruction_id: str = ""
    source_report_key: str = ""
    # === 空间锚定 ===
    start_anchor: Optional[Tuple[float, float]] = None
    end_anchor: Optional[Tuple[float, float]] = None
    path_bsms: List[str] = Field(default_factory=list)
    candidate_bsms: List[str] = Field(default_factory=list)
    candidate_bbox: Optional[Tuple[float, float, float, float]] = None
    requires_human_confirmation: bool = False
    # Semantic anchors (human-readable, not stored as RDF)
    semantic: SemanticMetadata = Field(default_factory=SemanticMetadata)


class ProjectTarget(BaseModel):
    """L3 project-bank item preserved as the parent planning intent."""

    project_id: str
    name: str
    category: str = "other"
    action: Literal[
        "preserve",
        "new",
        "expand",
        "relocate",
        "upgrade",
        "repair",
        "demolish",
    ] = "new"
    scale_text: str = ""
    area_ha: Optional[float] = None
    location_hint: str = ""
    candidate_bsms: List[str] = Field(default_factory=list)
    excluded_bsms: List[str] = Field(default_factory=list)
    related_facility_types: List[str] = Field(default_factory=list)
    related_road_targets: List[str] = Field(default_factory=list)
    source_instruction_id: str = ""
    source_report_key: str = ""
    source_section: str = "INSTRUCTION"
    source_row: Optional[int] = None
    semantic: SemanticMetadata = Field(default_factory=SemanticMetadata)


# ── Planning indicator table (附表1) ────────────────────────────────


class PlanningIndicatorItem(BaseModel):
    """Single planning target indicator (from planning_targets.yaml).

    Follows 广东省技术指南 附表1: 7 indicators × 3 time dimensions.
    """

    code: str = ""           # I01-I07
    name: str = ""           # e.g. "耕地保有量"
    unit: str = ""           # e.g. "公顷"
    attribute: Literal["mandatory", "expected"] = "mandatory"
    field: str = ""          # e.g. "farmland_area_ha"
    base_year_value: Optional[float] = None
    target_year_value: Optional[float] = None
    change: Optional[float] = None


class PlanningIndicatorTable(BaseModel):
    """Planning target indicator table (附表1).

    7 indicators with base year / target year / change values.
    """

    indicators: List[PlanningIndicatorItem] = Field(default_factory=list)


# ── Three zones and three lines (三区三线) ─────────────────────────


class ThreeZoneItem(BaseModel):
    """Single three-zone entry (生态空间/农业空间/建设空间)."""

    zone_type: Literal["ecological", "agricultural", "construction"] = "agricultural"
    name: str = ""
    area_ha: float = 0.0
    ratio: float = 0.0


class ThreeLineItem(BaseModel):
    """Single three-line entry (生态保护红线/永久基本农田/城镇开发边界)."""

    line_type: Literal["ecological_redline", "permanent_farmland", "urban_dev_boundary"] = "ecological_redline"
    name: str = ""
    area_ha: float = 0.0
    geometry_ref: Optional[str] = None


class ThreeZonesThreeLines(BaseModel):
    """Three zones + three lines structure (三区三线).

    Core spatial governance framework from national policy.
    """

    zones: List[ThreeZoneItem] = Field(default_factory=list)
    lines: List[ThreeLineItem] = Field(default_factory=list)


# ── Spatial anchor (dual-stage positioning) ──────────────────────────


class SpatialAnchor(BaseModel):
    """Spatial anchor for an operation — PARSE pre-resolves from SpatialContext.

    Dual-stage localization:
      - PARSE: matches location_desc against SpatialContext.residential_clusters
               -> pre-resolves candidate parcels + confidence
      - LAYOUT: resolve_place_name confirms or corrects the anchor
    """

    reference: str = ""
    offset: Optional[str] = None
    secondary_ref: Optional[str] = None
    secondary_offset: Optional[str] = None
    candidate_parcels: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    resolution_status: Literal[
        "anchored",
        "partial",
        "unresolved",
    ] = "unresolved"


class ComplianceCheck(BaseModel):
    """Compliance pre-check result — filled by Python computation, not LLM."""

    in_construction_boundary: bool = True
    not_farmland: bool = True
    not_ecological_redline: bool = True
    within_village_boundary: bool = True


# ── Spatial operation (PARSE output, EXECUTE input) ─────────────────


class SpatialOperation(BaseModel):
    """Spatially-aware atomic operation — PARSE outputs with spatial anchor.

    5 action variants with action-specific parameter fields.
    Aligned with design doc §4.3 OperationSequence spec.
    """

    action: Literal["create", "split", "merge", "modify", "reclassify"]

    # Spatial anchor (replaces location_desc free text)
    spatial_anchor: Optional[SpatialAnchor] = None

    # Free text fallback (only when spatial_anchor resolution fails)
    location_desc: Optional[str] = None

    # Target parcels — BSM list for EXECUTE_OPERATIONS
    target_parcels: List[str] = Field(default_factory=list)

    # Common fields
    source_text: str = ""
    confidence: float = 1.0
    confidence_level: Literal["high", "medium", "low"] = "high"
    needs_confirmation: bool = True

    # create parameters
    project_name: Optional[str] = None
    area_sqm: Optional[float] = None
    land_use_name: Optional[str] = None
    land_use_code: Optional[str] = None  # GHYTBM 编码

    # split parameters
    source_bsm: Optional[str] = None

    # merge parameters
    source_bsms: Optional[List[str]] = None

    # modify/reclassify parameters
    field_changes: Optional[Dict[str, Any]] = None
    new_qmdlbm: Optional[str] = None  # 期末地类编码

    # Affected output layers
    affected_layers: List[str] = Field(default_factory=list)

    # Compliance pre-check result
    compliance: Optional[ComplianceCheck] = None

    # Metadata
    article_ref: str = ""
    residential_cluster: str = ""


# ── Spatial constraint (PARSE output, EXECUTE input) ────────────────


class SpatialRule(BaseModel):
    """Computable spatial rule — directly maps to Shapely/GeoPandas operations."""

    operation: Literal[
        "no_overlap",
        "buffer_exclusion",
        "contained_by",
        "adjacent_to",
        "distance_within",
    ] = "no_overlap"
    subject: str = ""
    object: str = ""
    distance_m: Optional[float] = None


class SpatialConstraint(BaseModel):
    """Spatially-aware constraint — PARSE outputs directly mappable to spatial ops.

    6+ constraint type literals aligned with provincial standard categories.
    """

    type: Literal[
        "area_constraint",
        "spatial_constraint",
        "building_constraint",
        "use_constraint",
        "boundary_constraint",
        "ecological_protection",
        "farmland_protection",
        "heritage_protection",
        "construction_control",
        "safety_assurance",
        "other_control",
    ] = "spatial_constraint"
    source_text: str = ""
    article_ref: str = ""
    priority: Literal[
        "mandatory",
        "recommended",
        "aspirational",
    ] = "mandatory"

    # Area constraint
    land_use: Optional[str] = None
    target_area_ha: Optional[float] = None
    operator: Optional[Literal["<=", ">=", "=="]] = None

    # Spatial constraint (enhanced)
    zone_type: Optional[str] = None
    spatial_rule: Optional[SpatialRule] = None

    # Building constraint
    max_area_sqm: Optional[float] = None
    max_height_m: Optional[float] = None
    max_floors: Optional[int] = None
    setback_m: Optional[float] = None

    #* Generic value + unit
    value: Optional[float] = None
    value_unit: Optional[str] = None  # "公顷", "米", "层", "%", "人", "m²/人"


# ── Spatial Planning Intent ─────────────────────────────────────────


class SpatialPlanningIntent(BaseModel):
    """Spatially-aware planning intent — PARSE outputs with spatial arrangement preference.

    Borrows adjacency/location_bias fields already defined but unused in prompts.py.
    Phase 3: Includes planning indicator table and three-zone-three-line structure.
    """

    village_name: str = ""
    planning_period: str = ""

    # Zone targets (enhanced)
    zone_targets: List[ZoneTarget] = Field(default_factory=list)

    # Facility requirements (enhanced)
    facilities: List[FacilityTarget] = Field(default_factory=list)

    # Development axes (enhanced)
    development_axes: List[AxisTarget] = Field(default_factory=list)

    # Road targets (new — fills road sub-task gap)
    road_targets: List[RoadTarget] = Field(default_factory=list)

    # L3 project-bank parents. Facilities/roads/zones may derive from these.
    project_targets: List[ProjectTarget] = Field(default_factory=list)

    # Custom functional zone targets (P6 — from Explore/Binder project domain)
    custom_zone_targets: List["CustomZoneTarget"] = Field(default_factory=list)

    # Session vocabulary name for custom zoning (P7 — LLM-extracted from L3 reports)
    vocabulary_name: str = ""
    # Area constraints (preserved)
    total_area_ha: Optional[float] = None
    construction_area_ha: Optional[float] = None
    farmland_area_ha: Optional[float] = None
    ecological_area_ha: Optional[float] = None

    # Population
    population: Optional[int] = None

    # Phase 3: Planning indicator table (附表1)
    indicator_table: Optional[PlanningIndicatorTable] = None

    # Phase 3: Three zones and three lines (三区三线)
    three_zones_three_lines: Optional[ThreeZonesThreeLines] = None

    # Semantic anchors (human-readable, not stored as RDF)
    raw_text: str = ""                           # User's original planning text
    reasoning_trace: str = ""                    # PARSE reasoning process

    @property
    def total_area_ratio(self) -> float:
        """Sum of all zone target area ratios."""
        return sum(zt.area_ratio for zt in self.zone_targets)

    def get_zone_by_id(self, zone_id: str) -> Optional[ZoneTarget]:
        """Find a zone target by its zone_id."""
        for zt in self.zone_targets:
            if zt.zone_id == zone_id:
                return zt
        return None

    def get_zone_by_land_use(self, land_use: str) -> List[ZoneTarget]:
        """Find all zone targets matching a land use name or enum value."""
        return [zt for zt in self.zone_targets if zt.land_use and zt.land_use == land_use]


__all__ = [
    "SpatialPreference",
    "AdjacencyRules",
    "ZoneTarget",
    "FacilityTarget",
    "AxisTarget",
    "RoadTarget",
    "ProjectTarget",
    "SemanticMetadata",
    "PlanningIndicatorItem",
    "PlanningIndicatorTable",
    "ThreeZoneItem",
    "ThreeLineItem",
    "ThreeZonesThreeLines",
    "SpatialPlanningIntent",
    "SpatialAnchor",
    "ComplianceCheck",
    "SpatialOperation",
    "SpatialRule",
    "SpatialConstraint",
]


# P6: forward ref for custom_zone_targets — resolve CustomZoneTarget lazily
try:
    from .custom_zone_contracts import CustomZoneTarget  # noqa: F401

    SpatialPlanningIntent.model_rebuild()
except Exception:
    pass
