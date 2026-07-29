"""Ontology definitions for PlanningKG (v4.8.2).

Naming convention:
  - GisXxx / gis_* = GIS map-layer concepts (data themes, layer_registry)
  - Layer{1,2,3,4} = KG planning-phase build stages
  - Plain names = KG-internal (semantic enrichment, entity types)

[v4.6] Removed non-spatial entity types: Constraint, PlanningIndicator,
ControlRule, LandUseCategory, PlanIntent, Axis (L1 unused).
Added L3 RoadTarget, L4 PlannedZone/PlannedFacility/PlannedRoad/PlannedAxis.
Removed 8 relations: constrained_by, achieves, conflicts_with, conducted_from,
controls_use, protects, adjacent_to, location_constraint.

[v4.7] ThreeZone/ThreeLine removed from active entity types (all()) -
           transitioned to ConstraintIndex-based spatial queries.
           The type constants remain as class attributes for backward compat.

[v4.8] Spatial cognition schema:
          - Three-dimension predicates: gis_type_ref, geometry_kind, semantic_group,
            has_semantic_label (per L1 entity, from gis_layer_registry.yaml + encoding)
          - GisLayerSet virtual entity: aggregates contains_entity for layer-set
            level queries and LLM-facing layer cards.
          - Semantic-enrichment predicates: taxonomic_parent, legal_constraint,
            allowed_operations (entity-type level, derived from encodings/dicts/rules).

[v4.8.2] Naming cleanup:
          - GIS-related predicates prefixed with gis_:
            layer_type->gis_type_ref, layer_description->gis_description,
            layer_entity_count->entity_count, LayerGroup->GisLayerSet,
            layer_description_enriched->gis_description_enriched
          - Functions: get_layer_group_info->get_gis_layer_group_info,
            get_all_layer_groups->get_all_gis_layer_groups
          - Python classes/variables: LAYER_TYPE_REGISTRY->GIS_LAYER_REGISTRY,
            LayerTypeEntry->GisLayerTypeEntry, register_layer_type->register_gis_layer_type

Entity types: 18 total (active)
  L1: Parcel, Zone, Village, Facility, Road, WaterBody,
      AdministrativeVillage, ResidentialCluster, GisLayerSet
  L3: ZoneTarget, FacilityTarget, AxisTarget, RoadTarget
  L4: PlannedParcel, PlannedZone, PlannedFacility, PlannedRoad, PlannedAxis

Relations: 8 total (v4.9 GeoSPARQL aligned)
  Spatial: geo:sfTouches, pln:nearby, pln:connected_via_road, geo:sfWithin, geo:sfIntersects, geo:sfContains
  Semantic: pln:derived_from, pln:serves
  (within_zone, designated_as, connects, delineates kept for backward compat but not in active set)
"""

from __future__ import annotations

from rdflib import Literal, Namespace, URIRef

PLN = Namespace("http://village-planning.org/ontology#")
PLN_NS = "http://village-planning.org/ontology#"
GEO = Namespace("http://www.opengis.net/ont/geosparql#")


# ============================================================
# Geometry kind constants (mirror gis_layer_registry.yaml geometry_kind values)
# ============================================================

