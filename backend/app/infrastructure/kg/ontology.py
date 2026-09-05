"""Ontology definitions for the DATA-backed World Model.

Naming convention:
  - GisXxx / gis_* = GIS map-layer concepts (data themes, layer_registry)
  - Layer{1,2,3,4} = KG planning-phase build stages
  - Plain names = KG-internal (semantic enrichment, entity types)

[v4.6] Removed non-spatial entity types: Constraint, PlanningIndicator,
ControlRule, LandUseCategory, PlanIntent, Axis (L1 unused).
Added L3 RoadTarget, L4 PlannedZone/PlannedFacility/PlannedRoad/PlannedAxis.
Removed 8 relations: constrained_by, achieves, conflicts_with, conducted_from,
controls_use, protects, adjacent_to, location_constraint.

[current] ThreeZone/ThreeLine are represented by current DATA control-line
           resources and ConstraintIndex; they are not separate World Entity
           classes.

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

[v5.0] GeoSPARQL alignment:
          - GeoPredicates class for standard geometry representation
          - EntityTypes.l1_static(), geo_feature_types(), geo_subclass_decls() for TBox grouping
          - Relations.spatial(), SemanticPredicates.cognition_predicates() for clone_static_layer
          - Entity types: 18 total (active)
    L1: Parcel, Zone, Village, Facility, Road, AdministrativeBoundary,
                ContourLine, WaterBody,
                AdministrativeVillage, ResidentialCluster, GisLayerSet, PlaceRef, RasterDataset
            L3: ZoneTarget, FacilityTarget, AxisTarget, RoadTarget
            L4: PlannedParcel, PlannedZone, PlannedFacility, PlannedRoad, PlannedAxis

Relations: 8 total (v4.9 GeoSPARQL aligned)
  Spatial: geo:sfTouches, pln:nearby, pln:near, pln:same_coordinate,
           pln:co_located, pln:overlaps, pln:connected_via_road,
           geo:sfWithin, geo:sfIntersects, geo:sfContains
  Semantic: pln:derived_from, pln:serves
  (within_zone, designated_as and delineates are not World Model predicates)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote

from rdflib import Literal, Namespace, URIRef

PLN = Namespace("http://village-planning.org/ontology#")
PLN_NS = "http://village-planning.org/ontology#"
GEO = Namespace("http://www.opengis.net/ont/geosparql#")


class ThreeLineSubtypes:
    """Current DATA vocabulary for the four 三线 ControlLine subtypes.

    These are stable source-role vocabulary values, not a Bundle API.
    Three-lines are法定约束底数 (statutory constraint base data), not derived:
      ecological_redline:    生态保护红线 (state-mandated)
      farmland_redline:      永久基本农田 (subset of 耕地保护红线, highest priority)
      urban_dev_boundary:    城镇开发边界 (city-level transmission, often missing at village)
      village_construction_boundary: 村庄建设边界 ZJDJSFWX (village-level, parallel to UDB)
    """
    ECOLOGICAL_REDLINE = "ecological_redline"
    FARMLAND_REDLINE = "farmland_redline"
    URBAN_DEV_BOUNDARY = "urban_dev_boundary"
    VILLAGE_CONSTRUCTION_BOUNDARY = "village_construction_boundary"


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
        entity_type = quote(str(entity_type), safe="-._~")
        bsm = quote(str(bsm), safe="-._~")
        version = quote(str(version), safe="-._~")
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
    """Active entity type URIs for the planning ontology (v6.0).

    Business feature types are separate from World Model support types.
    v4.8: LayerGroup added - virtual entity aggregating layer-group membership
          for layer-card-level queries (not a spatial entity, carries no BSM).
    v6.0: ThreeLine NOT added as separate entity - the four 三线 subtypes are
          ControlLine subclasses (EcologicalRedline, FarmlandProtection,
          UrbanDevBoundary, VillageDevBoundary). Added FunctionalZone for
          vocabulary-driven custom functional zones (planning_intent overlay)."""
    # L1: Static entities (现状)
    Parcel = PLN.Parcel
    Zone = PLN.Zone
    Village = PLN.Village
    Facility = PLN.Facility
    Road = PLN.Road
    AdministrativeBoundary = PLN.AdministrativeBoundary
    ContourLine = PLN.ContourLine
    WaterBody = PLN.WaterBody
    AdministrativeVillage = PLN.AdministrativeVillage
    ResidentialCluster = PLN.ResidentialCluster
    PlaceRef = PLN.PlaceRef
    ControlLine = PLN.ControlLine      # 控制线 (三线 + 灾害/洪涝/历史保护 等子类)
    GisLayerSet = PLN.GisLayerSet      # v4.8: virtual gis-layer aggregator
    RasterDataset = PLN.RasterDataset  # v4.audit: DEM/DOM raster entity
    # L3: Intent virtual entities (意图虚拟实体)
    ZoneTarget = PLN.ZoneTarget
    FacilityTarget = PLN.FacilityTarget
    AxisTarget = PLN.AxisTarget
    RoadTarget = PLN.RoadTarget
    LinearTarget = PLN.LinearTarget
    SiteAreaTarget = PLN.SiteAreaTarget
    # L4: Planned state (规划成果)
    PlannedParcel = PLN.PlannedParcel
    PlannedZone = PLN.PlannedZone
    PlannedFacility = PLN.PlannedFacility
    PlannedRoad = PLN.PlannedRoad
    PlannedAxis = PLN.PlannedAxis
    PlannedFeature = PLN.PlannedFeature
    FunctionalZone = PLN.FunctionalZone  # v6.0: 自定义功能分区 (vocabulary-driven)
    # World-model migration types. These are deliberately excluded from
    # ``all()``/``spatial_l1()``: they are identity/representation support
    # nodes, not legacy business feature classes or executable target types.
    WorldEntity = PLN.WorldEntity
    EntityPart = PLN.EntityPart
    SpatialRepresentation = PLN.SpatialRepresentation
    ExternalObservationSupport = PLN.ExternalObservationSupport
    SpatialSupportCluster = PLN.SpatialSupportCluster
    SourceDataset = PLN.SourceDataset
    DataCapability = PLN.DataCapability

    @classmethod
    def all(cls) -> list:
        """Return all active entity types, including spatial and planning types."""
        return [
            cls.Parcel, cls.Zone, cls.Village, cls.Facility, cls.Road, cls.WaterBody,
            cls.AdministrativeVillage, cls.ResidentialCluster, cls.ControlLine,
            cls.AdministrativeBoundary, cls.ContourLine, cls.GisLayerSet,
            cls.ZoneTarget, cls.FacilityTarget, cls.AxisTarget, cls.RoadTarget,
            cls.LinearTarget,
            cls.SiteAreaTarget,
            cls.PlannedParcel, cls.PlannedZone, cls.PlannedFacility,
            cls.PlannedRoad, cls.PlannedAxis, cls.PlannedFeature, cls.FunctionalZone,
        ]

    @classmethod
    def cognition_support_types(cls) -> list:
        """World-model support nodes kept separate from business feature types."""
        return [
            cls.WorldEntity,
            cls.EntityPart,
            cls.SpatialRepresentation,
            cls.ExternalObservationSupport,
            cls.SpatialSupportCluster,
            cls.SourceDataset,
            cls.DataCapability,
        ]

    @classmethod
    def spatial_l1(cls) -> list:
        """L1 spatial entity types (have geometry, carry BSM). Excludes GisLayerSet."""
        return [
            cls.Parcel, cls.Zone, cls.Village, cls.Facility, cls.Road,
            cls.AdministrativeBoundary, cls.ContourLine, cls.WaterBody,
            cls.AdministrativeVillage, cls.ResidentialCluster, cls.ControlLine,
        ]

    @classmethod
    def l1_static(cls) -> set:
        """L1 entity types that persist in the static (cacheable) layer."""
        return {
            cls.AdministrativeVillage, cls.Parcel, cls.Road,
            cls.AdministrativeBoundary, cls.ContourLine, cls.WaterBody,
            cls.Facility, cls.ControlLine,
            cls.ResidentialCluster, cls.Zone, cls.GisLayerSet,
            cls.PlaceRef, cls.RasterDataset,
        }

    @classmethod
    def geo_feature_types(cls) -> list:
        """L1 entity types that are geo:Feature subclasses (have real geometry)."""
        return [
            cls.Parcel, cls.Road, cls.AdministrativeBoundary, cls.ContourLine,
            cls.WaterBody, cls.Facility, cls.ControlLine,
            cls.ResidentialCluster, cls.Zone,
            cls.PlaceRef,
        ]

    @classmethod
    def geo_subclass_decls(cls) -> list:
        """List of (pln_type, geo_type) pairs for rdfs:subClassOf declarations."""
        return [(t, GEO.Feature) for t in cls.geo_feature_types()]


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
    near = PLN.near
    same_coordinate = PLN.same_coordinate
    co_located = PLN.co_located
    overlaps = PLN.overlaps
    connected_via_road = PLN.connected_via_road
    sfWithin = GEO.sfWithin
    sfIntersects = GEO.sfIntersects
    sfContains = GEO.sfContains
    # Planning semantics
    derived_from = PLN.derived_from
    serves = PLN.serves
    # Active extension predicate (used in layer1.py)
    connects = PLN.connects
    # Cognition-only support relation.  A support cluster is an indexable
    # spatial co-location hint, never a WorldEntity or executable geometry.
    supports_entity = PLN.supports_entity

    @classmethod
    def all(cls) -> list:
        """Active relations (8)."""
        return [
            cls.sfTouches, cls.nearby, cls.near, cls.same_coordinate,
            cls.co_located, cls.overlaps, cls.connected_via_road,
            cls.sfWithin, cls.sfIntersects, cls.sfContains,
            cls.derived_from, cls.serves,
        ]

    @classmethod
    def spatial(cls) -> set:
        """Spatial relation predicates (used in clone_static_layer)."""
        return {
            cls.sfTouches, cls.nearby, cls.near, cls.same_coordinate,
            cls.co_located, cls.overlaps, cls.connected_via_road,
            cls.sfWithin, cls.sfIntersects, cls.sfContains,
        }


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

    @classmethod
    def cognition_predicates(cls) -> set:
        """All cognition/semantic-enrichment predicates (used in clone_static_layer)."""
        return {
            cls.gis_type_ref, cls.geometry_kind, cls.semantic_group,
            cls.has_semantic_label, cls.contains_entity, cls.gis_description,
            cls.entity_count, cls.dominant_label,
            cls.taxonomic_parent, cls.legal_constraint, cls.allowed_operations,
            cls.overlap_pct,
        }


@dataclass(frozen=True)
class BusinessFeatureSelector:
    """Select source-backed business features by their complete GIS identity.

    ``rdf:type`` is a broad ontology class. Business queries use this selector
    so registry type, semantic group, geometry kind and source identity are
    all part of the selection contract.
    """

    gis_type_ref: str
    semantic_group: str
    geometry_kind: str

    @classmethod
    def current_road(cls) -> "BusinessFeatureSelector":
        """The authoritative selector for present-state transport roads."""
        return cls("road", "transport", GEOMETRY_LINE)

    @classmethod
    def current_facility(cls) -> "BusinessFeatureSelector":
        """The authoritative selector for present-state point facilities."""
        return cls("current_facility", "facility", GEOMETRY_POINT)

    def matches(self, graph, subject) -> bool:
        """Return whether ``subject`` satisfies this complete feature contract."""
        required_dimensions = (
            (SemanticPredicates.gis_type_ref, self.gis_type_ref),
            (SemanticPredicates.semantic_group, self.semantic_group),
            (SemanticPredicates.geometry_kind, self.geometry_kind),
        )
        if any((subject, predicate, Literal(value)) not in graph for predicate, value in required_dimensions):
            return False
        def has_non_empty_value(predicate) -> bool:
            return any(str(value).strip() for value in graph.objects(subject, predicate))

        if not has_non_empty_value(PLN.source_feature_id):
            return False
        has_dataset = any(
            has_non_empty_value(predicate)
            for predicate in (PLN.source_dataset, PLN.source_uri)
        )
        has_snapshot = any(
            has_non_empty_value(predicate)
            for predicate in (PLN.source_snapshot_ref, PLN.source_content_digest)
        )
        return has_dataset and has_snapshot

    def select(self, graph) -> Iterable[URIRef]:
        """Yield every graph resource satisfying this selector exactly."""
        for subject in graph.subjects(
            SemanticPredicates.gis_type_ref,
            Literal(self.gis_type_ref),
        ):
            if self.matches(graph, subject):
                yield subject


def select_business_features(graph, selector: BusinessFeatureSelector) -> list[URIRef]:
    """Materialize a complete-GIS-identity selection for a business query."""
    return list(selector.select(graph))


class GeoPredicates:
    """v5.0: GeoSPARQL standard predicates for geometry representation.

    Used to store centroid and bounding box as standard WKT literals,
    enabling interoperability with GeoSPARQL-aware tools.
    """
    hasCentroid = GEO.hasCentroid
    hasBoundingBox = GEO.hasBoundingBox
    hasGeometry = GEO.hasGeometry
    asWKT = GEO.asWKT
    wktLiteral = GEO.wktLiteral
    Feature = GEO.Feature
    Geometry = GEO.Geometry


class ProvenancePredicates:
    """v4.9: Encoding decision provenance predicates.

    These predicates record the decision chain for code mappings
    at the individual feature level.
    """
    decided_by = PLN.decided_by
    decision_confidence = PLN.decision_confidence
    decision_evidence = PLN.decision_evidence
    mapping_basis = PLN.mapping_basis
