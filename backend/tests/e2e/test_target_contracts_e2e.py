from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.agent.parse.compile_node import compile_program_deterministic
from app.agent.ground.aggregate import ground_aggregate
from app.modules.schema.contracts.deferral_contracts import (
    DeferralLedger,
    HumanDeferralDecision,
    TargetDeferral,
)
from app.modules.schema.contracts.l3_contracts import (
    PlanningIntervention,
    PlanningProgram,
)
from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec


pytestmark = pytest.mark.e2e


def test_physical_target_stays_spatial_when_location_evidence_is_missing():
    program = PlanningProgram(
        interventions=[
            PlanningIntervention(
                intervention_id="project-physical-1",
                name="村民活动中心",
                execution_mode="spatial",
                expected_output_kind="parcel",
            )
        ]
    )

    result, specs, diagnostics = compile_program_deterministic(program)

    target = result.typed_intent.project_targets[0]
    assert target.target_id == "project-physical-1"
    assert target.requires_spatial is True
    assert target.execution_mode == "spatial"
    assert target.expected_output_kind == "parcel"
    assert specs[0].target_id == target.target_id
    assert specs[0].unresolved_reason == "missing_location_evidence"
    assert any(
        diagnostic.code == "UNRESOLVED_SPATIAL_REFERENCE"
        and diagnostic.target_id == target.target_id
        and diagnostic.spec_id == specs[0].spec_id
        for diagnostic in diagnostics
    )


def test_non_spatial_intervention_compiles_as_an_action_target():
    program = PlanningProgram(
        interventions=[
            PlanningIntervention(
                intervention_id="action-1",
                name="建立村庄保洁巡查制度",
                execution_mode="non_spatial",
                expected_output_kind="action",
            )
        ]
    )

    result, specs, diagnostics = compile_program_deterministic(program)

    target = result.typed_intent.project_targets[0]
    assert target.target_id == "action-1"
    assert target.requires_spatial is False
    assert target.execution_mode == "non_spatial"
    assert target.expected_output_kind == "action"
    assert specs == []
    assert diagnostics == []


def test_deferral_ledger_is_immutable_and_records_a_human_decision():
    ledger = DeferralLedger(
        entries=(
            TargetDeferral(
                target_id="project-physical-1",
                reason="authoritative parcel evidence is unavailable",
                source_refs=("artifact:grounding_result:ground-1", "spec:project-physical-1"),
                decision=HumanDeferralDecision(
                    decision_id="review-1",
                    decided_by="planner@example.test",
                    decided_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
                    rationale="Continue with non-blocking work only.",
                ),
            ),
        )
    )

    assert ledger.schema_version == "2.0"
    assert ledger.entries[0].target_id == "project-physical-1"
    with pytest.raises(Exception):
        ledger.entries = ()


def test_ground_preserves_unresolved_target_and_spec_links(monkeypatch):
    class EmptyResolver:
        def __init__(self, context):
            self.context = context

        def resolve_spec(self, spec):
            raise AssertionError("unresolved specs must not be resolved")

    monkeypatch.setattr("app.agent.ground.aggregate.SpatialResolver", EmptyResolver)
    spec = SpatialReferenceSpec(
        type="composed",
        op="and",
        intervention_id="project-physical-1",
        target_id="project-physical-1",
        spec_id="spatial-ref:project-physical-1",
        unresolved_reason="missing_location_evidence",
    )

    result = ground_aggregate([spec], object())

    assert result.schema_version == "2.0"
    assert result.unresolved[0].related_artifact_id == "project-physical-1"
    assert "spec_id=spatial-ref:project-physical-1" in result.unresolved[0].detail
    assert result.spatial_query_evidence[0].target_id == "project-physical-1"


def test_acknowledgement_does_not_clear_ground_unresolved_items(monkeypatch):
    from app.agent.bootstrap import post_l3_main_nodes
    from app.modules.schema.contracts.contract_meta import StageIssue
    from app.modules.schema.contracts.grounding_contracts import GroundingResult

    context = SimpleNamespace(version="1")
    context.snapshot_meta = lambda: {"session_id": "session-1", "version": "1"}
    unresolved = StageIssue(
        stage="ground",
        severity="warning",
        code="spatial_reference_unresolved",
        message="missing evidence",
        related_artifact_id="project-physical-1",
    )
    persisted = []

    async def require_context(state):
        return context

    monkeypatch.setattr(post_l3_main_nodes, "_require_context", require_context)
    monkeypatch.setattr(
        "app.agent.ground.aggregate.ground_aggregate",
        lambda specs, loaded_context: GroundingResult(unresolved=[unresolved]),
    )
    monkeypatch.setattr(
        "app.agent.ground.gate.evaluate_ground_gate",
        lambda result: SimpleNamespace(model_dump=lambda mode: {"passed": False}),
    )
    monkeypatch.setattr(
        post_l3_main_nodes,
        "_persist_artifact",
        lambda state, module, artifact_type, result: persisted.append(result) or {},
    )

    asyncio.run(
        post_l3_main_nodes.ground_node(
            {"specs": [], "human_acknowledged_unresolved_spatial": True}
        )
    )

    assert persisted[0].unresolved == [unresolved]


def test_deferral_requires_explicit_target_ids():
    from app.agent.bootstrap.graph import apply_human_review_decision

    patch = asyncio.run(
        apply_human_review_decision(
            {
                "human_review_items": [{"request_id": "ground-1"}],
                "paused_stage": "ground",
                "human_review_decisions": {
                    "action": "accept",
                    "defer_unresolved_spatial_references": True,
                },
            }
        )
    )

    assert patch["fatal_error"]["code"] == "HUMAN_DEFER_TARGET_IDS_REQUIRED"
    assert "ground_gate" not in patch


def test_explicit_unresolved_target_deferral_persists_a_ledger(monkeypatch):
    from app.agent.bootstrap.graph import _record_target_deferrals
    from app.modules.schema.contracts.contract_meta import StageIssue
    from app.modules.schema.contracts.grounding_contracts import GroundingResult

    captured = {}

    monkeypatch.setattr(
        "app.agent.bootstrap.artifact_runtime.load_artifact",
        lambda state, key, model: GroundingResult(
            unresolved=[
                StageIssue(
                    stage="ground",
                    severity="warning",
                    code="spatial_reference_unresolved",
                    message="missing evidence",
                    related_artifact_id="project-physical-1",
                )
            ]
        ),
    )

    def store_artifact(state, key, module, artifact_type, payload):
        captured["key"] = key
        captured["type"] = artifact_type
        captured["payload"] = payload
        return {"artifact_id": "deferral-1"}

    monkeypatch.setattr(
        "app.agent.bootstrap.artifact_runtime.store_artifact", store_artifact
    )

    patch = asyncio.run(
        _record_target_deferrals(
            {
                "human_review_event_id": "review-1",
                "artifact_refs": {"grounding_result": {"artifact_id": "ground-1"}},
            },
            {"decided_by": "planner@example.test", "feedback": "Defer this target."},
            ["project-physical-1"],
        )
    )

    assert patch["artifact_refs"]["deferral_ledger"]["artifact_id"] == "deferral-1"
    assert captured["key"] == "deferral_ledger"
    assert captured["type"] == "DeferralLedger"
    assert captured["payload"].entries[0].source_refs == (
        "artifact:grounding_result:ground-1",
        "spec:project-physical-1",
    )
    assert captured["payload"].entries[0].decision.decided_by == "planner@example.test"
