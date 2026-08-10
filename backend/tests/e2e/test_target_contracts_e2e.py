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
    from app.modules.schema.contracts.grounding_contracts import GroundingResult, SpatialQueryEvidence

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
    from app.modules.schema.contracts.grounding_contracts import GroundingResult, SpatialQueryEvidence

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
            ],
            spatial_query_evidence=[
                SpatialQueryEvidence(target_id="project-physical-1", spec_id="spatial-ref-1")
            ],
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
        "spec:spatial-ref-1",
    )
    assert captured["payload"].entries[0].decision.decided_by == "planner@example.test"


def test_partial_ground_deferral_remains_blocking_with_remaining_target_ids(monkeypatch):
    from app.agent.bootstrap.graph import apply_human_review_decision, route_after_human_review
    from app.modules.schema.contracts.contract_meta import StageIssue
    from app.modules.schema.contracts.grounding_contracts import GroundingResult, SpatialQueryEvidence

    grounding = GroundingResult(
        unresolved=[
            StageIssue(stage="ground", severity="warning", code="unresolved", message="one", related_artifact_id="target-1"),
            StageIssue(stage="ground", severity="warning", code="unresolved", message="two", related_artifact_id="target-2"),
        ],
        spatial_query_evidence=[
            SpatialQueryEvidence(target_id="target-1", spec_id="spec-1"),
            SpatialQueryEvidence(target_id="target-2", spec_id="spec-2"),
        ],
    )
    monkeypatch.setattr(
        "app.agent.bootstrap.artifact_runtime.load_artifact",
        lambda state, key, model: grounding,
    )
    monkeypatch.setattr(
        "app.agent.bootstrap.artifact_runtime.store_artifact",
        lambda *args: {"artifact_id": "ledger-1"},
    )

    patch = asyncio.run(
        apply_human_review_decision(
            {
                "human_review_items": [{"request_id": "ground-1"}],
                "paused_stage": "ground",
                "ground_gate": {"stage": "ground", "passed": False, "feedback_route": "HUMAN"},
                "artifact_refs": {"grounding_result": {"artifact_id": "ground-1"}},
                "human_review_decisions": {
                    "action": "accept",
                    "defer_unresolved_spatial_references": True,
                    "deferred_target_ids": ["target-1"],
                },
            }
        )
    )

    assert patch["ground_gate"]["passed"] is False
    assert patch["ground_gate"]["feedback_route"] == "HUMAN"
    assert patch["ground_gate"]["pending_requests"][0]["context"]["remaining_target_ids"] == ["target-2"]
    assert route_after_human_review({
        "paused_stage": "ground",
        "human_review_decisions": {
            "action": "accept",
            "defer_unresolved_spatial_references": True,
        },
        **patch,
    }) == "human_review"


def test_ground_candidate_uses_target_id_not_intervention_id(monkeypatch):
    class Resolver:
        def __init__(self, context):
            self.context = context

        def resolve_spec(self, spec):
            from app.modules.schema.contracts.spatial_reference_contracts import ResolvedSpatialRef

            return ResolvedSpatialRef(final_bsms=["P-1"], confidence=1.0)

    monkeypatch.setattr("app.agent.ground.aggregate.SpatialResolver", Resolver)
    result = ground_aggregate(
        [
            SpatialReferenceSpec(
                type="attributive",
                intervention_id="intervention-1",
                target_id="target-1",
                spec_id="spec-1",
            )
        ],
        object(),
    )

    assert result.candidates[0].target_ref == "target-1"


