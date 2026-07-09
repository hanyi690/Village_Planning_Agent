"""Ontology definitions for PlanningKG.

Defines 16 entity types and 11 relationship types following
the 三区三线 national standard planning framework, augmented with
省级村庄规划编制规程 (DB35/T 2061-2022, DB14/T 3120-2024) 整治规划实体.

Entity types:
  Parcel, Zone, Constraint, Indicator  (Phase 0)
  Project, Village, Regulation, LandUsePlan  (Phase 1)
  Facility, Axis, Road, WaterBody, BuildingGroup  (Phase 1)
  LandConservationPlan, ReforestationPlan, GridRegulation  (Phase 2)

Relationship types:
  adjacent_to, within_zone, constrained_by  (existing)
  designated_as, protects, located_in  (new)
  achieves, conflicts_with, derived_from  (new)
  serves, connects  (new)
"""

from __future__ import annotations

from rdflib import Namespace

PLN = Namespace("http://village-planning.org/ontology#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")


class EntityTypes:
    """16 entity type URIs for the planning ontology.

    Phase 2 新增 3 个整治规划实体，对标 DB35/T 2061-2022、DB14/T 3120-2024 省级规程：
    - LandConservationPlan: 土地整治规划
    - ReforestationPlan: 生态修复规划
    - GridRegulation: 田水路林村综合整治
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

    @classmethod
    def all(cls) -> list:
        return [
            cls.Parcel, cls.Zone, cls.Constraint, cls.Indicator,
            cls.Project, cls.Village, cls.Regulation, cls.LandUsePlan,
            cls.Facility, cls.Axis, cls.Road, cls.WaterBody, cls.BuildingGroup,
            cls.LandConservationPlan, cls.ReforestationPlan, cls.GridRegulation,
        ]


class Relations:
    """11 relationship type URIs for the planning ontology."""
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

    @classmethod
    def all(cls) -> list:
        return [
            cls.adjacent_to, cls.within_zone, cls.constrained_by,
            cls.designated_as, cls.protects, cls.located_in,
            cls.achieves, cls.conflicts_with, cls.derived_from,
            cls.serves, cls.connects,
        ]


# Facility types for _add_spatial_infrastructure
FACILITY_TYPES = {
    "公共服务": {"entity": EntityTypes.Facility, "serves": "居民"},
    "教育": {"entity": EntityTypes.Facility, "serves": "学生"},
    "医疗": {"entity": EntityTypes.Facility, "serves": "患者"},
    "文化": {"entity": EntityTypes.Facility, "serves": "居民"},
    "体育": {"entity": EntityTypes.Facility, "serves": "居民"},
}

# Regulation types for _add_regulation
REGULATION_TYPES = {
    "永久基本农田保护": {"protects": "农田保护区", "field": "farmland_area_ha"},
    "生态保护红线": {"protects": "生态保护区", "field": "ecological_redline_ha"},
    "村庄建设边界": {"protects": "村庄建设区", "field": "construction_area_ha"},
}
