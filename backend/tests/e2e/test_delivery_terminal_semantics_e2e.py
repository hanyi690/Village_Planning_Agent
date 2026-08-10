"""Task 4 delivery, rendering, audit, API, and SSE acceptance tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent.deliver.aggregate import deliver_aggregate
from app.agent.deliver.gate import deliver_gate_route
from app.agent.deliver.render_layers import build_render_layers
from app.agent.execute.planned_state_builder import changeset_to_planned_state
from app.agent.plan_state.state import state_to_ui_status
from app.modules.schema.contracts.deferral_contracts import (
    DeferralLedger,
    HumanDeferralDecision,
    TargetDeferral,
)
from app.modules.schema.contracts.delivery_manifest_contracts import DeliveryManifest
from app.modules.schema.contracts.execution_plan_contracts import (
    ExecutionOutcome,
    ExecutionPlan,
    ExecutionResult,
    TypedActionResult,
    WorkerTask,
    WorkerType,
)
from app.modules.schema.contracts.parcel_change_contracts import ParcelChangeSet
from app.modules.schema.contracts.planned_state_contracts import (
    PlannedAxis,
    PlannedFacility,
    PlannedParcel,
    PlannedRoad,
    PlannedState,
)
from app.modules.schema.contracts.reconciliation_contracts import (
    CoverageMatrix,
    CoverageMatrixRow,
    ReconciliationReport,
)
from app.modules.schema.contracts.selection_contracts import TargetAssignment
from app.modules.schema.contracts.validation_report_contracts import ValidationReport
from app.utils.event_factory import create_completed_event


def _task(
    target_id: str,
    output_kind: str,
    worker_type: WorkerType,
    *,
    target_type: str,
) -> WorkerTask:
    return WorkerTask(
        task_id=f"{worker_type.value}:{target_id}",
        worker_type=worker_type,
        target_id=target_id,
        target_type=target_type,
        expected_output_kind=output_kind,
        assignment=TargetAssignment(
            target_id=target_id,
            target_type=target_type,
            expected_output_kind=output_kind,
            target_binding={"target_id": target_id},
        ),
    )


def _report(*rows: CoverageMatrixRow) -> ReconciliationReport:
    return ReconciliationReport(coverage_matrix=CoverageMatrix(rows=list(rows)))


def _validation() -> ValidationReport:
    return ValidationReport(checks=[], overall_passed=True)


def _ledger(target_id: str) -> DeferralLedger:
    return DeferralLedger(
        entries=(
            TargetDeferral(
                target_id=target_id,
                reason="operator_deferred",
                source_refs=("artifact:execution_outcome:test",),
                decision=HumanDeferralDecision(
                    decision_id="review-1",
                    decided_by="planner",
                    rationale="Deliver the verified remainder now.",
                ),
            ),
        )
    )


def test_delivery_manifest_is_v2_and_rejects_unknown_terminal_status():
    manifest = DeliveryManifest(delivery_status="complete")

    assert manifest.schema_version == "2.0"
    with pytest.raises(ValidationError):
        DeliveryManifest(delivery_status="running")


def test_controlled_partial_is_terminal_and_carries_action_deferral_traceability():
    spatial = _task(
        "facility-active",
        "point",
        WorkerType.FACILITY_PLACEMENT,
        target_type="facility",
    )
    action = _task(
        "action-active",
        "action",
        WorkerType.NON_SPATIAL_ACTION,
        target_type="project",
    )
    deferred = _task(
        "road-deferred",
        "line",
        WorkerType.ROAD_CONSTRUCTION,
        target_type="road",
    )
    plan = ExecutionPlan(worker_tasks=[spatial, action], deferred_tasks=[deferred])
    outcome = ExecutionOutcome(
        task_results=[
            ExecutionResult(
                task_id=spatial.task_id,
                target_id=spatial.target_id,
                status="succeeded",
                expected_output_kind="point",
                output_artifacts=["facility_point"],
            ),
            ExecutionResult(
                task_id=action.task_id,
                target_id=action.target_id,
                status="succeeded",
                expected_output_kind="action",
                output_artifacts=["action"],
            ),
            ExecutionResult(
                task_id=deferred.task_id,
                target_id=deferred.target_id,
                status="deferred",
                expected_output_kind="line",
            ),
        ],
        action_results=[
            TypedActionResult(target_id="action-active", action="建立运营台账")
        ],
    )
    report = _report(
        CoverageMatrixRow(
            target_id="facility-active",
            target_type="facility",
            expected_output_kind="point",
            execution_task_id=spatial.task_id,
            output_artifacts=["facility_point"],
            intervention_id="facility-active",
            status="covered",
        ),
        CoverageMatrixRow(
            target_id="action-active",
            target_type="project",
            expected_output_kind="action",
            execution_task_id=action.task_id,
            output_artifacts=["action"],
            intervention_id="action-active",
            status="covered",
        ),
        CoverageMatrixRow(
            target_id="road-deferred",
            target_type="road",
            expected_output_kind="line",
            execution_task_id=deferred.task_id,
            intervention_id="road-deferred",
            status="deferred",
        ),
    )
    ledger = _ledger("road-deferred")

    manifest = deliver_aggregate(
        PlannedState(
            facilities=[
                PlannedFacility(
                    name="卫生室",
                    facility_type="医疗",
                    geometry="POINT (116 24)",
                    derived_from_target="facility-active",
                )
            ]
        ),
        _validation(),
        report,
        [],
        {
            "exported_files": [
                "current/boundary.geojson",
                "current/landuse.geojson",
                "planned/landuse.geojson",
                "planned/ecological_protection.geojson",
                "planned/farmland_protection.geojson",
                "planned/construction_zone.geojson",
            ]
        },
        execution_plan=plan,
        execution_outcome=outcome,
        deferral_ledger=ledger,
        expected_spatial_output_count=1,
        render_layer_count=1,
    )

    assert manifest.delivery_status == "partial", manifest.diagnostic_summary
    assert manifest.statutory_complete is False
    assert deliver_gate_route(manifest) == "PASS"
    assert manifest.deferral_ledger == ledger
    assert manifest.deferral_summary == {
        "count": 1,
        "target_ids": ["road-deferred"],
        "actions": ["defer"],
    }
    assert [item.target_id for item in manifest.action_results] == ["action-active"]
    assert {item.target_id: item.status for item in manifest.traceability} == {
        "facility-active": "covered",
        "action-active": "covered",
        "road-deferred": "deferred",
    }


def test_non_deferred_spatial_render_gap_is_diagnostic_terminal():
    spatial = _task(
        "facility-missing",
        "point",
        WorkerType.FACILITY_PLACEMENT,
        target_type="facility",
    )
    manifest = deliver_aggregate(
        PlannedState(),
        _validation(),
        _report(
            CoverageMatrixRow(
                target_id=spatial.target_id,
                target_type="facility",
                expected_output_kind="point",
                execution_task_id=spatial.task_id,
                intervention_id=spatial.target_id,
                status="covered",
            )
        ),
        [],
        None,
        execution_plan=ExecutionPlan(worker_tasks=[spatial]),
        execution_outcome=ExecutionOutcome(
            task_results=[
                ExecutionResult(
                    task_id=spatial.task_id,
                    target_id=spatial.target_id,
                    status="succeeded",
                    expected_output_kind="point",
                    output_artifacts=["point"],
                )
            ]
        ),
        expected_spatial_output_count=1,
        render_layer_count=0,
    )

    assert manifest.delivery_status == "diagnostic_only"
    assert deliver_gate_route(manifest) == "END_DIAGNOSTIC"
    assert manifest.diagnostic_summary["blocking_count"] > 0
    assert "hi-render-empty" in manifest.diagnostic_summary["blocking_item_ids"]


def test_action_only_delivery_is_complete_and_mapless():
    action = _task(
        "action-only",
        "action",
        WorkerType.NON_SPATIAL_ACTION,
        target_type="project",
    )
    manifest = deliver_aggregate(
        PlannedState(),
        _validation(),
        _report(
            CoverageMatrixRow(
                target_id=action.target_id,
                target_type="project",
                expected_output_kind="action",
                execution_task_id=action.task_id,
                output_artifacts=["action"],
                intervention_id=action.target_id,
                status="covered",
            )
        ),
        [],
        None,
        execution_plan=ExecutionPlan(worker_tasks=[action]),
        execution_outcome=ExecutionOutcome(
            task_results=[
                ExecutionResult(
                    task_id=action.task_id,
                    target_id=action.target_id,
                    status="succeeded",
                    expected_output_kind="action",
                    output_artifacts=["action"],
                )
            ],
            action_results=[TypedActionResult(target_id=action.target_id, action="巡查")],
        ),
        expected_spatial_output_count=0,
        render_layer_count=0,
    )

    assert build_render_layers(PlannedState()) == []
    assert manifest.delivery_status == "complete"
    assert manifest.statutory_complete is False
    assert not any(item.item_id.startswith("hi-render-") for item in manifest.pending_human_items)


def test_render_layers_are_derived_exclusively_from_planned_state():
    planned = PlannedState(
        parcels=[
            PlannedParcel(
                bsm="parcel-1",
                planning_land_use="0701",
                geometry="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
            )
        ],
        facilities=[
            PlannedFacility(
                name="卫生室",
                facility_type="医疗",
                geometry="POINT (2 2)",
                derived_from_target="facility-1",
            )
        ],
        roads=[
            PlannedRoad(
                name="村道",
                road_level="村道",
                geometry="LINESTRING (0 0, 2 2)",
                derived_from_target="road-1",
            )
        ],
        axes=[
            PlannedAxis(
                name="发展轴",
                geometry="LINESTRING (0 2, 2 0)",
                derived_from_target="axis-1",
            )
        ],
    )

    layers = build_render_layers(planned)

    assert {layer["layerType"] for layer in layers} == {
        "function_zone",
        "facility_point",
        "planned_road",
        "development_axis",
    }
    assert all(
        feature.get("geometry")
        for layer in layers
        for feature in layer["data"]["features"]
    )
    assert {
        feature["properties"].get("target_id")
        for layer in layers
        for feature in layer["data"]["features"]
        if feature["properties"].get("target_id")
    } == {"facility-1", "road-1", "axis-1"}


def test_planned_state_materializes_worker_geometry_and_target_provenance():
    layers = [
        {
            "layerType": "facility_point",
            "data": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "target_id": "facility-1",
                            "facility_type": "医疗",
                            "name": "卫生室",
                        },
                        "geometry": {"type": "Point", "coordinates": [116.0, 24.0]},
                    }
                ],
            },
        },
        {
            "layerType": "planned_road",
            "data": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"target_id": "road-1", "road_level": "村道"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[116.0, 24.0], [116.1, 24.1]],
                        },
                    }
                ],
            },
        },
        {
            "layerType": "infrastructure",
            "data": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"target_id": "axis-1", "name": "发展轴"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[116.0, 24.1], [116.1, 24.0]],
                        },
                    }
                ],
            },
        },
    ]

    planned = changeset_to_planned_state(ParcelChangeSet(), layout_configs=layers)

    assert planned.facilities[0].derived_from_target == "facility-1"
    assert planned.facilities[0].geometry.startswith("POINT")
    assert planned.roads[0].derived_from_target == "road-1"
    assert planned.roads[0].geometry.startswith("LINESTRING")
    assert planned.axes[0].derived_from_target == "axis-1"
    assert planned.axes[0].geometry.startswith("LINESTRING")


def test_api_status_and_completed_sse_expose_terminal_summaries():
    deferral_summary = {
        "count": 1,
        "target_ids": ["road-deferred"],
        "actions": ["defer"],
    }
    terminal = {
        "stage": "validate",
        "reason": "remaining_non_deferred_structural_blockers",
    }
    status = state_to_ui_status(
        {
            "session_id": "terminal-status",
            "phase": "completed",
            "delivery_status": "partial",
            "deferral_summary": deferral_summary,
            "diagnostic_terminal": {},
        }
    )
    event = create_completed_event(
        "terminal-status",
        delivery_status="diagnostic_only",
        deferral_summary=deferral_summary,
        diagnostic_terminal=terminal,
    )

    assert status["status"] == "completed"
    assert status["delivery_status"] == "partial"
    assert status["deferral_summary"] == deferral_summary
    assert event["delivery_status"] == "diagnostic_only"
    assert event["deferral_summary"] == deferral_summary
    assert event["diagnostic_terminal"] == terminal


@pytest.mark.asyncio
async def test_stage_audit_exposes_gate_checksums_fingerprint_route_and_progress(monkeypatch):
    from app.agent.bootstrap import stage_audit

    saved = []

    async def capture(*args, **kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(stage_audit, "_save", capture)

    @stage_audit.audited_stage("VALIDATE")
    async def validate_node(_state):
        return {
            "artifact_refs": {"validation_report": {"artifact_id": "report-1"}},
            "validate_gate": {
                "passed": False,
                "feedback_route": "END_DIAGNOSTIC",
                "input_checksum": "gate-input",
                "output_checksum": "gate-output",
                "issue_fingerprint": "issue-1",
                "route_reason": "identical_no_progress",
                "progress_made": False,
            },
        }

    await validate_node({"session_id": "audit-1", "artifact_refs": {}})

    completed = saved[-1]
    diagnostics = completed["diagnostics"]
    assert diagnostics["gate_input_checksum"] == "gate-input"
    assert diagnostics["gate_output_checksum"] == "gate-output"
    assert diagnostics["issue_fingerprint"] == "issue-1"
    assert diagnostics["route_reason"] == "identical_no_progress"
    assert diagnostics["progress_made"] is False


@pytest.mark.asyncio
async def test_stage_audit_uses_semantic_refs_for_all_post_l3_stages(monkeypatch):
    from app.agent.bootstrap import stage_audit

    saved = []

    async def capture(*args, **kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(stage_audit, "_save", capture)
    ref = {
        "artifact_id": "stable-id",
        "artifact_type": "TypedArtifact",
        "semantic_checksum": "semantic-content",
        "checksum": "raw-content",
        "stored_at": "volatile-time-a",
    }

    for stage in ("PARSE", "GROUND", "SELECT", "EXECUTE"):
        saved.clear()

        @stage_audit.audited_stage(stage)
        async def stage_node(_state, _stage=stage):
            result = {"artifact_refs": {"output": ref}}
            if _stage != "EXECUTE":
                result[f"{_stage.lower()}_gate"] = {
                    "passed": True,
                    "feedback_route": None,
                }
            return result

        await stage_node({
            "session_id": f"audit-{stage}",
            "artifact_refs": {"input": ref},
            "context_ref": {"session_id": "audit", "version": "1"},
        })
        completed = saved[-1]
        diagnostics = completed["diagnostics"]
        inputs = completed["inputs"]
        outputs = completed["outputs"]
        for key in (
            "gate_input_checksum",
            "gate_output_checksum",
            "issue_fingerprint",
            "route_reason",
        ):
            assert diagnostics[key]
        assert diagnostics["gate_route"] == "PASS"
        assert diagnostics["progress_made"] is True
        assert inputs["input_checksum"]
        assert outputs["output_checksum"]
        assert "stored_at" not in str(inputs)
        assert "stored_at" not in str(outputs)

        ref["stored_at"] = "volatile-time-b"
        await stage_node({
            "session_id": f"audit-{stage}",
            "artifact_refs": {"input": ref},
            "context_ref": {"session_id": "audit", "version": "1"},
        })
        second = saved[-1]
        assert second["inputs"]["input_checksum"] == inputs["input_checksum"]
        assert second["outputs"]["output_checksum"] == outputs["output_checksum"]
