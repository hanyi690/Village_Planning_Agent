from __future__ import annotations

from types import SimpleNamespace

from app.contracts.spatial.spatial_reference_contracts import (
    RefObject,
    ResolvedSpatialRef,
    SpatialReferenceSpec,
)
from app.contracts.spatial.grounding_contracts import GroundedAnchor
from app.domain.ground.aggregate import build_candidate_sites, ground_aggregate
from app.domain.ground.candidate_domain_builder import build_candidate_domains
from app.spatial.grounding.resolver import SpatialResolver


def _parcel(bsm: str, west: float, south: float, east: float, north: float):
    return SimpleNamespace(
        bsm=bsm,
        area_sqm=10000.0,
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [west, south], [west, north], [east, north],
                [east, south], [west, south],
            ]],
        },
    )


class _Gazetteer:
    def __init__(self, entries: dict[str, SimpleNamespace]):
        self._entries = entries

    def resolve(self, token: str, fuzzy: bool = False):
        if token in self._entries:
            return self._entries[token]
        if not fuzzy:
            return None
        normalized = token.rstrip("村自然组")
        for key, entry in self._entries.items():
            if normalized and normalized in key:
                return entry
        return None


def _context(parcels, *, gazetteer=None):
    return SimpleNamespace(
        session_id="search-scope-boundary",
        version=1,
        kg=None,
        gazetteer=gazetteer,
        location_facts=[],
        ports=SimpleNamespace(spatial_query=None),
        workspace=SimpleNamespace(
            points={},
            polygons=SimpleNamespace(
                get=lambda key: parcels if key == "landuse_current" else []
            ),
            snapshot=SimpleNamespace(digest="bundle-search-scope"),
        ),
        current_parcels=lambda: parcels,
        evidence_graph=None,
        grounded_anchors=[],
        village_anchors=[],
        village_name="测试村",
        data_snapshot=SimpleNamespace(digest="bundle-search-scope"),
        l1_snapshot_ref="l1:test",
        constraint_index=None,
    )


def test_coarse_village_fallback_only_produces_search_scope() -> None:
    parcels = [
        _parcel("P-1", 116.0, 24.0, 116.01, 24.01),
        _parcel("P-2", 116.01, 24.0, 116.02, 24.01),
    ]
    gazetteer = _Gazetteer({
        "社前村": SimpleNamespace(
            bsms=["P-1", "P-2"],
            centroid=(116.01, 24.005),
            source="fixture",
            confidence=0.8,
            entity_uri="entity:社前村",
        )
    })
    context = _context(parcels, gazetteer=gazetteer)
    spec = SpatialReferenceSpec(
        type="topological",
        topo="sfWithin",
        reference=RefObject(kind="village", filter={"label_contains": "社前"}),
        target_id="target-village-scope",
    )

    resolved = SpatialResolver(context).resolve_spec(spec)

    assert resolved.final_bsms == []
    assert resolved.reference_geometries == []
    assert resolved.search_scope is not None
    assert resolved.search_scope.scope_bsms == ["P-1", "P-2"]
    assert resolved.search_scope.scope_type == "village_scope"
    assert resolved.search_scope.candidate_materialization_allowed is False

    result = ground_aggregate([spec], context)

    assert result.candidates == []
    assert result.unresolved[0].code == "search_scope_not_materialized"
    assert result.problem is not None
    assert result.problem.candidate_domains == []
    assert result.problem.target_domains[0].target_id == "target-village-scope"
    assert result.problem.target_domains[0].status == "unresolved"
    assert result.spatial_query_evidence[0].query_params["search_scope"]["scope_bsms"] == [
        "P-1",
        "P-2",
    ]
    assert any(
        item.startswith("search_scope:target-village-scope:")
        for item in (result.provenance.trace if result.provenance is not None else [])
    )


