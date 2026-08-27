"""KGBuilder - composition orchestrator for PlanningKG construction.

Replaces the multi-inheritance mixin pattern. PlanningKG holds only data
(RDF graph + memory); KGBuilder holds all construction logic.

Aligns with BHoM principle: functionality separated from types.
"""
from __future__ import annotations

import sys
from typing import Any, Optional

from rdflib import Literal, RDF

from app.infrastructure.logging import get_logger
from ..ontology import PLN, GEO, EntityTypes, Relations, SemanticPredicates
from ..memory import SemanticMemoryStore
from .registry import BuildContext, _ordered_builders, _get_bundle_features
from .base import PlanningKG

logger = get_logger(__name__)


class KGBuilder:
    """KG construction orchestrator. Composes PlanningKG via composition."""

    def __init__(self, village_name: str = ""):
        self.kg = PlanningKG(village_name)
        self._ctx: Optional[BuildContext] = None

    def build_from_bundle(self, bundle, parcel_relations=None,
                          intent=None, planned_state=None,
                          constraint_index=None, water_overlap=None,
                          cross_type_relations=None) -> PlanningKG:
        self.kg._reset_graph(constraint_index)
        self._ctx = self._make_ctx(bundle, constraint_index, water_overlap)

        self._build_village_entity(bundle)
        self._build_entities(bundle)
        self._attach_bundle_feature_identity(bundle)

        self._build_relations(bundle, parcel_relations, cross_type_relations)
        self._build_enrichment()

        if intent is not None:
            self.build_intent_layer(intent)

        if planned_state is not None:
            self.apply_planned_state(planned_state)

        # Publish one indexed lookup projection after all entity and relation
        # writes.  Evidence retrieval uses this projection instead of
        # repeatedly scanning RDFLib triples on the hot path.
        self.kg.rebuild_spatial_index()

        logger.info("[KGBuilder] Built: %d parcels, %d triples",
                    self.kg._parcel_count, len(self.kg.g))
        return self.kg

    def _attach_bundle_feature_identity(self, bundle) -> None:
        """Complete identity for bundle-backed entities before cognition/indexing.

        A source adapter normally supplies ``source_feature_id`` and source
        digests.  Synthetic/demo bundles still have authoritative generated
        BSMs, however, and must not disappear from business-feature queries
        merely because they lack an upstream file URI.  Use the immutable
        bundle snapshot as their provenance boundary; never replace an
        existing source identity.
        """
        digest = str(bundle.spatial_snapshot_digest() or "").strip()
        if not digest:
            return
        for subject, _, bsm_literal in list(
            self.kg.g.triples((None, PLN.bsm, None))
        ):
            bsm = str(bsm_literal or "").strip()
            if not bsm:
                continue
            layer = str(
                self.kg.g.value(subject, SemanticPredicates.gis_type_ref) or ""
            ).strip()
            if not layer:
                layer = str(self.kg.g.value(subject, RDF.type) or "").rsplit("#", 1)[-1]
            source_feature_id = str(
                self.kg.g.value(subject, PLN.source_feature_id) or ""
            ).strip()
            if not source_feature_id:
                source_feature_id = f"bundle:{layer or 'feature'}:{bsm}"
                self.kg.g.add((subject, PLN.source_feature_id, Literal(source_feature_id)))
            if not any(
                str(value).strip()
                for value in self.kg.g.objects(subject, PLN.source_dataset)
            ) and not any(
                str(value).strip() for value in self.kg.g.objects(subject, PLN.source_uri)
            ):
                self.kg.g.add((subject, PLN.source_dataset, Literal("village_bundle")))
            if not any(
                str(value).strip()
                for value in self.kg.g.objects(subject, PLN.source_snapshot_ref)
            ) and not any(
                str(value).strip()
                for value in self.kg.g.objects(subject, PLN.source_content_digest)
            ):
                self.kg.g.add((subject, PLN.source_snapshot_ref, Literal(digest)))
            if layer and not any(
                str(value).strip() for value in self.kg.g.objects(subject, PLN.source_layer)
            ):
                self.kg.g.add((subject, PLN.source_layer, Literal(layer)))

    def _make_ctx(self, bundle, constraint_index, water_overlap) -> BuildContext:
        bbox = None
        meta = getattr(bundle, "metadata", None)
        if meta:
            try:
                bbox = meta.bbox_wgs84.as_tuple()
            except Exception:
                pass
        return BuildContext(
            village_name=bundle.village_name,
            bbox=bbox,
            constraint_index=constraint_index,
            provenance={"water_overlap": water_overlap or {}},
        )

    def _build_village_entity(self, bundle):
        from .layer1_core import (
            add_village_entity, add_village_meta, add_bundle_metadata,
            add_facilities_from_annotations, add_annotations,
            add_control_lines_from_typed, add_planning_elements_from_typed,
            add_terrain,
        )
        from .layer1_extended import (
            add_protection_polygons, add_terrain_entities,
            add_boundaries, add_natural_resource_zones,
        )
        add_village_entity(self.kg, bundle.village_name)
        add_village_meta(self.kg, bundle)
        add_bundle_metadata(self.kg, bundle)
        add_facilities_from_annotations(self.kg, bundle.points.get("annotations_current"))
        add_annotations(self.kg, bundle.points.get("annotations_current"))
        add_control_lines_from_typed(self.kg, bundle.points, bundle.polygons)
        add_planning_elements_from_typed(self.kg, bundle.polygons)
        add_terrain(self.kg, getattr(bundle.rasters, 'slope', None))
        add_protection_polygons(self.kg, bundle.polygons)
        add_terrain_entities(self.kg, bundle.lines, bundle.points)
        add_boundaries(self.kg, bundle.polygons, bundle.lines)
        add_natural_resource_zones(self.kg, bundle.polygons)

    def _build_entities(self, bundle):
        from app.data.model.layer_registry import GIS_LAYER_REGISTRY
        for spec in _ordered_builders():
            entry = GIS_LAYER_REGISTRY.get(spec.gis_type_ref)
            if not entry:
                continue
            features = _get_bundle_features(bundle, entry)
            if not features:
                continue
            try:
                report = spec.fn(self.kg, features, gis_type_ref=spec.gis_type_ref,
                                 entry=entry, ctx=self._ctx)
            except TypeError:
                report = spec.fn(self.kg, features, gtype_ref=spec.gis_type_ref,
                                 entry=entry, ctx=self._ctx)
            if report and isinstance(report, dict):
                logger.debug("[entity] %s: %s", spec.gis_type_ref, report)

    def _build_relations(self, bundle, parcel_relations, cross_type_relations):
        from .layer2 import add_parcel_relations, add_cross_type_relations
        add_parcel_relations(self.kg, parcel_relations)

        if cross_type_relations is None and bundle is not None:
            try:
                from app.spatial.query.bridge import compute_cross_layer_relations
                computed = compute_cross_layer_relations(bundle)
                if computed:
                    cross_type_relations = computed
                    total = sum(len(v) for v in computed.values())
                    logger.info("[KGBuilder] Auto-computed %d cross-type relations", total)
            except Exception:
                logger.warning(
                    "[KGBuilder] cross-type computation failed (%s) - using centroid heuristic",
                    sys.exc_info()[1],
                )
        add_cross_type_relations(self.kg, cross_type_relations)

    def _build_enrichment(self):
        from .enrichment import add_gis_layer_groups, add_semantic_enrichment
        add_gis_layer_groups(self.kg)
        add_semantic_enrichment(self.kg)

    def build_intent_layer(self, intent) -> None:
        from .layer3 import build_intent_layer
        build_intent_layer(self.kg, intent)

    def clear_intent_layer(self) -> None:
        from .layer3 import clear_intent_layer
        clear_intent_layer(self.kg)

    def apply_planned_state(self, planned_state) -> None:
        from .layer4 import apply_planned_state
        apply_planned_state(self.kg, planned_state)

    @classmethod
    def build(cls, village_name: str, bundle, **kwargs) -> PlanningKG:
        return cls(village_name).build_from_bundle(bundle, **kwargs)
