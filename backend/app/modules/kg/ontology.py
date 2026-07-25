"""Ontology definitions for PlanningKG (v4.5).

Defines 17 entity types and 16 relationship types following
the 三区三线 national standard planning framework.

[v4.5] Cleanup: removed 6 unused types (BuildingGroup, LandUsePlan, Project,
LandConservationPlan, ReforestationPlan, GridRegulation). Merged Regulation→ControlRule,
Indicator→PlanningIndicator. Intent types unified: _add_structured_intent now consumes
parse_contracts.SpatialPlanningIntent directly (no PlanIntent/context_contracts bridge).

Entity types:
  Parcel, Zone, Constraint, PlanningIndicator  (Phase 0 merged)
  Village, Facility, Axis, Road, WaterBody  (Phase 1, cleaned)
  ControlRule, LandUseCategory  (Phase 3 — paradigm alignment)
  ThreeZone, ThreeLine  (Phase 3 — 三区三线)
  ZoneTarget, FacilityTarget, AxisTarget, PlanIntent  (v4.4 — structured intent)

[v4.4] Three-layer spatial relations:
  touches (L1 topology), nearby (L2 proximity), connected_via_road (L3 connectivity)
  With attributed properties: shared_boundary_length, centroid_distance, shortest_path_length

[v4.4] Intent entity types:
  ZoneTarget, FacilityTarget, AxisTarget, PlanIntent
  With constraint properties: location_constraint, max_distance_m, land_use_code
"""

from __future__ import annotations

from rdflib import Namespace

PLN = Namespace("http://village-planning.org/ontology#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")


class EntityTypes:
    """17 entity type URIs for the planning ontology (v4.5, cleaned).

    v4.5 cleanup: removed BuildingGroup, LandUsePlan, Project,
    LandConservationPlan, ReforestationPlan, GridRegulation (unused).
    Merged Regulation→ControlRule, Indicator→PlanningIndicator."""
    # Existing (Phase 0)
    Parcel = PLN.Parcel
    Zone = PLN.Zone
    Constraint = PLN.Constraint
    PlanningIndicator = PLN.PlanningIndicator
    # New (Phase 1 — cleaned)
    Village = PLN.Village
    Facility = PLN.Facility
    Axis = PLN.Axis
    Road = PLN.Road
    WaterBody = PLN.WaterBody
    # Phase 3 — 专业范式对齐实体（省标/国标）
    ControlRule = PLN.ControlRule
    LandUseCategory = PLN.LandUseCategory
    ThreeZone = PLN.ThreeZone
    ThreeLine = PLN.ThreeLine
    # Phase 6 — Village hierarchy (administrative village vs natural settlement)
    AdministrativeVillage = PLN.AdministrativeVillage
    NaturalSettlement = PLN.NaturalSettlement
    # v4.4 — Structured intent entities
    ZoneTarget = PLN.ZoneTarget
    FacilityTarget = PLN.FacilityTarget
    AxisTarget = PLN.AxisTarget
    PlanIntent = PLN.PlanIntent
    # v4.4 — Planning state (Layer 4)
    PlannedParcel = PLN.PlannedParcel

    @classmethod
    def all(cls) -> list:
        return [
            cls.Parcel, cls.Zone, cls.Constraint, cls.PlanningIndicator,
            cls.Village, cls.Facility, cls.Axis, cls.Road, cls.WaterBody,
            cls.ControlRule, cls.LandUseCategory,
            cls.ThreeZone, cls.ThreeLine,
            cls.AdministrativeVillage, cls.NaturalSettlement,
            cls.ZoneTarget, cls.FacilityTarget, cls.AxisTarget, cls.PlanIntent,
        ]


class Relations:
    """16 relationship type URIs for the planning ontology (v4.5, cleaned).

    @deprecated adjacent_to: replaced by touches (v4.4) with shared_boundary_length.
    Kept for zone-level adjacency (ZONE_ADJACENCY ContextBlock). Use touches for
    parcel-level spatial relations.

    v4.4 新增 3 个空间关系属性（L1-L3 三层模型）：
    - touches: 拓扑邻接（共享边界）
    - nearby: 近邻关系（质心距离 <= 200m）
    - connected_via_road: 道路连通

    v4.4 新增意图属性：
    - location_constraint: 位置约束
    - max_distance_m: 最大距离
    - land_use_code: 用地编码
    """
    # Existing (Phase 0)
    adjacent_to = PLN.adjacent_to  # @deprecated: use touches for parcel-level
    within_zone = PLN.within_zone
    constrained_by = PLN.constrained_by
    # New (Phase 1)
    designated_as = PLN.designated_as
    protects = PLN.protects
    located_in = PLN.located_in
    achieves = PLN.achieves
    conflicts_with = PLN.conflicts_with
    derived_from = PLN.derived_from
    serves = PLN.serves
    connects = PLN.connects
    # Phase 3 — 专业范式关系
    delineates = PLN.delineates
    controls_use = PLN.controls_use
    conducted_from = PLN.conducted_from
    # v4.4 — Three-layer spatial relations
    touches = PLN.touches
    nearby = PLN.nearby
    connected_via_road = PLN.connected_via_road
    # v4.4 — Intent properties
    location_constraint = PLN.location_constraint

    @classmethod
    def all(cls) -> list:
        return [
            cls.adjacent_to, cls.within_zone, cls.constrained_by,
            cls.designated_as, cls.protects, cls.located_in,
            cls.achieves, cls.conflicts_with, cls.derived_from,
            cls.serves, cls.connects,
            cls.delineates, cls.controls_use, cls.conducted_from,
            cls.touches, cls.nearby, cls.connected_via_road,
            cls.location_constraint,
        ]


# v4.4 — Attribute properties (not relations, but used as PLN predicates)
# These are accessed as PLN.attr_name rather than through Relations class
# shared_boundary_length, centroid_distance, shortest_path_length,
# max_distance_m, land_use_code, target_area_ha, min_area_sqm


# Facility types for _add_spatial_infrastructure (used by layer1.py)
FACILITY_TYPES = {
    "公共服务": {"entity": EntityTypes.Facility, "serves": "居民"},
    "教育": {"entity": EntityTypes.Facility, "serves": "学生"},
    "医疗": {"entity": EntityTypes.Facility, "serves": "患者"},
    "文化": {"entity": EntityTypes.Facility, "serves": "居民"},
    "体育": {"entity": EntityTypes.Facility, "serves": "居民"},
}

# Regulation types — 省标6大类管制规则(附录3), mapped to ControlRule
REGULATION_TYPES = {
    "永久基本农田保护": {"protects": "农田保护区", "field": "farmland_area_ha", "category": "farmland_protection"},
    "生态保护红线": {"protects": "生态保护区", "field": "ecological_redline_ha", "category": "ecological_protection"},
    "村庄建设边界": {"protects": "村庄建设区", "field": "construction_area_ha", "category": "construction_control"},
    "历史文化保护": {"protects": "历史文化区", "field": "", "category": "heritage_protection"},
    "村庄安全防灾": {"protects": "全村范围", "field": "", "category": "safety_assurance"},
    "建设空间管制": {"protects": "村庄建设区", "field": "construction_area_ha", "category": "construction_spatial_control"},
}
