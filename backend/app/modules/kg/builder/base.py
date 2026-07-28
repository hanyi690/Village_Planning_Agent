"""PlanningKG — 规划知识图谱构建器 (v4.6)

Skeleton class with build_from_bundle orchestrator + helper functions.
Layer-specific methods are inherited from mixin classes (see mixins.py).

Usage:
    kg = PlanningKG("金田村委会")
    kg.build_from_bundle(bundle=bundle, parcel_relations=relations,
                         intent=intent, planned_state=planned)
    result = kg.query("SELECT ?z WHERE { ?z a pln:Zone }")
"""
from __future__ import annotations

from typing import Any, List
from dataclasses import dataclass, field

from rdflib import Graph, Literal, RDF, URIRef
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, Relations
from ..memory import SemanticMemoryStore

from .mixins import Layer1Mixin, Layer2Mixin, Layer3Mixin, Layer4Mixin, QueryMixin

logger = get_logger(__name__)


@dataclass
class KGInputParcels:
    """Container for typed parcels consumed by KG builder.

    Callers should populate `parcels` directly from the Data layer
    (e.g., via DataCatalog.load_village_bundle or ingest_current_landuse).
    KG must not import from app.modules.data (architecture: Schema <- Data
    <- SpatialOps <- KG <- Agent; KG has no upward deps).
    """
    parcels: List[Any] = field(default_factory=list)


