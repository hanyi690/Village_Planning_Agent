from __future__ import annotations

from types import SimpleNamespace

from app.contracts.ports.place_resolution_contracts import PlaceResolutionCandidate
from app.contracts.spatial.spatial_reference_contracts import RefObject, SpatialReferenceSpec
from app.domain.ground.aggregate import ground_aggregate
from app.evidence.retrieval.evidence_graph import EvidenceGraph


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


def _context(index, parcels):
    return SimpleNamespace(
        session_id="spatial-domain-test",
        version=1,
        kg_version=2,
        gazetteer=None,
        location_facts=[],
        kg=None,
        ports=SimpleNamespace(spatial_query=None),
        workspace=SimpleNamespace(
            points=SimpleNamespace(get=lambda key: []),
            polygons=SimpleNamespace(get=lambda key: parcels if key == "landuse_current" else []),
            snapshot=SimpleNamespace(digest="bundle-domain-test"),
        ),
        current_parcels=lambda: parcels,
        evidence_graph=None,
        grounded_anchors=[],
        village_anchors=[],
        village_name="测试村",
        data_snapshot=SimpleNamespace(digest="bundle-domain-test"),
        l1_snapshot_ref="l1:test",
    )


def test_ambiguous_semantic_recall_stays_as_one_planning_domain():
    parcels = [
        _parcel("P-1", 116.0, 24.0, 116.01, 24.01),
        _parcel("P-2", 116.01, 24.0, 116.02, 24.01),
    ]

    class _Index:
        def resolve_mention(self, mention, role="unknown", hints=""):
            return SimpleNamespace(
                status="ambiguous",
                candidates=[
                    PlaceResolutionCandidate(
                        entity_ref="entity:大地块甲",
                        entity_type="parcel_set",
                        canonical_name="大地块甲",
                        source_bsms=["P-1"],
                        score=0.62,
                    ),
                    PlaceResolutionCandidate(
                        entity_ref="entity:大地块乙",
                        entity_type="parcel_set",
                        canonical_name="大地块乙",
                        source_bsms=["P-2"],
                        score=0.60,
                    ),
                ],
                query_trace=[],
            )

    context = _context(_Index(), parcels)
    context.evidence_graph = EvidenceGraph(context, index=_Index())
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(kind="place_name", filter={"label_contains": "大地块"}),
        target_id="target-large-area",
    )

    result = ground_aggregate([spec], context)

    assert not result.unresolved
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.source_parcels == ["P-1", "P-2"]
    assert candidate.geometry is not None
    assert candidate.geometry.spatial_domain_kind == "parcel_set"
    assert candidate.candidate_bbox == (116.0, 24.0, 116.02, 24.01)
    assert candidate.available_area_ha == 2.0

    corridor_result = ground_aggregate(
        [spec],
        context,
        target_metadata={
            "target-large-area": {
                "target_kind": "road",
                "expected_output_kind": "line",
            }
        },
    )
    corridor = corridor_result.candidates[0]
    assert corridor.geometry.spatial_domain_kind == "corridor"
    assert corridor.geometry.role == "corridor_candidate"


def test_ambiguous_facility_context_uses_related_parcels_for_grounding_domain():
    parcels = [_parcel("P-1", 116.0, 24.0, 116.01, 24.01)]

    class _Index:
        def resolve_mention(self, mention, role="unknown", hints=""):
            return SimpleNamespace(
                status="ambiguous",
                candidates=[
                    PlaceResolutionCandidate(
                        entity_ref="entity:公共服务点",
                        entity_type="facility",
                        canonical_name="公共服务点",
                        related_parcel_bsms=["P-1"],
                        source_bsms=[],
                        score=0.55,
                    )
                ],
                query_trace=[],
            )

    context = _context(_Index(), parcels)
    context.evidence_graph = EvidenceGraph(context, index=_Index())
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(kind="place_name", filter={"label_contains": "公共服务点"}),
        target_id="target-fuzzy-facility",
    )

    result = ground_aggregate([spec], context)

    assert len(result.candidates) == 1
    assert result.candidates[0].source_parcels == ["P-1"]
    assert result.candidates[0].geometry.spatial_domain_kind == "parcel_extent"


def test_grounding_recall_passes_semantic_hints_into_evidence_graph():
    calls = []

    class _Index:
        def resolve_mention(self, mention, role="unknown", hints=""):
            calls.append((mention, role, hints))
            return SimpleNamespace(
                status="resolved",
                candidates=[
                    PlaceResolutionCandidate(
                        entity_ref="entity:村北水点",
                        entity_type="facility",
                        canonical_name="水点",
                        source_bsms=["P-1"],
                        score=0.9,
                    )
                ],
                query_trace=[],
            )

    context = _context(_Index(), [_parcel("P-1", 116.0, 24.0, 116.01, 24.01)])
    graph = EvidenceGraph(context, index=_Index())
    assert graph.candidate_bsms(
        "水点", include_ambiguous=True, role="facility", hints="社前村 北"
    ) == ["P-1"]
    assert calls[-1] == ("水点", "facility", "社前村 北")


def test_facility_feature_bsm_does_not_replace_related_parcel_domain():
    from app.contracts.domain.l1_contracts import L1LocationFact

    parcel = _parcel("P-1", 116.0, 24.0, 116.01, 24.01)
    point = SimpleNamespace(
        bsm="F-1",
        geometry={"type": "Point", "coordinates": [116.005, 24.005]},
    )

    class _Index:
        def resolve_mention(self, mention, role="unknown", hints=""):
            return SimpleNamespace(
                status="resolved",
                candidates=[
                    PlaceResolutionCandidate(
                        entity_ref="entity:祠堂",
                        entity_type="facility",
                        canonical_name="祠堂",
                        feature_bsm="F-1",
                        source_bsms=["P-1"],
                        related_parcel_bsms=["P-1"],
                        geometry_ref="POINT(116.005 24.005)",
                        score=0.95,
                    )
                ],
                query_trace=[],
            )

    context = _context(_Index(), [parcel])
    context.location_facts = [
        L1LocationFact(
            mention="祠堂",
            normalized_name="祠堂",
            role="facility",
            confidence=0.9,
        )
    ]
    context.workspace.points = SimpleNamespace(
        get=lambda key: [point] if key == "facilities_current" else []
    )
    context.evidence_graph = EvidenceGraph(context, index=_Index())
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(kind="place_name", filter={"label_contains": "祠堂"}),
        target_id="target-facility",
    )

    result = ground_aggregate(
        [spec],
        context,
        target_metadata={"target-facility": {"target_kind": "facility", "expected_output_kind": "point"}},
    )

    candidate = result.candidates[0]
    assert candidate.source_parcels == ["P-1"]
    assert candidate.geometry.kind == "point"
    assert candidate.geometry.feature_bsms == ["F-1"]
