"""Ontology definitions for PlanningKG (v4.6).

[v4.6] Removed non-spatial entity types: Constraint, PlanningIndicator,
ControlRule, LandUseCategory, PlanIntent, Axis (L1 unused).
Added L3 RoadTarget, L4 PlannedZone/PlannedFacility/PlannedRoad/PlannedAxis.
Removed 8 relations: constrained_by, achieves, conflicts_with, conducted_from,
controls_use, protects, adjacent_to, location_constraint.

Entity types: 19 total
  L1: Parcel, Zone, Village, Facility, Road, WaterBody, ThreeZone, ThreeLine,
      AdministrativeVillage, NaturalSettlement
  L3: ZoneTarget, FacilityTarget, AxisTarget, RoadTarget
  L4: PlannedParcel, PlannedZone, PlannedFacility, PlannedRoad, PlannedAxis

Relations: 10 total
  Spatial: touches, nearby, connected_via_road, within_zone, located_in
  Semantic: designated_as, derived_from, serves, connects, delineates
"""

from __future__ import annotations

from rdflib import Literal, Namespace, URIRef

PLN = Namespace("http://village-planning.org/ontology#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")


class EntityIdPolicy:
    """统一实体标识契约 - 所有 KG 实体的 URI 生成与 BSM 绑定.

    Rules:
      L1 entities: uri = PLN[f"{entity_type}_{bsm}"]
      L3 entities: uri = PLN[f"{entity_type}_{target_id}"]  (intent, no BSM)
      L4 entities: uri = PLN[f"{entity_type}_{bsm}_v{version}"]

    When BSM is missing, use ysdm + seq for a stable fallback:
      PLN[f"{entity_type}_{ysdm}_{seq}"]
    """

    @staticmethod
    def uri(entity_type: str, bsm: str, version: str = "") -> URIRef:
        if version:
            return PLN[f"{entity_type}_{bsm}_{version}"]
        return PLN[f"{entity_type}_{bsm}"]

    @staticmethod
    def uri_with_seq(entity_type: str, bsm: str, seq: int, version: str = "") -> URIRef:
        """URI with sequence suffix for entities sharing the same BSM.

        Used when multiple features have the same BSM (e.g. multi-part parcels
        with different DLBM sub-areas). The seq disambiguates them.
        """
        if seq == 0:
            return EntityIdPolicy.uri(entity_type, bsm, version)
        if version:
            return PLN[f"{entity_type}_{bsm}_{seq}_{version}"]
        return PLN[f"{entity_type}_{bsm}_{seq}"]

    @staticmethod
    def fallback_uri(entity_type: str, ysdm: str, seq: int) -> URIRef:
        code = ysdm or "noysdm"
        return PLN[f"{entity_type}_{code}_{seq}"]

    @staticmethod
    def attach_bsm(graph, uri, bsm: str):
        if bsm:
            graph.add((uri, PLN.bsm, Literal(bsm)))


class EntityTypes:
    """19 entity type URIs for the planning ontology (v4.6).

    v4.6: removed Constraint, PlanningIndicator, ControlRule, LandUseCategory,
    PlanIntent, Axis (non-spatial). Added RoadTarget (L3), PlannedZone,
    PlannedFacility, PlannedRoad, PlannedAxis (L4)."""
    # L1: Static entities (现状)
    Parcel = PLN.Parcel
    Zone = PLN.Zone
    Village = PLN.Village
    Facility = PLN.Facility
    Road = PLN.Road
    WaterBody = PLN.WaterBody
    ThreeZone = PLN.ThreeZone
    ThreeLine = PLN.ThreeLine
    AdministrativeVillage = PLN.AdministrativeVillage
    NaturalSettlement = PLN.NaturalSettlement
    # L3: Intent virtual entities (意图虚拟实体)
    ZoneTarget = PLN.ZoneTarget
    FacilityTarget = PLN.FacilityTarget
    AxisTarget = PLN.AxisTarget
    RoadTarget = PLN.RoadTarget
    # L4: Planned state (规划成果)
    PlannedParcel = PLN.PlannedParcel
    PlannedZone = PLN.PlannedZone
    PlannedFacility = PLN.PlannedFacility
    PlannedRoad = PLN.PlannedRoad
    PlannedAxis = PLN.PlannedAxis

    @classmethod
    def all(cls) -> list:
        return [
            cls.Parcel, cls.Zone, cls.Village, cls.Facility, cls.Road, cls.WaterBody,
            cls.ThreeZone, cls.ThreeLine,
            cls.AdministrativeVillage, cls.NaturalSettlement,
            cls.ZoneTarget, cls.FacilityTarget, cls.AxisTarget, cls.RoadTarget,
            cls.PlannedParcel, cls.PlannedZone, cls.PlannedFacility,
            cls.PlannedRoad, cls.PlannedAxis,
        ]


class Relations:
    """10 relationship type URIs for the planning ontology (v4.6).

    v4.6: removed constrained_by, achieves, conflicts_with, conducted_from,
    controls_use, protects, adjacent_to, location_constraint (non-spatial).

    Spatial relations:
      touches (L1 topology), nearby (L2 proximity), connected_via_road (L3 connectivity)
    """
    # Spatial topology
    within_zone = PLN.within_zone
    touches = PLN.touches
    nearby = PLN.nearby
    connected_via_road = PLN.connected_via_road
    located_in = PLN.located_in
    # Planning semantics
    designated_as = PLN.designated_as
    derived_from = PLN.derived_from
    serves = PLN.serves
    connects = PLN.connects
    delineates = PLN.delineates

    @classmethod
    def all(cls) -> list:
        return [
            cls.within_zone, cls.touches, cls.nearby, cls.connected_via_road,
            cls.located_in,
            cls.designated_as, cls.derived_from, cls.serves, cls.connects,
            cls.delineates,
        ]


# v4.4 — Attribute properties (not relations, but used as PLN predicates)
# These are accessed as PLN.attr_name rather than through Relations class
# shared_boundary_length, centroid_distance, shortest_path_length,
# max_distance_m, land_use_code, target_area_ha, min_area_sqm

# v4.7 — L3 spatial anchoring predicates (PARSE grounding)
# Accessed as PLN.attr_name (e.g. PLN.candidate_bsm, PLN.spatial_hint)
# candidate_bsm, excluded_bsm, candidate_bbox, spatial_hint, description, raw_planning_text
# has_zone, has_facility, has_axis, has_road — village-to-L3 linking


# Facility types — used by layer builders
FACILITY_TYPES = {
    "公共服务": {"entity": EntityTypes.Facility, "serves": "居民"},
    "教育": {"entity": EntityTypes.Facility, "serves": "学生"},
    "医疗": {"entity": EntityTypes.Facility, "serves": "患者"},
    "文化": {"entity": EntityTypes.Facility, "serves": "居民"},
    "体育": {"entity": EntityTypes.Facility, "serves": "居民"},
}

# Regulation types — 省标6大类管制规则(附录3)
REGULATION_TYPES = {
    "永久基本农田保护": {"category": "farmland_protection"},
    "生态保护红线": {"category": "ecological_protection"},
    "村庄建设边界": {"category": "construction_control"},
    "历史文化保护": {"category": "heritage_protection"},
    "村庄安全防灾": {"category": "safety_assurance"},
    "建设空间管制": {"category": "construction_spatial_control"},
}
