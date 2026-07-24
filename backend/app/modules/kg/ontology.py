"""Ontology definitions for PlanningKG.

Defines 21 entity types and 14 relationship types following
the 三区三线 national standard planning framework, augmented with
省级村庄规划编制规程 (DB35/T 2061-2022, DB14/T 3120-2024) 整治规划实体
and professional paradigm alignment (VNE/LandUseCategory/ControlRule/ThreeZone/ThreeLine).

Entity types:
  Parcel, Zone, Constraint, Indicator  (Phase 0)
  Project, Village, Regulation, LandUsePlan  (Phase 1)
  Facility, Axis, Road, WaterBody, BuildingGroup  (Phase 1)
  LandConservationPlan, ReforestationPlan, GridRegulation  (Phase 2)
  ControlRule, LandUseCategory, PlanningIndicator  (Phase 3 — paradigm alignment)
  ThreeZone, ThreeLine  (Phase 3 — 三区三线)

Relationship types:
  adjacent_to, within_zone, constrained_by  (Phase 0)
  designated_as, protects, located_in  (Phase 1)
  achieves, conflicts_with, derived_from  (Phase 1)
  serves, connects  (Phase 1)
  delineates, controls_use, conducted_from  (Phase 3 — paradigm alignment)
"""

from __future__ import annotations

from rdflib import Namespace

PLN = Namespace("http://village-planning.org/ontology#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")


class EntityTypes:
    """21 entity type URIs for the planning ontology.

    Phase 2 新增 3 个整治规划实体，对标 DB35/T 2061-2022、DB14/T 3120-2024 省级规程：
    - LandConservationPlan: 土地整治规划
    - ReforestationPlan: 生态修复规划
    - GridRegulation: 田水路林村综合整治

    Phase 3 新增 5 个专业范式对齐实体（省标/国标）：
    - ControlRule: 管制规则（附录3 6大类）
    - LandUseCategory: 用地分类（VNE 15小类）
    - PlanningIndicator: 规划指标（附表1 7指标×3时间维度）
    - ThreeZone: 三区（生态/农业/建设空间）
    - ThreeLine: 三线（生态红线/永久基本农田/城镇开发边界）
    """
    # Existing (Phase 0)
    Parcel = PLN.Parcel
    Zone = PLN.Zone
    Constraint = PLN.Constraint
    Indicator = PLN.Indicator
    # New (Phase 1)
    Project = PLN.Project
    Village = PLN.Village
    Regulation = PLN.Regulation
    LandUsePlan = PLN.LandUsePlan
    Facility = PLN.Facility
    Axis = PLN.Axis
    Road = PLN.Road
    WaterBody = PLN.WaterBody
    BuildingGroup = PLN.BuildingGroup
    # Phase 2 — 整治规划实体（对标省级村庄规划编制规程）
    LandConservationPlan = PLN.LandConservationPlan
    ReforestationPlan = PLN.ReforestationPlan
    GridRegulation = PLN.GridRegulation
    # Phase 3 — 专业范式对齐实体（省标/国标）
    ControlRule = PLN.ControlRule
    LandUseCategory = PLN.LandUseCategory
    PlanningIndicator = PLN.PlanningIndicator
    ThreeZone = PLN.ThreeZone
    ThreeLine = PLN.ThreeLine

    @classmethod
    def all(cls) -> list:
        return [
            cls.Parcel, cls.Zone, cls.Constraint, cls.Indicator,
            cls.Project, cls.Village, cls.Regulation, cls.LandUsePlan,
            cls.Facility, cls.Axis, cls.Road, cls.WaterBody, cls.BuildingGroup,
            cls.LandConservationPlan, cls.ReforestationPlan, cls.GridRegulation,
            cls.ControlRule, cls.LandUseCategory, cls.PlanningIndicator,
            cls.ThreeZone, cls.ThreeLine,
        ]


class Relations:
    """14 relationship type URIs for the planning ontology.

    Phase 3 新增 3 个专业范式关系：
    - delineates: 控制线划定 (ThreeLine → Parcel)
    - controls_use: 用途管制 (ControlRule → LandUseCategory)
    - conducted_from: 上位传导 (PlanningIndicator → UpperPlan)
    """
    # Existing (Phase 0)
    adjacent_to = PLN.adjacent_to
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

    @classmethod
    def all(cls) -> list:
        return [
            cls.adjacent_to, cls.within_zone, cls.constrained_by,
            cls.designated_as, cls.protects, cls.located_in,
            cls.achieves, cls.conflicts_with, cls.derived_from,
            cls.serves, cls.connects,
            cls.delineates, cls.controls_use, cls.conducted_from,
        ]


# Facility types for _add_spatial_infrastructure
FACILITY_TYPES = {
    "公共服务": {"entity": EntityTypes.Facility, "serves": "居民"},
    "教育": {"entity": EntityTypes.Facility, "serves": "学生"},
    "医疗": {"entity": EntityTypes.Facility, "serves": "患者"},
    "文化": {"entity": EntityTypes.Facility, "serves": "居民"},
    "体育": {"entity": EntityTypes.Facility, "serves": "居民"},
}

# Regulation types for _add_regulation — 省标6大类管制规则(附录3)
REGULATION_TYPES = {
    "永久基本农田保护": {"protects": "农田保护区", "field": "farmland_area_ha", "category": "farmland_protection"},
    "生态保护红线": {"protects": "生态保护区", "field": "ecological_redline_ha", "category": "ecological_protection"},
    "村庄建设边界": {"protects": "村庄建设区", "field": "construction_area_ha", "category": "construction_control"},
    "历史文化保护": {"protects": "历史文化区", "field": "", "category": "heritage_protection"},
    "村庄安全防灾": {"protects": "全村范围", "field": "", "category": "safety_assurance"},
    "建设空间管制": {"protects": "村庄建设区", "field": "construction_area_ha", "category": "construction_spatial_control"},
}