GEOMETRY_POLYGON = "polygon"
GEOMETRY_LINE = "line"
GEOMETRY_POINT = "point"
GEOMETRY_RASTER = "raster"


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
    """18 active entity type URIs for the planning ontology (v4.8).

    v4.6: removed Constraint, PlanningIndicator, ControlRule, LandUseCategory,
    PlanIntent, Axis (non-spatial). Added RoadTarget (L3), PlannedZone,
    PlannedFacility, PlannedRoad, PlannedAxis (L4).
    v4.7: ThreeZone/ThreeLine removed from all() - migrated to ConstraintIndex.
          The type constants remain for backward compat (3rd-party scripts).
    v4.8: LayerGroup added - virtual entity aggregating layer-group membership
          for layer-card-level queries (not a spatial entity, carries no BSM)."""
    # L1: Static entities (现状)
    Parcel = PLN.Parcel
    Zone = PLN.Zone
    Village = PLN.Village
    Facility = PLN.Facility
    Road = PLN.Road
    WaterBody = PLN.WaterBody
    AdministrativeVillage = PLN.AdministrativeVillage
    ResidentialCluster = PLN.ResidentialCluster
    PlaceRef = PLN.PlaceRef
    ControlLine = PLN.ControlLine      # 控制线（灾害/洪涝等）
    GisLayerSet = PLN.GisLayerSet      # v4.8: virtual gis-layer aggregator
    RasterDataset = PLN.RasterDataset  # v4.audit: DEM/DOM raster entity
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
        """Active entity types (18, excluding ThreeZone/ThreeLine per v4.7)."""
        return [
            cls.Parcel, cls.Zone, cls.Village, cls.Facility, cls.Road, cls.WaterBody,
            cls.AdministrativeVillage, cls.ResidentialCluster, cls.ControlLine, cls.GisLayerSet,
            cls.ZoneTarget, cls.FacilityTarget, cls.AxisTarget, cls.RoadTarget,
            cls.PlannedParcel, cls.PlannedZone, cls.PlannedFacility,
            cls.PlannedRoad, cls.PlannedAxis,
        ]

    @classmethod
    def spatial_l1(cls) -> list:
        """L1 spatial entity types (have geometry, carry BSM). Excludes GisLayerSet."""
        return [
            cls.Parcel, cls.Zone, cls.Village, cls.Facility, cls.Road, cls.WaterBody,
            cls.AdministrativeVillage, cls.ResidentialCluster, cls.ControlLine,
        ]


class Relations:
    """9 active relationship type URIs (v4.9 - GeoSPARQL aligned).

    v4.9: 4 spatial predicates replaced with GeoSPARQL standard:
      touches     -> geo:sfTouches
      located_in  -> geo:sfWithin
      intersects  -> geo:sfIntersects
      contains    -> geo:sfContains
    5 pln extension predicates kept unchanged:
      nearby, connected_via_road, derived_from, serves, connects
    """

    # Spatial topology (GeoSPARQL standard)
    sfTouches = GEO.sfTouches
    nearby = PLN.nearby
    connected_via_road = PLN.connected_via_road
    sfWithin = GEO.sfWithin
    sfIntersects = GEO.sfIntersects
    sfContains = GEO.sfContains
    # Planning semantics
    derived_from = PLN.derived_from
    serves = PLN.serves
    # Active extension predicate (used in layer1.py)
    connects = PLN.connects

    @classmethod
    def all(cls) -> list:
        """Active relations (8)."""
        return [
            cls.sfTouches, cls.nearby, cls.connected_via_road,
            cls.sfWithin, cls.sfIntersects, cls.sfContains,
            cls.derived_from, cls.serves,
        ]


class SemanticPredicates:
    """v4.8 spatial cognition predicates, organized by category.

    GIS-type predicates (per L1 spatial entity, written at build time):
      gis_type_ref      <- gis_layer_registry.yaml key (e.g. "landuse_current", "road")
      geometry_kind     <- "polygon" | "line" | "point"
      semantic_group    <- gis_layer_registry.yaml group (e.g. "current_landuse", "transport")
      has_semantic_label <- Chinese label derived from dlbm (e.g. 0101 -> "水田")

    GisLayerSet predicates (on GisLayerSet virtual entities):
      contains_entity      <- links GisLayerSet -> its member entities
      gis_description      <- human-readable description (registry + statistics)
      entity_count         <- integer count
      dominant_label       <- most frequent has_semantic_label in the set

    Semantic-enrichment predicates (entity-type level, derived from encodings/dicts/rules):
      taxonomic_parent   <- classification hierarchy (水田 -> 耕地 -> 农用地)
      legal_constraint   <- legal restriction (农田保护区 -> forbid_construction)
      allowed_operations <- permitted SpatialOperation actions (宅基地 -> [split,merge,reclassify])
    """
    # GIS-type predicates
    gis_type_ref = PLN.gis_type_ref
    geometry_kind = PLN.geometry_kind
    semantic_group = PLN.semantic_group
    has_semantic_label = PLN.has_semantic_label

    # GisLayerSet predicates
    contains_entity = PLN.contains_entity
    gis_description = PLN.gis_description
    entity_count = PLN.entity_count
    dominant_label = PLN.dominant_label

    # Semantic-enrichment predicates
    taxonomic_parent = PLN.taxonomic_parent
    legal_constraint = PLN.legal_constraint
    allowed_operations = PLN.allowed_operations

    # Cross-type spatial relation quantitative attribute
    overlap_pct = PLN.overlap_pct


