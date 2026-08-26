from __future__ import annotations

from types import SimpleNamespace
import re

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


def _candidate(ref: str, bsm: str) -> PlaceResolutionCandidate:
    return PlaceResolutionCandidate(
        entity_ref=ref,
        entity_type="facility",
        canonical_name="祠堂",
        role="facility",
        source_bsms=[bsm],
        geometry_ref=f"bundle://feature/{bsm}",
        feature_bsm=bsm,
        source_feature_id=f"facility:{bsm}",
        relation_refs=["relation:test"],
        score=0.6,
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


def test_scoped_semantic_probe_keeps_scope_over_global_same_name(monkeypatch):
    context = _context()
    graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )
    global_candidate = _candidate(
        "http://example.test/facility/global",
        "bsm-global",
    )
    scoped_candidate = _candidate(
        "http://example.test/facility/scoped",
        "bsm-scoped",
    )

    monkeypatch.setattr(
        graph,
        "semantic_label_probes",
        lambda *_args, **_kwargs: [("社前公祠", "facility")],
    )

    def scoped_lookup(_scope, label, **_kwargs):
        if label == "社前公祠":
            return SimpleNamespace(
                status="resolved",
                candidates=[scoped_candidate],
                query_trace=[],
            )
        return SimpleNamespace(
            status="unresolved",
            candidates=[],
            query_trace=[],
        )

    monkeypatch.setattr(graph, "query_facility_bsms", scoped_lookup)
    expansion = graph.expand_supporting_evidence(
        "祠堂",
        role="facility",
        scope_names=["社前村"],
        direct_result=SimpleNamespace(
            status="ambiguous",
            candidates=[global_candidate],
            query_trace=[],
        ),
    )

    assert expansion["status"] == "resolved"
    assert expansion["candidates"] == [scoped_candidate]
    assert global_candidate not in expansion["candidates"]
    assert any(
        item.get("step") == "strict_facility_probe_scope"
        and item.get("probe") == "社前公祠"
        for item in expansion["query_trace"]
    )


@pytest.mark.asyncio
async def test_ground_uses_scoped_probe_mode_after_trace_truncation(monkeypatch):
    from app.domain.ground import anchors as anchors_module
    from app.evidence.retrieval import evidence_graph as evidence_graph_module

    context = _context()
    graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )
    global_candidate = _candidate(
        "http://example.test/facility/global",
        "bsm-global",
    )
    scoped_candidate = _candidate(
        "http://example.test/facility/scoped",
        "bsm-scoped",
    )
    probes = [(f"别名{i}", "facility") for i in range(11)]
    probes.append(("社前公祠", "facility"))
    scopes = [f"村{i}" for i in range(12)]

    def direct_resolve(_mention, **_kwargs):
        return SimpleNamespace(
            status="resolved",
            candidates=[global_candidate],
            query_trace=[],
        )

    def scoped_lookup(_scope, label, **_kwargs):
        if label == "社前公祠":
            return SimpleNamespace(
                status="resolved",
                candidates=[scoped_candidate],
                query_trace=[],
            )
        return SimpleNamespace(
            status="unresolved",
            candidates=[],
            query_trace=[],
        )

    monkeypatch.setattr(graph, "resolve_mention", direct_resolve)
    monkeypatch.setattr(
        graph,
        "semantic_label_probes",
        lambda *_args, **_kwargs: probes,
    )
    monkeypatch.setattr(graph, "query_facility_bsms", scoped_lookup)
    monkeypatch.setattr(
        evidence_graph_module.EvidenceGraph,
        "build",
        staticmethod(lambda _context: graph),
    )
    context.location_facts = [L1LocationFact(
        mention="祠堂",
        normalized_name="祠堂",
        role="facility",
        village_scopes=scopes,
        spatial_hint="社前村",
        source_report_ref="report:trace-truncation",
        dimension_key="historical_culture",
    )]

    grounded = await anchors_module.ground_l1_anchors(
        context,
        "ground-strict-probe-truncation",
        bump=False,
    )

    assert len(grounded) == 1
    assert grounded[0].feature_bsm == "bsm-scoped"
    assert any(
        item.get("step") == "supporting_evidence_start"
        for item in grounded[0].query_trace
    )


def test_direct_result_reuse_does_not_resolve_again():
    class _CountingIndex:
        def __init__(self):
            self.calls = 0

        def resolve_mention(self, _mention, *, role, hints):
            del role, hints
            self.calls += 1
            return SimpleNamespace(
                status="unresolved",
                candidates=[],
                query_trace=[],
            )

        def semantic_label_probes(self, *_args, **_kwargs):
            return []

    index = _CountingIndex()
    context = _context()
    graph = EvidenceGraph(context, index=index)
    candidate = _candidate("http://example.test/facility/1", "bsm-1")
    expansion = graph.expand_supporting_evidence(
        "祠堂",
        role="facility",
        direct_result=SimpleNamespace(
            status="ambiguous",
            candidates=[candidate],
            query_trace=[],
        ),
    )

    assert index.calls == 0
    assert expansion["candidates"] == [candidate]
    assert expansion["status"] == "ambiguous"