def test_matching_village_scope_anchor_cannot_rematerialize_search_scope() -> None:
    parcels = [
        _parcel("P-1", 116.0, 24.0, 116.01, 24.01),
        _parcel("P-2", 116.01, 24.0, 116.02, 24.01),
    ]
    gazetteer = _Gazetteer({
        "社前村": SimpleNamespace(
            bsms=["P-1", "P-2"],
            centroid=(116.01, 24.005),
            source="fixture",
            confidence=0.8,
            entity_uri="entity:社前村",
        )
    })
    context = _context(parcels, gazetteer=gazetteer)
    context.grounded_anchors = [
        GroundedAnchor(
            normalized_name="社前村",
            mention="社前村",
            entity_ref="entity:社前村",
            source_bsms=["P-1", "P-2"],
            geometry_ref="village_anchor:社前村",
            geometry_granularity="village_scope",
            status="resolved",
        )
    ]
    spec = SpatialReferenceSpec(
        type="topological",
        topo="sfWithin",
        reference=RefObject(kind="village", filter={"label_contains": "社前"}),
        target_id="target-village-anchor-scope",
    )

    result = ground_aggregate([spec], context)

    assert result.candidates == []
    assert result.problem is not None
    assert result.problem.candidate_domains == []
    assert result.unresolved[0].code == "search_scope_not_materialized"


def test_anchor_wkt_without_identity_or_snapshot_is_not_materialized(monkeypatch) -> None:
    context = _context([_parcel("P-1", 116.0, 24.0, 116.01, 24.01)])
    context.grounded_anchors = [
        GroundedAnchor(
            normalized_name="未绑定设施",
            mention="未绑定设施",
            geometry_ref="POINT (116.005 24.005)",
            geometry_granularity="exact_feature",
            status="unresolved",
        )
    ]
    spec = SpatialReferenceSpec(
        type="place_name",
        reference=RefObject(
            kind="place_name",
            filter={"label_contains": "未绑定设施"},
        ),
        target_id="target-anchor-authority",
    )

    monkeypatch.setattr(
        SpatialResolver,
        "resolve_spec",
        lambda self, spec, **kwargs: ResolvedSpatialRef(),
    )

    result = ground_aggregate(
        [spec],
        context,
        target_metadata={
            "target-anchor-authority": {
                "target_kind": "facility",
                "expected_output_kind": "point",
            }
        },
    )

    assert result.candidates == []
    assert result.problem is not None
    assert result.problem.candidate_domains == []
    assert result.unresolved[0].code == "spatial_reference_unresolved"
    authority = result.spatial_query_evidence[0].query_params["anchor_authority"]
    assert authority["reason"] == "grounded_anchor_missing_authority"
    assert set(authority["missing_requirements"]) == {
        "explicit_feature_identity",
        "source_snapshot",
    }
    assert "grounded_anchor_missing_authority" in result.unresolved[0].detail


def test_coarse_entity_anchor_wkt_with_snapshot_is_not_materialized(monkeypatch) -> None:
    context = _context([_parcel("P-1", 116.0, 24.0, 116.01, 24.01)])
    context.grounded_anchors = [
        GroundedAnchor(
            normalized_name="粗粒度村",
            mention="粗粒度村域",
            entity_ref="entity:village:coarse",
            l1_snapshot_ref="l1:coarse-anchor",
            geometry_ref="POINT (116.005 24.005)",
            geometry_granularity="village_scope",
            status="resolved",
        )
    ]
    spec = SpatialReferenceSpec(
        type="place_name",
        reference=RefObject(
            kind="place_name",
            filter={"label_contains": "粗粒度村域"},
        ),
        target_id="target-coarse-anchor",
    )

    monkeypatch.setattr(
        SpatialResolver,
        "resolve_spec",
        lambda self, spec, **kwargs: ResolvedSpatialRef(),
    )

    result = ground_aggregate(
        [spec],
        context,
        target_metadata={
            "target-coarse-anchor": {
                "target_kind": "facility",
                "expected_output_kind": "point",
            }
        },
    )

    assert result.candidates == []
    assert result.problem is not None
    assert result.problem.candidate_domains == []
    assert result.unresolved[0].code == "spatial_reference_unresolved"
    authority = result.spatial_query_evidence[0].query_params["anchor_authority"]
    assert authority["reason"] == "grounded_anchor_missing_identity"
    assert "explicit_feature_identity" in authority["missing_requirements"]
    assert "exact_feature_granularity" in authority["missing_requirements"]
    assert "source_snapshot" not in authority["missing_requirements"]
    assert authority["identity"]["entity_ref"] == "entity:village:coarse"


