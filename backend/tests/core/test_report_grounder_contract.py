from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.spatial.grounding import report_grounder as module


def _fact(name: str = "祠堂", role: str = "facility") -> SimpleNamespace:
    return SimpleNamespace(
        mention=name,
        normalized_name=name,
        role=role,
        source_report_ref="current_report.md",
        source_span="",
    )


class _Graph:
    def __init__(self, candidates):
        self.candidates = candidates

    def resolve_mention(self, _name, *, role):
        return SimpleNamespace(status="resolved", candidates=self.candidates)


def _context(graph):
    return SimpleNamespace(
        gazetteer=None,
        workspace=SimpleNamespace(polygons={}, lines={}, points={}),
        evidence_graph=graph,
        location_facts=[],
    )


@pytest.mark.asyncio
async def test_ground_report_emits_stable_candidate_and_source_span(monkeypatch):
    candidate = SimpleNamespace(
        entity_ref="entity:facility:stable-1",
        source_bsms=["bsm-1"],
        geometry_ref="bundle://feature/annotation-1",
    )
    graph = _Graph([candidate])
    context = _context(graph)

    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    monkeypatch.setattr(EvidenceGraph, "build", staticmethod(lambda _context: graph))
    result = await module.ground_report(
        context,
        [_fact()],
        "现状设施包括祠堂。",
        llm=None,
        session_id="ground-contract",
    )

    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.status == "grounded"
    assert entity.entity_ref == "facility:8ca78906595b91f6d35a0cb8"
    assert entity.candidate_ids == ["entity:facility:stable-1"]
    assert entity.source_span is not None
    assert entity.source_span["segment_id"] == "report"
    assert result.pending == []
    assert result.unresolved == []


@pytest.mark.asyncio
async def test_empty_or_ambiguous_candidate_set_is_pending_without_default_choice(monkeypatch):
    graph = _Graph([
        SimpleNamespace(entity_ref="entity:facility:a", source_bsms=["a"], geometry_ref="bundle://a"),
        SimpleNamespace(entity_ref="entity:facility:b", source_bsms=["b"], geometry_ref="bundle://b"),
    ])
    context = _context(graph)

    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    monkeypatch.setattr(EvidenceGraph, "build", staticmethod(lambda _context: graph))
    result = await module.ground_report(
        context,
        [_fact()],
        "现状设施包括祠堂。",
        llm=None,
        session_id="ground-ambiguous",
    )

    entity = result.entities[0]
    assert entity.status == "pending"
    assert entity.candidate_ids == []
    assert entity.reason == "ambiguous_candidate_set"
    assert result.pending_refs == [entity.entity_ref]


@pytest.mark.asyncio
async def test_duplicate_input_entities_are_preserved_as_pending(monkeypatch):
    candidate = SimpleNamespace(
        entity_ref="entity:facility:stable-1",
        source_bsms=["bsm-1"],
        geometry_ref="bundle://feature/annotation-1",
    )
    graph = _Graph([candidate])
    context = _context(graph)

    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    monkeypatch.setattr(EvidenceGraph, "build", staticmethod(lambda _context: graph))
    result = await module.ground_report(
        context,
        [_fact(), _fact()],
        "现状设施包括祠堂。",
        llm=None,
        session_id="ground-duplicate",
    )

    assert len(result.entities) == 2
    assert all(entity.status == "pending" for entity in result.entities)
    assert all(entity.reason == "duplicate_input_entity_ref" for entity in result.entities)
    assert len(result.pending_refs) == 2
