"""Offline regression tests for the e2e stabilization plan (P0/P1).

Each test maps to an acceptance item in docs/design plans:
- unit/parameter ERROR downgrade (P0.2)
- target_projection L3 gate route (P0.5)
- identical-fingerprint VALIDATE replay cap + per-session budget (P0.4)
- empty spatial deferral = plain approve (P0.1)
- blocked VALIDATE compilation auto-defers targets (P0.3)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.workflow.gate_policy import GATE_ROUTE_POLICY
from app.workflow import root_graph
from app.workflow.stages import validate as validate_stage
from app.domain.program.claim_draft import (
    PlanningClaimDraft,
    PlanningClaimDraftSet,
    claim_set_semantic_errors,
    normalize_claim_draft_set,
)


# ?? P0.2: unit/parameter errors are warnings, not semantic blockers ??????
def test_claim_unknown_units_are_warnings_not_semantic_errors():
    li = "\u91cc"  # ? (unknown length unit)
    raw = PlanningClaimDraftSet(
        dimension_key="test",
        claims=[
            PlanningClaimDraft(
                claim_id="c1",
                statement="s",
                suggested_category="zone",
                suggested_output_kind="polygon",
                polygon_parameters={
                    "materialization_role": "land_use_assignment",
                    "planning_zone": "A",
                    "land_use": "B",
                    "area_range": {"minimum": 1, "maximum": 5, "unit": li},
                },
            ),
            PlanningClaimDraft(
                claim_id="c2",
                statement="s",
                suggested_category="road",
                suggested_output_kind="line",
                road_parameters={"action": "new", "length": {"value": 100, "unit": li}},
            ),
            PlanningClaimDraft(
                claim_id="c3",
                statement="s",
                suggested_category="zone",
                suggested_output_kind="polygon",
                polygon_parameters={
                    "materialization_role": "land_use_assignment",
                    "planning_zone": "A",
                    "land_use": "B",
                    "area_range": {"minimum": 1, "maximum": 5, "unit": "ha"},
                },
            ),
        ],
    )
    cs = normalize_claim_draft_set(raw, dimension_key="test")
    assert not any(d.startswith("ERROR[") for d in cs.diagnostics)
    assert claim_set_semantic_errors(cs) == []
    assert len(cs.claims) == 3


def test_claim_incomplete_area_range_is_warning():
    raw = PlanningClaimDraftSet(
        dimension_key="test",
        claims=[
            PlanningClaimDraft(
                claim_id="c1",
                statement="s",
                suggested_category="zone",
                suggested_output_kind="polygon",
                polygon_parameters={
                    "materialization_role": "land_use_assignment",
                    "planning_zone": "A",
                    "land_use": "B",
                    "area_range": {"minimum": 1, "unit": "ha"},
                },
            ),
        ],
    )
    cs = normalize_claim_draft_set(raw, dimension_key="test")
    assert any("WARNING[incomplete_area_range]" in d for d in cs.diagnostics)
    assert not any(d.startswith("ERROR[") for d in cs.diagnostics)
    assert claim_set_semantic_errors(cs) == []


# ?? P0.5: target_projection L3 gate route is a bounded retry, not HUMAN ??
def test_target_projection_l3_route_retries_target():
    assert "L3" in GATE_ROUTE_POLICY["target_projection"]
    route = root_graph._evaluate_gate_policy(
        {"retry_counts": {"target_projection": 0}},
        "target_projection",
        "L3",
    )
    assert route == "target_projection"


# ?? P0.4: identical-fingerprint VALIDATE replay cap + budget ?????????????
class _FakeGate:
    issue_fingerprint = "abc"


def _validate_state(retry_count=0, budget=0, fingerprint="abc"):
    return {
        "retry_counts": {"validate": retry_count},
        "validation_budget_used": {"validate": budget},
        "repair_impact": {
            "status": "ready",
            "earliest_invalid_stage": "EXECUTE",
            "directive_ids": ["d1"],
        },
        "stage_audit": {"VALIDATE": {"issue_fingerprint": fingerprint}},
    }


def test_validate_first_replay_allowed(monkeypatch):
    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: _FakeGate())
    route = root_graph._retry_or_human(_validate_state(0), "validate", "execute")
    assert route == "execute"


def test_validate_retry_exhaustion_goes_diagnostic(monkeypatch):
    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: _FakeGate())
    route = root_graph._retry_or_human(_validate_state(3), "validate", "execute")
    assert route == root_graph.END_DIAGNOSTIC


def test_validate_session_budget_exhausted(monkeypatch):
    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: _FakeGate())
    state = _validate_state(1, budget=21)
    route = root_graph._retry_or_human(state, "validate", "execute")
    assert route == root_graph.END_DIAGNOSTIC


# ?? P0.1: empty spatial deferral is a plain approve, never a dead state ??
@pytest.mark.asyncio
async def test_empty_spatial_defer_is_plain_approve(monkeypatch):
    state = {
        "session_id": "s1",
        "paused_stage": "select",
        "human_review_items": [{"request_type": "spatial_reference_unresolved"}],
        "human_review_decisions": {
            "action": "approve",
            "defer_unresolved_spatial_references": True,
            "deferred_target_ids": [],
        },
    }
    monkeypatch.setattr(root_graph, "_gate_mutation_patch", lambda *a, **k: {})
    result = await root_graph.apply_human_review_decision(state)
    assert "fatal_error" not in result
    assert result.get("human_review_resume_consumed") is True


# ?? P0.3: blocked VALIDATE compilation auto-defers target-level findings ?
def test_auto_defer_blocked_targets_builds_ledger_and_passes(monkeypatch):
    compilation = SimpleNamespace(
        unresolved=[SimpleNamespace(target_ids=["t1", "t2"])]
    )
    impact = SimpleNamespace(reason="no deterministic repair policy")
    state = {"session_id": "s1", "artifact_refs": {}}
    working_state = {"artifact_refs": {}}

    persisted = {}

    def fake_persist(ws, stage, schema_id, payload):
        persisted[schema_id] = payload
        return {"ref": schema_id}

    decision = validate_stage._auto_defer_blocked_targets(
        state,
        compilation,
        impact,
        working_state,
        load_ref=lambda *a, **k: None,
        persist=fake_persist,
    )
    assert decision is not None
    assert decision["next_action"]["target_stage"] == "reconcile"
    assert decision["gate"].feedback_route == "PASS"
    assert decision["patch"]["auto_deferred_target_ids"] == ["t1", "t2"]
    ledger = persisted.get("DeferralLedger")
    assert ledger is not None
    assert [e.target_id for e in ledger.entries] == ["t1", "t2"]


def test_auto_defer_blocked_targets_none_without_ids():
    compilation = SimpleNamespace(unresolved=[SimpleNamespace(target_ids=[])])
    impact = SimpleNamespace(reason="integrity failure")
    decision = validate_stage._auto_defer_blocked_targets(
        {"session_id": "s1"},
        compilation,
        impact,
        {"artifact_refs": {}},
        load_ref=lambda *a, **k: None,
        persist=lambda *a, **k: None,
    )
    assert decision is None


# ?? P0.1 (root cause of run #6 dead state): GROUND approve must continue ??
def test_approve_ground_routes_to_select_never_end():
    assert root_graph._approve_ground(
        {"human_review_decisions": {"action": "approve"}}, "ground"
    ) == "select"


def test_approve_default_continues_forward_for_known_stages():
    assert root_graph._approve_default({}, "target_projection") == "ground"
    assert root_graph._approve_default({}, "ground") == "select"
    assert root_graph._approve_default({}, "reconcile") == "deliver"


def test_auto_defer_blocked_targets_fails_closed_on_non_target_findings():
    compilation = SimpleNamespace(
        unresolved=[
            SimpleNamespace(target_ids=["t1"]),
            SimpleNamespace(target_ids=[]),
        ]
    )
    impact = SimpleNamespace(reason="mixed findings")
    decision = validate_stage._auto_defer_blocked_targets(
        {"session_id": "s1"},
        compilation,
        impact,
        {"artifact_refs": {}},
        load_ref=lambda *a, **k: None,
        persist=lambda *a, **k: None,
    )
    assert decision is None
