from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.contracts.domain.l1_contracts import L1LocationFact
from app.contracts.ports.place_resolution_contracts import (
    PlaceResolutionCandidate,
)
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex
from app.evidence.retrieval.evidence_graph import EvidenceGraph


def _parcel(bsm: str, left: float, bottom: float) -> SimpleNamespace:
    return SimpleNamespace(
        bsm=bsm,
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [left, bottom],
                [left + 0.002, bottom],
                [left + 0.002, bottom + 0.002],
                [left, bottom + 0.002],
                [left, bottom],
            ]],
        },
        layer_type="landuse_current",
        _raw={"source_feature_id": f"parcel:{bsm}"},
    )


def _feature(
    *,
    bsm: str,
    source_feature_id: str,
    text: str,
    layer: str,
    lon: float,
    lat: float,
) -> SimpleNamespace:
    properties = {"text": text}
    if "hazard" in layer:
        properties = {"地质灾害点名称": text, "类型": "滑坡"}
    return SimpleNamespace(
        bsm=bsm,
        text=text,
        geometry={"type": "Point", "coordinates": [lon, lat]},
        properties=properties,
        _raw={"source_feature_id": source_feature_id},
    )


def _context(
    *,
    points: dict[str, list] | None = None,
    lines: dict[str, list] | None = None,
    gazetteer_entries: list | None = None,
    parcel_origins: tuple[tuple[float, float], tuple[float, float]] = (
        (116.072, 24.838),
        (116.075, 24.840),
    ),
) -> SimpleNamespace:
    parcel_a = _parcel(
        "44142621100000001001",
        *parcel_origins[0],
    )
    parcel_b = _parcel(
        "44142621100000001002",
        *parcel_origins[1],
    )
    parcels = [parcel_a, parcel_b]
    workspace = SimpleNamespace(
        points=points or {},
        lines=lines or {},
        polygons={"landuse_current": parcels},
        current_parcels=lambda: parcels,
        boundary=None,
        snapshot=SimpleNamespace(digest="supporting-evidence-bundle"),
    )
    entries = list(gazetteer_entries or [])
    village_by_name = {
        str(getattr(entry, "name", "")): entry for entry in entries
    }

    def resolve(name: str, fuzzy: bool = False):
        del fuzzy
        token = str(name).replace("自然村", "").replace("村", "")
        return village_by_name.get(token) or village_by_name.get(f"{token}村")

    context = SimpleNamespace(
        session_id="supporting-evidence-test",
        village_name="金田村",
        workspace=workspace,
        current_parcels=lambda: parcels,
        location_facts=[],
        l1_fact_records=[],
        kg=None,
        kg_version=0,
        l1_snapshot_ref="l1:test",
        data_snapshot=SimpleNamespace(digest="supporting-evidence-bundle"),
        gazetteer=SimpleNamespace(entries=entries, resolve=resolve),
    )
    return context


def test_cross_role_scope_uses_multiple_source_roles_and_keeps_point_geometry_out(
):
    hazard = _feature(
        bsm="44142621100000009001",
        source_feature_id="hazard:luchi:1",
        text="炉池赖木生",
        layer="geological_hazard_points",
        lon=116.07285,
        lat=24.83862,
    )
    annotation = _feature(
        bsm="44142621100000009002",
        source_feature_id="annotation:luchi:1",
        text="炉池古驿道节点",
        layer="annotations_current",
        lon=116.07310,
        lat=24.83880,
    )
    context = _context(
        points={
            "geological_hazard_points": [hazard],
            "annotations_current": [annotation],
        }
    )
    graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )

    expansion = graph.expand_supporting_evidence(
        "炉池",
        role="village",
    )

    candidate = expansion["inferred_scope_candidate"]
    assert expansion["status"] == "inferred"
    assert candidate is not None
    assert candidate.entity_type == "residential_cluster"
    assert candidate.geometry_ref is None
    assert candidate.feature_bsm is None
    assert candidate.related_parcel_bsms
    assert any(
        item.get("step") == "semantic_label_probe_resolution"
        and item.get("source_role") == "hazard"
        for item in expansion["query_trace"]
    )
    assert any(
        item.get("step") == "semantic_label_probe_resolution"
        and item.get("source_role") == "landmark"
        for item in expansion["query_trace"]
    )
    inference = next(
        item
        for item in expansion["query_trace"]
        if item.get("step") == "cross_role_scope_inference"
    )
    assert set(inference["source_roles"]) >= {"hazard", "landmark"}
    assert inference["best_effort"] is True
    assert inference["geometry_granularity"] == "parcel_set"


def test_unsupported_name_remains_unresolved_with_trace():
    context = _context()
    graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )

    expansion = graph.expand_supporting_evidence(
        "不存在的地点",
        role="village",
    )

    assert expansion["status"] == "unresolved"
    assert expansion["inferred_scope_candidate"] is None
    assert any(
        item.get("step") == "supporting_evidence_unresolved"
        for item in expansion["query_trace"]
    )