def test_duplicate_facilities_keep_distinct_target_ids_in_selection(monkeypatch):
    from app.agent.select.aggregate import select_aggregate
    from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult
    from app.modules.schema.contracts.parse_contracts import FacilityTarget, SpatialPlanningIntent
    from app.modules.spatial_ops.selection import PlacementDecision

    parcel_a = SimpleNamespace(
        bsm="P-1",
        dlbm="1201",
        area_sqm=10000.0,
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
    )
    parcel_b = SimpleNamespace(
        bsm="P-2",
        dlbm="1201",
        area_sqm=10000.0,
        geometry={"type": "Polygon", "coordinates": [[[2, 0], [3, 0], [3, 1], [2, 1], [2, 0]]]},
    )
    context = SimpleNamespace(
        session_id="selection-test",
        bundle=SimpleNamespace(polygons={"landuse_current": [parcel_a, parcel_b]}),
        village_anchors=[],
        constraint_index=None,
    )
    intent = SpatialPlanningIntent(
        facilities=[
            FacilityTarget(target_id="facility-1", type="卫生室", candidate_bsms=["P-1"]),
            FacilityTarget(target_id="facility-2", type="卫生室", candidate_bsms=["P-2"]),
        ]
    )
    monkeypatch.setattr(
        "app.agent.select.aggregate.select_parcel",
        lambda target, candidates, **kwargs: PlacementDecision(
            target_id=target.target_id,
            selected_bsm=candidates[0].bsm,
            anchor_point=(0.0, 0.0),
            status="placed",
        ),
    )

    decision, _ = select_aggregate(
        GroundingResult(
            candidates=[
                CandidateSite(site_id="one", source_parcels=["P-1"], target_ref="facility-1"),
                CandidateSite(site_id="two", source_parcels=["P-2"], target_ref="facility-2"),
            ]
        ),
        intent,
        context,
    )

    assert {item.project_ref for item in decision.full_ranking} == {"facility-1", "facility-2"}
    assert set(decision.decision_factors["facility_placements"]) == {"facility-1", "facility-2"}


def test_mixed_action_and_spatial_projects_do_not_emit_action_parcel_changes(monkeypatch):
    from app.agent.execute.execute_state import ExecuteAgentState
    from app.agent.execute.nodes.project_worker import _project_worker
    from app.agent.select.aggregate import select_aggregate
    from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult
    from app.modules.schema.contracts.parse_contracts import ProjectTarget, SpatialPlanningIntent
    from app.modules.schema.contracts.parcel_change_contracts import ParcelChange
    from app.modules.spatial_ops.selection import PlacementDecision

    action_target = ProjectTarget(
        target_id="action-target",
        project_id="action-target",
        name="建立巡查制度",
        execution_mode="non_spatial",
        expected_output_kind="action",
    )
    spatial_target = ProjectTarget(target_id="spatial-target", project_id="spatial-target", name="建设服务点")
    intent = SpatialPlanningIntent(project_targets=[action_target, spatial_target])
    parcel = SimpleNamespace(
        bsm="P-1",
        dlbm="1201",
        area_sqm=10000.0,
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
    )
    context = SimpleNamespace(
        session_id="mixed-test",
        bundle=SimpleNamespace(polygons={"landuse_current": [parcel]}),
        village_anchors=[],
        constraint_index=None,
    )
    monkeypatch.setattr(
        "app.agent.select.aggregate.select_parcel",
        lambda target, candidates, **kwargs: PlacementDecision(
            target_id=target.target_id,
            selected_bsm="P-1",
            anchor_point=(0.0, 0.0),
            status="placed",
        ),
    )
    selection, briefs = select_aggregate(
        GroundingResult(candidates=[CandidateSite(site_id="one", source_parcels=["P-1"], target_ref="spatial-target")]),
        intent,
        context,
    )
    monkeypatch.setattr(
        "app.agent.execute.land_design_worker.design_project_footprint",
        lambda project, brief, bsm, parcels: [ParcelChange(bsm=bsm, project_ref=project.target_id)],
    )

    result = _project_worker(
        ExecuteAgentState(
            intent=intent,
            site_selection=selection,
            land_design_briefs=briefs,
            parcel_by_bsm={"P-1": parcel},
        )
    )

    assert [brief.project_ref for brief in briefs] == ["spatial-target"]
    assert [change.project_ref for change in result.parcel_changes] == ["spatial-target"]
    assert result.action_results[0].target_id == "action-target"
    assert result.action_results[0].expected_output_kind == "action"


def test_review_matches_specs_by_authoritative_target_id():
    from app.agent.parse.review import _spec_ref_for_target

    entry = {"target_id": "target-1", "name": "设施"}
    wrong_spec = SpatialReferenceSpec(
        type="directional",
        intervention_id="other",
        target_id="target-2",
        spec_id="spec-2",
    )

    assert _spec_ref_for_target(entry, {}, [wrong_spec]) == "unmapped"