def test_supporting_evidence_caps_scope_and_probe_queries(monkeypatch):
    context = _context()
    graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )
    scoped_calls = []

    def scoped_lookup(scope, label, **_kwargs):
        scoped_calls.append((scope, label))
        return SimpleNamespace(
            status="unresolved",
            candidates=[],
            query_trace=[],
        )

    monkeypatch.setattr(graph, "query_facility_bsms", scoped_lookup)
    monkeypatch.setattr(
        graph,
        "semantic_label_probes",
        lambda *_args, **_kwargs: [
            (f"别名{i}", "facility")
            for i in range(100)
        ],
    )
    expansion = graph.expand_supporting_evidence(
        "祠堂",
        role="facility",
        scope_names=[f"村{i}" for i in range(100)],
        direct_result=SimpleNamespace(
            status="unresolved",
            candidates=[],
            query_trace=[],
        ),
        max_candidates=999,
    )
    start = next(
        item
        for item in expansion["query_trace"]
        if item.get("step") == "supporting_evidence_start"
    )

    assert len(start["scope_names"]) == 12
    assert start["scope_truncated"] is True
    assert start["candidate_limit"] == 12
    assert len(scoped_calls) <= 12 * (1 + 12)


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
    assert expansion["candidates"]
    assert [candidate.feature_bsm for candidate in expansion["candidates"]] == [
        road.bsm
    ]
    assert all(
        getattr(candidate, "role", "") in {"road", "axis"}
        and getattr(candidate, "source_layer", "") == "roads_current"
        for candidate in expansion["candidates"]
    )
    water_expansion = graph.expand_supporting_evidence(
        "炉池",
        role="water",
    )
    assert water_expansion["candidates"] == []


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


@pytest.mark.asyncio
async def test_ground_rejects_global_facility_when_scope_lookup_is_unresolved(
    monkeypatch,
):
    from app.domain.ground import anchors as anchors_module
    from app.evidence.retrieval import evidence_graph as evidence_graph_module

    global_candidate = PlaceResolutionCandidate(
        entity_ref="poi:祠堂:global",
        entity_type="facility",
        role="facility",
        canonical_name="祠堂",
        feature_bsm="44142621100000006001",
        source_feature_id="facility:global",
        geometry_ref="bundle://feature/44142621100000006001",
        source_bsms=["44142621100000001001"],
        score=0.95,
    )

    class _Graph:
        def resolve_mention(self, mention, role="unknown", hints=""):
            return SimpleNamespace(
                mention=mention,
                status="ambiguous",
                candidates=[global_candidate],
                query_trace=[],
            )

        def expand_supporting_evidence(self, *args, **kwargs):
            return {
                "candidates": [],
                "inferred_scope_candidate": None,
                "status": "unresolved",
                "query_trace": [{
                    "step": "supporting_evidence_start",
                    "scope_names": ["社前村"],
                }, {
                    "step": "supporting_evidence_unresolved",
                    "reason": "strict facility scope has no source-backed candidate",
                }],
            }

    monkeypatch.setattr(
        evidence_graph_module.EvidenceGraph,
        "build",
        classmethod(lambda cls, context: _Graph()),
    )
    context = SimpleNamespace(
        session_id="ground-strict-scope",
        village_name="金田村",
        workspace=SimpleNamespace(
            points={},
            lines={},
            polygons={},
            boundary=None,
        ),
        current_parcels=lambda: [],
        location_facts=[L1LocationFact(
            mention="祠堂",
            normalized_name="祠堂",
            role="facility",
            village_scopes=["社前村"],
            spatial_hint="社前村",
            source_report_ref="report:mvp",
            dimension_key="historical_culture",
        )],
        gazetteer=None,
        kg=None,
        ports=None,
    )

    grounded = await anchors_module.ground_l1_anchors(
        context,
        "ground-strict-scope",
        bump=False,
    )

    assert grounded == []
    assert context.grounding_unresolved[0]["mention"] == "祠堂"


@pytest.mark.asyncio
async def test_ground_rejects_global_facility_when_scope_expansion_raises(
    monkeypatch,
):
    from app.domain.ground import anchors as anchors_module
    from app.evidence.retrieval import evidence_graph as evidence_graph_module

    global_candidate = _candidate(
        "http://example.test/facility/global",
        "bsm-global",
    )

    class _Graph:
        def resolve_mention(self, mention, role="unknown", hints=""):
            return SimpleNamespace(
                mention=mention,
                status="resolved",
                candidates=[global_candidate],
                query_trace=[],
            )

        def expand_supporting_evidence(self, *args, **kwargs):
            raise RuntimeError("scoped lookup unavailable")

    monkeypatch.setattr(
        evidence_graph_module.EvidenceGraph,
        "build",
        classmethod(lambda cls, context: _Graph()),
    )
    context = SimpleNamespace(
        session_id="ground-strict-scope-error",
        village_name="金田村",
        workspace=SimpleNamespace(
            points={},
            lines={},
            polygons={},
            boundary=None,
        ),
        current_parcels=lambda: [],
        location_facts=[L1LocationFact(
            mention="祠堂",
            normalized_name="祠堂",
            role="facility",
            spatial_hint="社前村",
            source_report_ref="report:mvp",
            dimension_key="historical_culture",
        )],
        gazetteer=SimpleNamespace(
            entries=[SimpleNamespace(name="社前村", aliases=[], bsms=[])],
            resolve=lambda *_args, **_kwargs: None,
        ),
        kg=None,
        ports=None,
    )

    grounded = await anchors_module.ground_l1_anchors(
        context,
        "ground-strict-scope-error",
        bump=False,
    )

    assert grounded == []
    assert context.grounding_unresolved[0]["mention"] == "祠堂"


