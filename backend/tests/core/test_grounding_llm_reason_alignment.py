"""Grounding LLM reason alignment (design 22 §4.3).

Covers the resolver-side bounded LLM discrimination contract:
- failure keeps the reference unresolved (never degrades to candidate #1)
- ambiguous references enter LLM discrimination even when BSMs exist
- candidate lines carry geometry + KG topology context for the discriminator
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.spatial.grounding.resolver import SpatialResolver


def _parcel(bsm):
    return SimpleNamespace(bsm=bsm)


def _candidate(name, bsm, entity_ref, score=0.8, geometry="POINT(1 1)", rels=None):
    return SimpleNamespace(
        entity_ref=entity_ref,
        entity_type="ResidentialCluster",
        canonical_name=name,
        aliases=[],
        geometry_ref=geometry,
        source_bsms=[bsm],
        score=score,
        evidence_refs=["test"],
        relation_refs=rels or ["http://village-planning.org/ontology#serves"],
        evidence={},
    )


class _FakeIndex:
    def __init__(self, result):
        self._result = result

    def resolve_mention(self, mention, hints=""):
        return self._result


def _context(index):
    kg = SimpleNamespace(g=None)
    ctx = SimpleNamespace(
        session_id="s-llm-reason",
        version=1,
        kg_version=1,
        gazetteer=None,
        location_facts=[],
        kg=kg,
        workspace=SimpleNamespace(
            points={"annotations_current": [], "facilities_current": []},
            polygons={"landuse_current": []},
        ),
        current_parcels=lambda: [_parcel("bsm-1"), _parcel("bsm-2")],
        evidence_index=index,
    )
    return ctx


def _spec(mention):
    return SimpleNamespace(
        target_id="t-1",
        type="attributive",
        direction=None,
        topo=None,
        semantic=SimpleNamespace(raw_text=""),
        reference=SimpleNamespace(
            kind="place_name", filter={"label_contains": mention}
        ),
    )


def test_llm_failure_keeps_unresolved(monkeypatch):
    """Design §4.3: failure/timeout keeps ambiguous - never degrade to first."""
    from app.infrastructure.llm import factory as llm_factory

    def _boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(llm_factory, "create_flash_llm", _boom)
    index = _FakeIndex(
        SimpleNamespace(
            status="ambiguous",
            candidates=[_candidate("甲村", "bsm-1", "http://e/1", 0.8)],
        )
    )
    resolver = SpatialResolver(_context(index))
    result = resolver._llm_reason_fallback(_spec("甲村"), "甲村", None)
    assert result is None, "LLM failure must keep the reference unresolved"


def test_llm_pick_success_binds_picked_bsm(monkeypatch):
    from app.infrastructure.llm import factory as llm_factory

    monkeypatch.setattr(
        llm_factory,
        "create_flash_llm",
        lambda *a, **k: SimpleNamespace(
            invoke=lambda prompt: SimpleNamespace(content="2")
        ),
    )
    index = _FakeIndex(
        SimpleNamespace(
            status="ambiguous",
            candidates=[
                _candidate("甲村", "bsm-1", "http://e/1", 0.8),
                _candidate("乙村", "bsm-2", "http://e/2", 0.6),
            ],
        )
    )
    resolver = SpatialResolver(_context(index))
    result = resolver._llm_reason_fallback(_spec("模糊村"), "模糊村", None)
    assert result is not None
    assert result.final_bsms == ["bsm-2"]
    assert result.provenance["picked"] == "乙村"


def test_ambiguous_with_bsms_enters_llm_discrimination(monkeypatch):
    from app.infrastructure.llm import factory as llm_factory

    monkeypatch.setattr(
        llm_factory,
        "create_flash_llm",
        lambda *a, **k: SimpleNamespace(
            invoke=lambda prompt: SimpleNamespace(content="1")
        ),
    )
    index = _FakeIndex(
        SimpleNamespace(
            status="ambiguous",
            candidates=[
                _candidate("甲村", "bsm-1", "http://e/1", 0.8),
                _candidate("乙村", "bsm-2", "http://e/2", 0.7),
            ],
        )
    )
    resolver = SpatialResolver(_context(index))
    result = resolver._llm_resolve_ambiguous(_spec("甲村"), "甲村", None)
    assert result is not None
    assert result.final_bsms == ["bsm-1"]
    assert result.uncertainty_reason == "llm_ambiguous_resolution"


def test_candidate_line_carries_geometry_and_topology():
    resolver = SpatialResolver(_context(None))
    line = resolver._candidate_line(
        1,
        _candidate(
            "祠堂",
            "bsm-1",
            "http://e/1",
            rels=[
                "http://village-planning.org/ontology#serves",
                "http://village-planning.org/ontology#nearby",
            ],
        ),
    )
    assert "POINT(1 1)" in line
    assert "serves" in line
    assert "nearby" in line
    assert "拓扑" in line


def test_sync_resolver_queue_wait_is_bounded(monkeypatch):
    """The compatibility resolver must not wait forever behind its gate."""
    from app.infrastructure.llm import factory as llm_factory
    from app.spatial.grounding.call_budget import ground_llm_sync_semaphore

    monkeypatch.setattr("app.core.settings.GROUND_LLM_CALL_TIMEOUT_S", 0.01)
    monkeypatch.setattr("app.core.settings.GROUND_LLM_MAX_CONCURRENT", 1)
    monkeypatch.setattr(
        llm_factory,
        "create_flash_llm",
        lambda *a, **k: SimpleNamespace(
            invoke=lambda _prompt: (_ for _ in ()).throw(
                AssertionError("provider must not start while the queue is held")
            )
        ),
    )
    resolver = SpatialResolver(_context(None))
    gate = ground_llm_sync_semaphore(resolver._ground_llm_budget)
    assert gate.acquire(timeout=0.1)
    try:
        result = resolver._llm_pick_candidate(
            "模糊村",
            "",
            [_candidate("甲村", "bsm-1", "http://e/1")],
        )
    finally:
        gate.release()
    assert result is None