def test_scoped_same_name_facility_keeps_feature_identity():
    point_a = _feature(
        bsm="44142621100000006001",
        source_feature_id="facility:hall:a",
        text="祠堂",
        layer="facilities_current",
        lon=116.0721,
        lat=24.8381,
    )
    point_b = _feature(
        bsm="44142621100000006002",
        source_feature_id="facility:hall:b",
        text="祠堂",
        layer="facilities_current",
        lon=116.0909,
        lat=24.8569,
    )
    village_a = SimpleNamespace(
        name="甲村",
        aliases=[],
        bsms=["44142621100000001001"],
        centroid=(116.073, 24.839),
    )
    village_b = SimpleNamespace(
        name="乙村",
        aliases=[],
        bsms=["44142621100000001002"],
        centroid=(116.091, 24.857),
    )
    context = _context(
        points={"facilities_current": [point_a, point_b]},
        gazetteer_entries=[village_a, village_b],
        parcel_origins=((116.072, 24.838), (116.090, 24.856)),
    )
    graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )

    expansion = graph.expand_supporting_evidence(
        "祠堂",
        role="facility",
        scope_names=["甲村"],
    )

    assert expansion["status"] == "resolved", expansion
    assert len(expansion["candidates"]) == 1
    candidate = expansion["candidates"][0]
    assert candidate.feature_bsm == point_a.bsm
    assert candidate.source_feature_id == "facility:hall:a"
    assert candidate.feature_bsm != point_b.bsm
    assert any(
        item.get("step") == "strict_facility_scope"
        for item in expansion["query_trace"]
    )
    unsupported_scope = graph.expand_supporting_evidence(
        "祠堂",
        role="facility",
        scope_names=["丙村"],
    )
    assert unsupported_scope["status"] == "unresolved"
    assert unsupported_scope["candidates"] == []


def test_cross_role_point_does_not_become_a_road_or_line_candidate():
    hazard = _feature(
        bsm="44142621100000009003",
        source_feature_id="hazard:luchi:2",
        text="炉池赖木生",
        layer="geological_hazard_points",
        lon=116.07285,
        lat=24.83862,
    )
    road = SimpleNamespace(
        bsm="44142621100000007001",
        text="炉池路",
        geometry={
            "type": "LineString",
            "coordinates": [[116.072, 24.838], [116.074, 24.840]],
        },
        _raw={"source_feature_id": "road:luchi:1"},
    )
    context = _context(
        points={"geological_hazard_points": [hazard]},
        lines={"roads_current": [road]},
    )
    graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )

    expansion = graph.expand_supporting_evidence(
        "炉池",
        role="road",
    )

    assert expansion["inferred_scope_candidate"] is None
    assert all(
        getattr(candidate, "role", "") in {"road", "axis"}
        for candidate in expansion["candidates"]
    )


@pytest.mark.asyncio
async def test_ground_consumes_inferred_scope_candidate_and_trace(monkeypatch):
    from app.domain.ground import anchors as anchors_module
    from app.evidence.retrieval import evidence_graph as evidence_graph_module

    parcel_bsm = "44142621100000001001"
    inferred = PlaceResolutionCandidate(
        entity_ref="scope:village:炉池",
        entity_type="residential_cluster",
        role="village",
        canonical_name="炉池",
        source_bsms=[parcel_bsm],
        related_parcel_bsms=[parcel_bsm],
        score=0.5,
    )

    class _Graph:
        def resolve_mention(self, mention, role="unknown", hints=""):
            return SimpleNamespace(
                mention=mention,
                status="unresolved",
                candidates=[],
                query_trace=[{"step": "direct_source_resolution", "role": role}],
            )

        def expand_supporting_evidence(self, *args, **kwargs):
            return {
                "candidates": [],
                "inferred_scope_candidate": inferred,
                "status": "inferred",
                "query_trace": [{
                    "step": "cross_role_scope_inference",
                    "source_roles": ["hazard", "landmark"],
                    "best_effort": True,
                }],
            }

    monkeypatch.setattr(
        evidence_graph_module.EvidenceGraph,
        "build",
        classmethod(lambda cls, context: _Graph()),
    )
    context = SimpleNamespace(
        session_id="ground-supporting-evidence",
        village_name="金田村",
        workspace=SimpleNamespace(
            points={},
            lines={},
            polygons={},
            boundary=None,
        ),
        current_parcels=lambda: [],
        location_facts=[L1LocationFact(
            mention="炉池",
            normalized_name="炉池",
            role="village",
            source_report_ref="report:mvp",
            dimension_key="historical_culture",
        )],
        gazetteer=None,
        kg=None,
        ports=None,
    )

    grounded = await anchors_module.ground_l1_anchors(
        context,
        "ground-supporting-evidence",
        bump=False,
    )

    assert len(grounded) == 1
    anchor = grounded[0]
    assert anchor.best_effort is True
    assert anchor.source_bsms == [parcel_bsm]
    assert anchor.geometry_ref is None
    assert anchor.geometry_granularity == "parcel_set"
    assert any(
        item.get("step") == "cross_role_scope_inference"
        for item in anchor.query_trace
    )