def test_sourced_exact_anchor_wkt_preserves_authority_lineage(monkeypatch) -> None:
    context = _context([_parcel("P-1", 116.0, 24.0, 116.01, 24.01)])
    context.grounded_anchors = [
        GroundedAnchor(
            normalized_name="已绑定设施",
            mention="已绑定设施",
            entity_ref="entity:facility:exact",
            feature_bsm="FAC-1",
            source_feature_id="facility-feature-1",
            source_layer="facilities_current",
            source_bsms=["P-1"],
            l1_fact_refs=["fact:facility:exact"],
            relation_refs=["relation:facility:parcel"],
            l1_snapshot_ref="l1:anchor-exact",
            bundle_snapshot_digest="bundle:anchor-exact",
            geometry_ref="POINT (116.005 24.005)",
            geometry_granularity="exact_feature",
            status="resolved",
        )
    ]
    spec = SpatialReferenceSpec(
        type="place_name",
        reference=RefObject(
            kind="place_name",
            filter={"label_contains": "已绑定设施"},
        ),
        target_id="target-sourced-anchor",
    )

    monkeypatch.setattr(
        SpatialResolver,
        "resolve_spec",
        lambda self, spec, **kwargs: ResolvedSpatialRef(),
    )

    result = ground_aggregate(
        [spec],
        context,
        target_metadata={
            "target-sourced-anchor": {
                "target_kind": "facility",
                "expected_output_kind": "point",
            }
        },
    )

    assert len(result.candidates) == 1
    geometry = result.candidates[0].geometry
    assert geometry is not None
    assert geometry.wkt == "POINT (116.005 24.005)"
    assert geometry.feature_bsms == ["FAC-1"]
    assert geometry.source_feature_ids == ["facility-feature-1"]
    assert geometry.entity_refs == ["entity:facility:exact"]
    assert geometry.relation_refs == ["relation:facility:parcel"]
    assert geometry.l1_fact_refs == ["fact:facility:exact"]
    assert geometry.l1_snapshot_ref == "l1:anchor-exact"
    assert geometry.bundle_snapshot_digest == "bundle:anchor-exact"
    authority = result.spatial_query_evidence[0].query_params["anchor_authority"]
    assert authority["reason"] == "grounded_anchor_authority_verified"
    assert authority["missing_requirements"] == []


def test_second_anchor_promotion_preserves_resolver_path(monkeypatch) -> None:
    import app.domain.ground.aggregate as aggregate_module

    context = _context([_parcel("P-1", 116.0, 24.0, 116.01, 24.01)])
    context.grounded_anchors = [
        GroundedAnchor(
            normalized_name="二次路径设施",
            mention="二次路径设施",
            entity_ref="entity:facility:second-path",
            feature_bsm="FAC-2",
            source_feature_id="facility-feature-2",
            source_layer="facilities_current",
            source_bsms=["P-1"],
            l1_snapshot_ref="l1:anchor-second-path",
            bundle_snapshot_digest="bundle:anchor-second-path",
            geometry_ref="POINT (116.005 24.005)",
            geometry_granularity="exact_feature",
            status="resolved",
        )
    ]
    spec = SpatialReferenceSpec(
        type="place_name",
        reference=RefObject(
            kind="place_name",
            filter={"label_contains": "二次路径设施"},
        ),
        target_id="target-second-anchor-path",
    )
    monkeypatch.setattr(
        SpatialResolver,
        "resolve_spec",
        lambda self, spec, **kwargs: ResolvedSpatialRef(
            final_bsms=["P-1"],
            provenance={"path": "resolver:second-path"},
        ),
    )
    captured: dict = {}
    original_build_candidate_sites = aggregate_module.build_candidate_sites

    def capture_resolved(*args, **kwargs):
        captured["provenance"] = dict(args[1].provenance)
        return original_build_candidate_sites(*args, **kwargs)

    monkeypatch.setattr(
        aggregate_module,
        "build_candidate_sites",
        capture_resolved,
    )

    result = ground_aggregate(
        [spec],
        context,
        target_metadata={
            "target-second-anchor-path": {
                "target_kind": "facility",
                "expected_output_kind": "point",
            }
        },
    )

    assert len(result.candidates) == 1
    assert captured["provenance"]["path"] == "grounded_anchor"
    assert captured["provenance"]["resolver_path"] == "resolver:second-path"