class PlanningKG(Layer1Mixin, Layer2Mixin, Layer3Mixin, Layer4Mixin, QueryMixin):
    """规划知识图谱: 基于 RDFLib 的轻量级图存储。

    [v4.6] Methods inherited from mixin classes. Build from bundle morphology
    groups directly (no ContextBlock dependency).
    """

    def __init__(self, village_name: str = ""):
        self.g = Graph()
        self.g.bind("pln", PLN)
        self.village_name = village_name
        self._parcel_count = 0
        self._constraint_index = None
        self.memory = SemanticMemoryStore()

    # ── Main entry point ──

    def build_from_bundle(self, bundle, parcel_relations=None,
                          intent=None, planned_state=None, constraint_index=None,
                          water_overlap=None, cross_type_relations=None):
        """Build KG from VillageBundle morphology groups.

        Layer 1-2: Static entities + spatial relations from bundle + parcel_relations.
        Layer 3:   Intent virtual entities from SpatialPlanningIntent (optional).
        Layer 4:   Planned state from PlannedState (optional).

        Args:
            constraint_index: Optional ConstraintIndex from spatial_ops.bridge,
                injected for constraint violation checking (architecture: KG
                does not import spatial_ops, receives it as a dependency).
            water_overlap: Optional dict from spatial_ops.bridge.compute_water_overlap(),
                mapping water_feature_id -> [covered_bsm, ...] for deduplication.
            cross_type_relations: Optional dict with "located_in"/"intersects"/"contains"
                lists, pre-computed by spatial_ops. If None, uses centroid heuristic.
        """
        self.g = Graph()
        self.g.bind("pln", PLN)
        self._parcel_count = 0
        self._constraint_index = constraint_index

        # Layer 1: each bundle layer -> one entity type
        self._add_village_entity(bundle.village_name)
        self._add_village_meta_from_bundle(bundle)
        self._add_parcels(bundle.polygons.get("landuse_current"))
        self.add_roads(bundle.lines.get("roads_current"))
        self._add_water_bodies(bundle.polygons.get("water_bodies"), water_overlap=water_overlap or {})
        self._add_facilities_from_typed(bundle.points.get("facilities_current"))
        self._add_facilities_from_annotations(bundle.points.get("annotations_current"))
        self.add_annotations(bundle.points.get("annotations_current"))
        self._add_control_lines_from_typed(bundle.points, bundle.polygons)
        self._add_planning_elements_from_typed(bundle.polygons)
        self._add_residential_clusters_from_typed(
            bundle.polygons.get("landuse_current"),
            bundle.points.get("annotations_current"),
        )
        self.add_terrain(getattr(bundle.rasters, 'slope', None))

        # v4.8.1: additional bundle geometry groups
        self._add_protection_polygons(bundle.polygons)
        self._add_buildings(bundle.points.get("buildings"))
        self._add_terrain_entities(bundle.lines, bundle.points)
        self._add_boundaries(bundle.polygons, bundle.lines)
        self._add_natural_resource_zones(bundle.polygons)

        # Spatial relations (computed from geometry)
        self._add_parcel_relations(parcel_relations)

        # v4.8.1: cross-type spatial relations — auto-compute from bundle by default
        if cross_type_relations is None and bundle is not None:
            try:
                from app.modules.spatial_ops.bridge import compute_cross_layer_relations
                computed = compute_cross_layer_relations(bundle)
                if computed:
                    cross_type_relations = computed
                    total = sum(len(v) for v in computed.values())
                    logger.info("[build_from_bundle] Auto-computed %d cross-type relations", total)
            except ImportError:
                logger.warning(
                    "[build_from_bundle] spatial_ops.bridge not available — "
                    "falling back to centroid heuristic for cross-type relations"
                )
        self._add_cross_type_relations(cross_type_relations)

        # v4.8: GIS layer virtual entities + semantic enrichment
        self._add_gis_layer_groups()
        self._add_semantic_enrichment()

        # Layer 3: intent virtual entities
        if intent is not None:
            self.build_intent_layer(intent)

        # Layer 4: planned state
        if planned_state is not None:
            self._apply_planned_state(planned_state)

        logger.info("[PlanningKG] Built from bundle: %d parcels, %d triples",
                    self._parcel_count, len(self.g))
        return self

    # ── Clone / cache ──

    def clone_static_layer(self):
        new_kg = PlanningKG(village_name=self.village_name)
        new_kg.g = Graph()
        new_kg.g.bind("pln", PLN)
        new_kg._constraint_index = self._constraint_index

        l1_types = {
            EntityTypes.AdministrativeVillage, EntityTypes.Parcel,
            EntityTypes.Road,
            EntityTypes.WaterBody, EntityTypes.Facility,
            EntityTypes.ControlLine, EntityTypes.ResidentialCluster, EntityTypes.Zone,
            EntityTypes.GisLayerSet,  # v4.8: include GisLayerSet virtual entities
        }

        l1_subjects = set()
        for t in l1_types:
            for s in self.g.subjects(RDF.type, t):
                l1_subjects.add(s)
        l1_subjects.add(PLN.village)

        spatial_predicates = {PLN.touches, PLN.nearby, PLN.connected_via_road}

        # v4.8.2: predicates that should be cloned (gis-type + semantic-enrichment + GisLayerSet)
        from ..ontology import SemanticPredicates, Relations
        cognition_predicates = {
            SemanticPredicates.gis_type_ref, SemanticPredicates.geometry_kind,
            SemanticPredicates.semantic_group, SemanticPredicates.has_semantic_label,
            SemanticPredicates.contains_entity, SemanticPredicates.gis_description,
            SemanticPredicates.entity_count, SemanticPredicates.dominant_label,
            PLN.gis_description_enriched,
            SemanticPredicates.taxonomic_parent, SemanticPredicates.legal_constraint,
            SemanticPredicates.allowed_operations,
            Relations.intersects, Relations.contains, SemanticPredicates.overlap_pct,
        }

        for s, p, o in self.g.triples((None, None, None)):
            if s in l1_subjects or p in spatial_predicates or p in cognition_predicates:
                new_kg.g.add((s, p, o))
        new_kg._parcel_count = self._parcel_count
        return new_kg

    def print_summary(self):
        print(f"\n=== Planning KG Summary ===")
        print(f"  Parcels: {self._parcel_count}")
        print(f"  Total triples: {len(self.g)}")