class ProvenancePredicates:
    """v4.9: Encoding decision provenance predicates.

    These predicates record the decision chain for code mappings
    at the individual feature level.
    """
    decided_by = PLN.decided_by
    decision_confidence = PLN.decision_confidence
    decision_evidence = PLN.decision_evidence
    mapping_basis = PLN.mapping_basis


# ============================================================
# GIS layer metadata: dynamically read from gis_layer_registry.yaml
# ============================================================

def get_gis_layer_group_info(group_name: str) -> dict:
    """Get GIS layer metadata from gis_layer_registry.yaml by semantic group name.

    Reads the YAML at runtime - no hardcoded registry dict.
    Returns dict with: gis_type_ref, geometry_kind, description.
    Returns empty dict if group not found.
    """
    try:
        from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY
        for gis_type, entry in GIS_LAYER_REGISTRY.items():
            if _gis_type_matches_group(gis_type, group_name):
                return {
                    "gis_type_ref": gis_type,
                    "geometry_kind": entry.geometry_kind,
                    "description": entry.description,
                }
    except Exception:
        pass
    return {}


def _gis_type_matches_group(gis_type: str, group_name: str) -> bool:
    """Check if a gis_type belongs to a semantic group.

    Maps semantic_group -> representative gis_type_ref.
    """
    _GROUP_TO_GIS_TYPE = {
        "current_landuse": "landuse_current",
        "transport": "road",
        "water": "water",
        "facility": "current_facility",
        "protection": "farmland_protection",
        "hazard": "hazard_control_line",
        "hazard_point": "geological_hazard_points",
        "construction": "construction_zone",
        "admin": "boundary",
        "building": "current_building",
        "terrain": "contour_line",
        "natural_resource": "soil_type",
    }
    return _GROUP_TO_GIS_TYPE.get(group_name) == gis_type


def get_all_gis_layer_groups() -> list:
    """Return all known GIS semantic group names."""
    return [
        "current_landuse", "transport", "water", "facility",
        "protection", "hazard", "hazard_point", "construction",
        "admin", "building", "terrain", "natural_resource",
    ]


# ============================================================
# Semantic-enrichment derivation rules (documentation)
# ============================================================
#
# taxonomic_parent: derived from appendix5 zone_type + planning_zone_to_primary_zone
#   DLBM -> zone_type (农业用地/生态绿地/居住用地/...) -> primary_zone (农业空间/生态空间/建设空间)
#
# legal_constraint: derived from construction_zone_codes + planning_zone_to_control_code
#   planning_zone -> control_code (01-06) -> constraint description
#   05 永久基本农田保护区 -> "forbid_construction" (禁止非农建设)
#   06 生态保护红线区 -> "forbid_construction" (禁止建设)
#   04 禁止建设区 -> "forbid_construction"
#   03 有条件建设区 -> "conditional_construction" (不超过现状20%)
#   02 限制建设区 -> "restrict_construction"
#   01 允许建设区 -> "allow_construction"
#
# allowed_operations: manually supplemented from allowed_operations.yaml
#   (see encodings/dicts/rules/allowed_operations.yaml)


# Facility types - used by layer builders
FACILITY_TYPES = {
    "公共服务": {"entity": EntityTypes.Facility, "serves": "居民"},
    "教育": {"entity": EntityTypes.Facility, "serves": "学生"},
    "医疗": {"entity": EntityTypes.Facility, "serves": "患者"},
    "文化": {"entity": EntityTypes.Facility, "serves": "居民"},
    "体育": {"entity": EntityTypes.Facility, "serves": "居民"},
}

# Regulation types - 省标6大类管制规则(附录3)
REGULATION_TYPES = {
    "永久基本农田保护": {"category": "farmland_protection"},
    "生态保护红线": {"category": "ecological_protection"},
    "村庄建设边界": {"category": "construction_control"},
    "历史文化保护": {"category": "heritage_protection"},
    "村庄安全防灾": {"category": "safety_assurance"},
    "建设空间管制": {"category": "construction_spatial_control"},
}