def test_downstream_candidate_domain_rejects_blocked_materialization() -> None:
    from app.contracts.spatial.candidate_geometry import CandidateGeometry
    from app.contracts.spatial.grounding_contracts import CandidateSite

    candidate = CandidateSite(
        site_id="blocked-site",
        target_ref="target-blocked",
        candidate_materialization_allowed=False,
        geometry=CandidateGeometry(
            target_id="target-blocked",
            kind="point",
            role="anchor_geometry",
            wkt="POINT (116 24)",
        ),
    )

    assert build_candidate_domains([candidate]) == []


def test_exact_polygon_candidate_behavior_is_unchanged() -> None:
    parcels = [_parcel("P-1", 0.0, 0.0, 1.0, 1.0)]
    candidates = build_candidate_sites(
        SpatialReferenceSpec(type="place_name", target_id="site-1"),
        ResolvedSpatialRef(
            final_bsms=["P-1"],
            reference_geometry_wkt="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
            spatial_domain_kind="exact_feature",
            confidence=0.95,
            provenance={"path": "kg:site"},
        ),
        0,
        _context(parcels),
        target_kind="site_area",
        expected_output_kind="polygon",
    )

    assert len(candidates) == 1
    assert candidates[0].source_parcels == ["P-1"]
    assert candidates[0].geometry is not None
    assert candidates[0].geometry.role == "execution_geometry"
    assert candidates[0].geometry.kind == "polygon"


def test_single_parcel_candidate_behavior_is_unchanged() -> None:
    parcels = [_parcel("P-1", 0.0, 0.0, 1.0, 1.0)]
    candidates = build_candidate_sites(
        SpatialReferenceSpec(type="place_name", target_id="site-1"),
        ResolvedSpatialRef(
            final_bsms=["P-1"],
            spatial_domain_kind="parcel_extent",
            confidence=0.7,
            provenance={"path": "evidence:candidates"},
        ),
        0,
        _context(parcels),
        target_kind="site_area",
        expected_output_kind="polygon",
    )

    assert len(candidates) == 1
    assert candidates[0].source_parcels == ["P-1"]
    assert candidates[0].geometry is not None
    assert candidates[0].geometry.generation_operation == "grounded_candidate"


def test_multiple_identifiable_parcels_still_split_into_alternatives() -> None:
    parcels = [
        _parcel("P-1", 0.0, 0.0, 1.0, 1.0),
        _parcel("P-2", 2.0, 0.0, 3.0, 1.0),
    ]
    candidates = build_candidate_sites(
        SpatialReferenceSpec(type="place_name", target_id="site-2"),
        ResolvedSpatialRef(
            final_bsms=["P-1", "P-2"],
            spatial_domain_kind="parcel_set",
            confidence=0.7,
            provenance={"path": "evidence:candidates"},
        ),
        0,
        _context(parcels),
        target_kind="site_area",
        expected_output_kind="polygon",
    )

    assert [candidate.source_parcels for candidate in candidates] == [["P-1"], ["P-2"]]
    assert [candidate.geometry.generation_operation for candidate in candidates] == [
        "grounded_parcel_alternative",
        "grounded_parcel_alternative",
    ]
