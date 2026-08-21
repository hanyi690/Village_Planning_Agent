"""Characterize real JinTian spatial queries at the EvidenceGraph boundary."""

from __future__ import annotations

import sys
from pathlib import Path


_SCRIPTS_ROOT = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from benchmark_real_evidence import _load_bundle  # noqa: E402


def test_real_bundle_graph_exposes_roads_and_parcel_bbox_without_geometry_copy() -> None:
    """Road scope and parcel bbox queries stay bundle-backed and bounded."""
    from app.evidence.index.place_evidence_index import PlaceEvidenceIndex
    from app.evidence.retrieval.evidence_graph import (
        EvidenceGraph,
        enrich_evidence_packet_with_spatial_graph,
    )
    from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
    from app.data.catalog.catalog import _derive_water_bodies_from_landuse
    from app.infrastructure.context.planning_context import PlanningContext
    from app.infrastructure.kg.manager import KGManager
    from app.spatial.model.workspace import SpatialWorkspace

    bundle, counts = _load_bundle()
    assert counts["current_road"] == 131
    assert counts["landuse_current"] == 660
    assert _derive_water_bodies_from_landuse(bundle) > 0

    manager = KGManager()
    session_id = "characterization-real-spatial-evidence"
    workspace = SpatialWorkspace.from_bundle(
        bundle,
        session_id=session_id,
        source="characterization",
    )
    try:
        kg = manager.get_or_build_kg(
            "金田村",
            bundle=bundle,
            session_id=session_id,
        )
        context = PlanningContext(
            session_id=session_id,
            village_name="金田村",
            version=1,
            workspace=workspace,
            data_snapshot=workspace.snapshot,
            kg=kg,
            kg_session_ref=session_id,
            kg_version=1,
        )
        graph = EvidenceGraph(
            context,
            index=PlaceEvidenceIndex.build(context),
        )
        context.evidence_graph = graph

        # Real-data proof for the inverse location path: this context has no
        # L1 facts or gazetteer binding for 炉池, so the only semantic anchors
        # are the four named geological-hazard points in the uploaded Bundle.
        from app.contracts.spatial.spatial_reference_contracts import (
            RefObject,
            SpatialReferenceSpec,
        )
        from app.spatial.grounding.resolver import SpatialResolver

        furnace_spec = SpatialReferenceSpec(
            type="attributive",
            reference=RefObject(
                kind="village",
                filter={"label_contains": "炉池"},
            ),
            target_id="real-furnace-village",
        )
        furnace_packet = enrich_evidence_packet_with_spatial_graph(
            EvidencePacket(request="炉池自然村在哪里"),
            context,
            query="炉池自然村在哪里",
            village_name="金田村",
            entity_scope=[],
            spatial_spec=furnace_spec,
        )
        assert len(furnace_packet.candidate_refs) == 4
        assert all(ref.identity.role == "hazard" for ref in furnace_packet.candidate_refs)
        assert all("炉池" in ref.identity.canonical_name for ref in furnace_packet.candidate_refs)
        assert all(ref.related_parcel_bsms for ref in furnace_packet.candidate_refs)

        furnace_scope = SpatialResolver(context).resolve_spec(
            furnace_spec,
            evidence_packet=furnace_packet,
        )
        assert furnace_scope.spatial_domain_kind == "village_scope"
        assert len(furnace_scope.final_bsms) == 26
        assert furnace_scope.provenance["scope_semantics"] == "inferred_from_spatial_evidence"
        assert furnace_scope.provenance["not_exact_village_boundary"] is True
        assert furnace_scope.provenance["anchor_cluster_count"] == 1
        assert furnace_scope.provenance["anchor_cluster_selection"] == "single_spatial_cluster"
        assert set(furnace_scope.feature_bsms) == {
            ref.identity.bundle_feature_bsm
            for ref in furnace_packet.candidate_refs
        }

        road_candidates = graph.query_scope_candidates(
            "金田村的道路",
            entity_scope=["roads"],
            max_candidates=16,
        )
        assert road_candidates
        assert len(road_candidates) <= 16
        assert all(candidate.role == "road" for candidate in road_candidates)
        assert all(candidate.feature_bsm for candidate in road_candidates)
        assert all(candidate.source_feature_id for candidate in road_candidates)
        assert all(
            candidate.source_layer in {"roads_current", "current_road", "transport", "road"}
            for candidate in road_candidates
        )
        assert all(
            str(candidate.geometry_ref or "").startswith("bundle://feature/")
            for candidate in road_candidates
        )
        assert all(
            "POINT(" not in str(candidate.geometry_ref or "")
            and "LINESTRING(" not in str(candidate.geometry_ref or "")
            for candidate in road_candidates
        )

        # A natural-village prefix can be present only inside a hazard-point
        # source label (for example 炉池赖木生).  The public scope query must
        # still return those Bundle-backed semantic anchors for GROUND; it
        # must not pretend the hazard point itself is the village boundary.
        hazard_candidates = graph.query_scope_candidates(
            "炉池自然村在哪里",
            entity_scope=["hazards"],
            max_candidates=16,
        )
        assert len(hazard_candidates) == 4
        assert all(candidate.role == "hazard" for candidate in hazard_candidates)
        assert all("炉池" in candidate.canonical_name for candidate in hazard_candidates)
        assert all(candidate.feature_bsm for candidate in hazard_candidates)
        assert all(candidate.related_parcel_bsms for candidate in hazard_candidates)

        # The same query remains cross-layer when the caller provides no
        # entity_scope.  The returned role is discovered from indexed source
        # labels; the caller does not need to know the source layer first.
        unscoped_hazard_candidates = graph.query_scope_candidates(
            "炉池",
            entity_scope=[],
            max_candidates=16,
        )
        assert len(unscoped_hazard_candidates) == 4
        assert all(candidate.role == "hazard" for candidate in unscoped_hazard_candidates)

        west_packet = enrich_evidence_packet_with_spatial_graph(
            EvidencePacket(request="金田村村西的道路"),
            context,
            query="金田村村西的道路",
            village_name="金田村",
            entity_scope=["roads"],
        )
        directional_trace = next(
            trace
            for trace in west_packet.query_trace
            if trace.get("step") == "directional_scope_hint"
        )
        assert directional_trace["value"] == "west"
        assert directional_trace["parser"] == "deterministic_scope"
        assert west_packet.candidate_refs
        assert len(west_packet.candidate_refs) <= 16
        assert west_packet.ambiguity_status == "multiple"
        assert all(ref.related_parcel_bsms for ref in west_packet.candidate_refs)

        water_candidates = graph.query_scope_candidates(
            "金田村的水体",
            entity_scope=["waters"],
            max_candidates=16,
        )
        assert water_candidates
        assert len(water_candidates) <= 16
        assert all(candidate.role == "water" for candidate in water_candidates)
        assert all(candidate.feature_bsm for candidate in water_candidates)
        assert all(
            str(candidate.geometry_ref or "").startswith("bundle://feature/")
            for candidate in water_candidates
        )

        parcels = list(bundle.polygons.get("landuse_current") or [])
        assert parcels
        first_parcel = parcels[0]
        first_bsm = str(first_parcel.bsm)
        from shapely.geometry import shape

        geometry = shape(first_parcel.geometry)
        bounds = tuple(float(value) for value in geometry.bounds)
        assert first_bsm in graph.query_parcel_bsms_in_bbox(bounds)

        bundle_feature = bundle.find_feature_by_bsm(road_candidates[0].feature_bsm)
        assert bundle_feature is not None
        assert bundle_feature[2].geometry is not None
        assert all(
            field not in road_candidates[0].model_dump(mode="json")
            for field in ("coordinates", "wkt", "geometry")
        )
    finally:
        manager.remove_session(session_id)
