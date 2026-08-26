"""Focused coverage for equivalent Grounding fallback work grouping."""

from __future__ import annotations

from types import SimpleNamespace
import re

import pytest


def _selection_proposal(response_model, prompt, position=1):
    if response_model.__name__ == "CandidateSelectionBatchProposal":
        decisions = []
        for block in prompt.split("任务 decision_id=")[1:]:
            decision_id = block.splitlines()[0].strip()
            ids = re.findall(r"candidate_id=([^\s]+)", block)
            digest = re.search(r"input_digest=([0-9a-f]+)", block).group(1)
            decisions.append({
                "decision_id": decision_id,
                "status": "selected",
                "selected_candidate_id": ids[position - 1],
                "input_digest": digest,
            })
        return response_model(decisions=decisions)
    ids = re.findall(r"candidate_id=([^\s]+)", prompt)
    digest = re.search(r"input_digest=([0-9a-f]+)", prompt).group(1)
    return response_model(
        status="selected",
        selected_candidate_id=ids[position - 1],
        input_digest=digest,
    )


class _Index:
    def __init__(self, results):
        self._results = iter(results)

    def resolve_mention(self, _mention, *, role, hints):
        return next(self._results)


def _fact(ref: str, *, role: str = "facility") -> SimpleNamespace:
    return SimpleNamespace(
        mention="同名地点",
        normalized_name="同名地点",
        role=role,
        spatial_hint="同一村",
        source_span=f"{role} | 同名地点 | 同一村",
        source_report_ref=ref,
        dimension_key="test",
    )


def _candidate(ref: str, bsm: str) -> SimpleNamespace:
    return SimpleNamespace(
        entity_ref=ref,
        entity_type="facility",
        canonical_name="同名地点",
        role="facility",
        source_bsms=[bsm],
        geometry_ref=f"bundle://feature/{bsm}",
        feature_bsm=bsm,
        source_feature_id=f"source:{bsm}",
        relation_refs=["relation:test"],
        score=0.6,
    )


def _context(facts, results):
    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    context = SimpleNamespace(
        session_id="ground-grouping-test",
        version=1,
        kg_version=1,
        gazetteer=None,
        kg=None,
        location_facts=facts,
        workspace=SimpleNamespace(
            points={"annotations_current": [], "facilities_current": []},
            polygons={"landuse_current": []},
        ),
        current_parcels=lambda: [],
        evidence_graph=None,
    )
    context.evidence_graph = EvidenceGraph(context, index=_Index(results))
    return context


def _village_base_candidate() -> SimpleNamespace:
    return SimpleNamespace(
        entity_ref="",
        entity_type="village",
        canonical_name="",
        role="village",
        source_bsms=[],
        geometry_ref=None,
        relation_refs=[],
        score=0.0,
    )


def _village_fallback_plan(context, fact, anchor, trace):
    clusters = [
        SimpleNamespace(index=1, bsms=["cluster-1"], area_ha=3.0),
        SimpleNamespace(index=2, bsms=["cluster-2"], area_ha=2.0),
        SimpleNamespace(index=3, bsms=["cluster-3"], area_ha=1.0),
    ]
    candidates = [
        SimpleNamespace(
            entity_ref=f"cluster:{cluster.index}",
            entity_type="village",
            canonical_name=f"聚落{cluster.index}",
            role="village",
            source_bsms=list(cluster.bsms),
            geometry_ref=f"POINT({cluster.index} {cluster.index})",
            relation_refs=[],
            score=0.4,
        )
        for cluster in clusters
    ]
    return {
        "fact": fact,
        "anchor": anchor,
        "candidate": None,
        "candidates": candidates,
        "clusters": clusters,
        "hints": "村内",
        "trace": trace,
    }