@pytest.mark.asyncio
async def test_shared_context_recovery_retries_unresolved_location_for_three_rounds(
    monkeypatch,
):
    from app.domain.ground import anchors as anchors_module
    from app.evidence.retrieval import evidence_graph as evidence_graph_module

    known = _candidate(
        "http://example.test/facility/known",
        "bsm-known",
    ).model_copy(update={
        "canonical_name": "已知祠堂",
        "source_feature_id": "facility:known",
    })
    unresolved = _candidate(
        "http://example.test/facility/unresolved",
        "bsm-unresolved",
    ).model_copy(update={
        "canonical_name": "祠堂",
        "source_feature_id": "facility:unresolved",
    })
    facts = [
        L1LocationFact(
            mention="已知祠堂",
            normalized_name="已知祠堂",
            role="facility",
            village_scopes=["甲村"],
            spatial_hint="甲村",
            source_span="已知祠堂 | 甲村",
            source_report_ref="report:known",
            dimension_key="history",
        ),
        L1LocationFact(
            mention="祠堂",
            normalized_name="祠堂",
            role="facility",
            village_scopes=["甲村"],
            spatial_hint="甲村",
            source_span="祠堂 | 甲村 | unresolved",
            source_report_ref="report:unresolved",
            dimension_key="history",
        ),
    ]
    context = _context(
        gazetteer_entries=[
            SimpleNamespace(
                name="甲村",
                aliases=[],
                bsms=["44142621100000001001"],
                centroid=(116.073, 24.839),
            ),
        ],
    )
    context.location_facts = facts

    class _Graph:
        def resolve_mention(self, mention, role="unknown", hints=""):
            del role, hints
            if mention == "已知祠堂":
                return SimpleNamespace(
                    status="resolved",
                    candidates=[known],
                    query_trace=[],
                )
            return SimpleNamespace(
                status="unresolved",
                candidates=[],
                query_trace=[],
            )

        def expand_supporting_evidence(self, mention, **_kwargs):
            if mention == "已知祠堂":
                return {
                    "candidates": [known],
                    "status": "resolved",
                    "resolution_mode": "strict_scope",
                    "query_trace": [{
                        "step": "supporting_evidence_start",
                        "scope_names": ["甲村"],
                    }],
                }
            return {
                "candidates": [],
                "scope_candidates": [unresolved],
                "status": "unresolved",
                "query_trace": [{
                    "step": "supporting_evidence_start",
                    "scope_names": ["甲村"],
                }],
            }

        def recover_scoped_candidates(self, *_args, **_kwargs):
            return [unresolved], [{
                "step": "scoped_candidate_recovery",
                "scope": "甲村",
                "accepted_count": 1,
            }]

    graph = _Graph()
    monkeypatch.setattr(
        evidence_graph_module.EvidenceGraph,
        "build",
        staticmethod(lambda _context: graph),
    )
    monkeypatch.setattr(
        "app.core.settings.GROUND_MAX_RECOVERY_ROUNDS",
        3,
    )
    monkeypatch.setattr(
        "app.core.settings.GROUND_MAX_LLM_CALLS",
        3,
    )
    calls = []

    class _LLM:
        def with_structured_output(self, response_model, **_kwargs):
            class _Structured:
                async def ainvoke(self, prompt):
                    calls.append(prompt)
                    candidate_ids = re.findall(
                        r"candidate_id=([^\s]+)",
                        prompt,
                    )
                    digest = re.search(
                        r"input_digest=([0-9a-f]+)",
                        prompt,
                    ).group(1)
                    if len(calls) < 3:
                        return response_model(
                            status="abstain",
                            selected_candidate_id="",
                            input_digest=digest,
                        )
                    return response_model(
                        status="selected",
                        selected_candidate_id=candidate_ids[0],
                        input_digest=digest,
                    )

            return _Structured()

    grounded = await anchors_module.ground_l1_anchors(
        context,
        "shared-context-three-rounds",
        llm=_LLM(),
        bump=False,
    )

    assert len(calls) == 3
    assert "bsm-known" in calls[0]
    assert "previous_unresolved" in calls[1]
    assert [
        anchor.source_feature_id
        for anchor in grounded
    ] == ["facility:known", "facility:unresolved"]
    assert context.grounding_unresolved == []
    assert any(
        item.get("step") == "shared_scope_recovery_selected"
        and item.get("round") == 3
        for item in grounded[1].query_trace
    )