@pytest.mark.asyncio
async def test_equivalent_facts_share_llm_work_without_losing_fact_identity(monkeypatch):
    from app.domain.ground import anchors

    first = _candidate("http://example.test/facility/1", "bsm-1")
    second = _candidate("http://example.test/facility/1", "bsm-1")
    facts = [_fact("report-1"), _fact("report-2")]
    context = _context(
        facts,
        [
            SimpleNamespace(status="ambiguous", candidates=[first], query_trace=[]),
            SimpleNamespace(status="ambiguous", candidates=[second], query_trace=[]),
        ],
    )
    calls = []

    class FakeLLM:
        def with_structured_output(self, response_model, **_kwargs):
            class _Structured:
                async def ainvoke(self, prompt):
                    calls.append(prompt)
                    return _selection_proposal(response_model, prompt)

            return _Structured()

    monkeypatch.setattr("app.core.settings.GROUND_MAX_LLM_CALLS", 4)
    monkeypatch.setattr("app.core.settings.GROUND_LLM_MAX_CONCURRENT", 2)
    monkeypatch.setattr("app.core.settings.GROUND_LLM_CALL_TIMEOUT_S", 5)
    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    monkeypatch.setattr(
        EvidenceGraph,
        "build",
        staticmethod(lambda current_context: current_context.evidence_graph),
    )

    result = await anchors.ground_l1_anchors(
        context,
        "ground-grouping-test",
        llm=FakeLLM(),
        bump=False,
    )

    assert len(calls) == 1
    assert [anchor.location_fact_ref for anchor in result] == ["report-1", "report-2"]
    assert all(anchor.source_bsms == ["bsm-1"] for anchor in result)
    assert all(
        str(anchor.geometry_ref or "").startswith("bundle://feature/")
        for anchor in result
    )


@pytest.mark.asyncio
async def test_same_name_different_role_or_candidate_does_not_share_work(monkeypatch):
    from app.domain.ground import anchors

    candidate_one = _candidate("http://example.test/place/1", "bsm-1")
    candidate_one_copy = _candidate("http://example.test/place/1", "bsm-1")
    candidate_two = _candidate("http://example.test/place/2", "bsm-2")
    facts = [
        _fact("report-1"),
        _fact("report-2"),
        _fact("report-3", role="water"),
        _fact("report-4"),
    ]
    context = _context(
        facts,
        [
            SimpleNamespace(status="ambiguous", candidates=[candidate_one], query_trace=[]),
            SimpleNamespace(status="ambiguous", candidates=[candidate_one_copy], query_trace=[]),
            SimpleNamespace(status="ambiguous", candidates=[candidate_one], query_trace=[]),
            SimpleNamespace(status="ambiguous", candidates=[candidate_two], query_trace=[]),
        ],
    )
    calls = []

    class FakeLLM:
        def with_structured_output(self, response_model, **_kwargs):
            class _Structured:
                async def ainvoke(self, prompt):
                    calls.append(prompt)
                    return _selection_proposal(response_model, prompt)

            return _Structured()

    monkeypatch.setattr("app.core.settings.GROUND_MAX_LLM_CALLS", 8)
    monkeypatch.setattr("app.core.settings.GROUND_LLM_MAX_CONCURRENT", 2)
    monkeypatch.setattr("app.core.settings.GROUND_LLM_CALL_TIMEOUT_S", 5)
    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    monkeypatch.setattr(
        EvidenceGraph,
        "build",
        staticmethod(lambda current_context: current_context.evidence_graph),
    )

    result = await anchors.ground_l1_anchors(
        context,
        "ground-grouping-test",
        llm=FakeLLM(),
        bump=False,
    )

    assert len(calls) == 1
    assert [anchor.location_fact_ref for anchor in result] == [
        "report-1",
        "report-2",
        "report-3",
        "report-4",
    ]
    assert [anchor.source_bsms for anchor in result] == [
        ["bsm-1"],
        ["bsm-1"],
        ["bsm-1"],
        ["bsm-2"],
    ]


@pytest.mark.asyncio
async def test_empty_village_water_road_candidates_are_skipped(monkeypatch):
    from app.domain.ground import anchors
    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    facts = [
        _fact("report-village", role="village"),
        _fact("report-water", role="water"),
        _fact("report-road", role="road"),
    ]
    context = _context(
        facts,
        [
            SimpleNamespace(status="unresolved", candidates=[], query_trace=[])
            for _ in facts
        ],
    )
    monkeypatch.setattr(
        EvidenceGraph,
        "build",
        staticmethod(lambda current_context: current_context.evidence_graph),
    )

    result = await anchors.ground_l1_anchors(
        context,
        "ground-empty-candidates",
        llm=None,
        bump=False,
    )

    assert result == []


@pytest.mark.asyncio
async def test_village_fallback_wave_is_bounded_and_commits_ownership_in_order(monkeypatch):
    from app.domain.ground import anchors
    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    facts = [
        _fact("report-1", role="village"),
        _fact("report-2", role="village"),
        _fact("report-3", role="village"),
    ]
    for fact, name in zip(facts, ("村甲", "村乙", "村丙")):
        fact.mention = name
        fact.normalized_name = name
    context = _context(
        facts,
        [
            SimpleNamespace(
                status="resolved",
                candidates=[_village_base_candidate()],
                query_trace=[],
            )
            for _ in facts
        ],
    )
    monkeypatch.setattr(
        EvidenceGraph,
        "build",
        staticmethod(lambda current_context: current_context.evidence_graph),
    )
    monkeypatch.setattr(anchors, "_village_spatial_fallback_plan", _village_fallback_plan)
    monkeypatch.setattr("app.core.settings.GROUND_MAX_LLM_CALLS", 8)
    monkeypatch.setattr("app.core.settings.GROUND_LLM_MAX_CONCURRENT", 2)
    monkeypatch.setattr("app.core.settings.GROUND_LLM_CALL_TIMEOUT_S", 5)
    active = 0
    peak = 0
    calls = 0
    selections = iter([1, 2, 3])

    class FakeLLM:
        def with_structured_output(self, response_model, **_kwargs):
            class _Structured:
                async def ainvoke(self, _prompt):
                    nonlocal active, peak, calls
                    calls += 1
                    active += 1
                    peak = max(peak, active)
                    import asyncio

                    await asyncio.sleep(0.02)
                    active -= 1
                    return _selection_proposal(response_model, _prompt, next(selections))

            return _Structured()

    result = await anchors.ground_l1_anchors(
        context,
        "ground-village-wave",
        llm=FakeLLM(),
        bump=False,
    )

    assert calls == 3
    assert peak == 2
    assert [anchor.source_bsms for anchor in result] == [
        ["cluster-1"],
        ["cluster-2"],
        ["cluster-3"],
    ]
    assert context.grounding_unresolved == []


@pytest.mark.asyncio
async def test_village_fallback_wave_respects_budget_before_ordered_commit(monkeypatch):
    from app.domain.ground import anchors
    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    facts = [_fact("report-1", role="village"), _fact("report-2", role="village")]
    for fact, name in zip(facts, ("村甲", "村乙")):
        fact.mention = name
        fact.normalized_name = name
    context = _context(
        facts,
        [
            SimpleNamespace(
                status="resolved",
                candidates=[_village_base_candidate()],
                query_trace=[],
            )
            for _ in facts
        ],
    )
    monkeypatch.setattr(
        EvidenceGraph,
        "build",
        staticmethod(lambda current_context: current_context.evidence_graph),
    )
    monkeypatch.setattr(anchors, "_village_spatial_fallback_plan", _village_fallback_plan)
    monkeypatch.setattr("app.core.settings.GROUND_MAX_LLM_CALLS", 1)
    monkeypatch.setattr("app.core.settings.GROUND_LLM_MAX_CONCURRENT", 2)
    monkeypatch.setattr("app.core.settings.GROUND_LLM_CALL_TIMEOUT_S", 5)
    calls = 0

    class FakeLLM:
        def with_structured_output(self, response_model, **_kwargs):
            class _Structured:
                async def ainvoke(self, _prompt):
                    nonlocal calls
                    calls += 1
                    return _selection_proposal(response_model, _prompt)

            return _Structured()

    result = await anchors.ground_l1_anchors(
        context,
        "ground-village-budget",
        llm=FakeLLM(),
        bump=False,
    )

    assert calls == 1
    assert [anchor.source_bsms for anchor in result] == [["cluster-1"]]
    assert len(context.grounding_unresolved) == 1
