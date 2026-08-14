"""EXECUTE consumes VALIDATE repair directives (P0-2 wiring)."""

from __future__ import annotations

from types import SimpleNamespace

from app.contracts.spatial.global_zone_allocation_contracts import (
    AuthoritativeZoneParcelAssignment,
    GlobalZoneAllocationResult,
    ZoneAssignmentLineage,
)
from app.contracts.workflow.execution_plan_contracts import (
    ExecutionPlan,
    TaskExecutionResult,
    WorkerTask,
    WorkerType,
)
from app.contracts.workflow.repair_directive_contracts import (
    RepairDirective,
    RepairDirectiveCompilation,
    RepairDirectiveType,
    RepairEvidenceScope,
)
from app.domain.materialization.nodes.zone_worker import _repair_skip_bsms, _zone_worker
from app.workflow.stages.execute import (
    _apply_execute_repair_to_intent,
    _build_exec_repair_payload,
    _mark_require_evidence_unresolved,
)

_SHA = "sha256:" + "a" * 64


def _directive(
    target_id: str,
    directive_type: RepairDirectiveType,
    *,
    affected_bsms: list[str] | None = None,
    exclude_bsms: list[str] | None = None,
    rebuild_strategy: str | None = None,
    evidence_scope: RepairEvidenceScope | None = None,
    required_evidence: list[str] | None = None,
) -> RepairDirective:
    return RepairDirective(
        directive_id=f"repair-{target_id}",
        directive_type=directive_type,
        target_id=target_id,
        source_violation_ids=[f"v-{target_id}"],
        source_artifact_key="validation_report",
        source_artifact_digest=_SHA,
        affected_bsms=affected_bsms or [],
        exclude_bsms=exclude_bsms or [],
        evidence_scope=evidence_scope,
        required_evidence=required_evidence or [],
        rebuild_strategy=rebuild_strategy,
        reason_code="test",
        issue_fingerprint=_SHA,
    )


def test_build_exec_repair_payload_extracts_require_evidence_targets() -> None:
    compilation = RepairDirectiveCompilation(
        status="ready",
        directives=[
            _directive(
                "zone-A",
                RepairDirectiveType.REBUILD_GEOMETRY,
                affected_bsms=["P1"],
                rebuild_strategy="repair_invalid_geometry",
            ),
            _directive(
                "road-x",
                RepairDirectiveType.REQUIRE_SOURCE_EVIDENCE,
                evidence_scope=RepairEvidenceScope.TARGET_CONTRACT,
                required_evidence=["road_mode"],
            ),
        ],
    )

    payload, require_evidence = _build_exec_repair_payload(compilation)

    assert set(payload) == {"zone-A", "road-x"}
    assert payload["zone-A"]["rebuild_strategy"] == "repair_invalid_geometry"
    assert payload["zone-A"]["affected_bsms"] == ["P1"]
    assert require_evidence == ["road-x"]


def test_apply_execute_repair_to_intent_reroute_avoids_bsms() -> None:
    from app.contracts.workflow.parse_contracts import RoadTarget, SpatialPlanningIntent

    road = RoadTarget(
        target_id="road-route",
        road_planning_kind="new_corridor",
        path_bsms=["P1", "P2", "P3"],
        candidate_bsms=["P1", "P2"],
    )
    intent = SpatialPlanningIntent(road_targets=[road])
    payload = {
        "road-route": {
            "directive_type": "rebuild_geometry",
            "affected_bsms": ["P2"],
            "rebuild_strategy": "reroute_avoiding_bsms",
        }
    }

    revised, changed = _apply_execute_repair_to_intent(intent, payload)

    assert changed is True
    assert revised.road_targets[0].path_bsms == ["P1", "P3"]
    assert revised.road_targets[0].candidate_bsms == ["P1"]
    assert intent.road_targets[0].path_bsms == ["P1", "P2", "P3"]


def test_apply_execute_repair_to_intent_drops_require_evidence_roads() -> None:
    from app.contracts.workflow.parse_contracts import RoadTarget, SpatialPlanningIntent

    road = RoadTarget(target_id="road-x", road_planning_kind="new_corridor")
    intent = SpatialPlanningIntent(road_targets=[road])
    payload = {
        "road-x": {
            "directive_type": "require_source_evidence",
            "required_evidence": ["road_mode"],
        }
    }

    revised, changed = _apply_execute_repair_to_intent(intent, payload)

    assert changed is True
    assert revised.road_targets == []


def test_mark_require_evidence_unresolved_appends_typed_failed_result() -> None:
    from app.contracts.domain.selection_contracts import TargetAssignment

    task = WorkerTask(
        task_id="road_construction:road-x",
        worker_type=WorkerType.ROAD_CONSTRUCTION,
        target_id="road-x",
        target_type="road",
        expected_output_kind="line",
        assignment=TargetAssignment(
            target_id="road-x",
            target_type="road",
            status="placed",
            target_binding={},
        ),
    )
    plan = ExecutionPlan(worker_tasks=[task])
    outcome = {"task_results": [], "action_results": [], "diagnostics": []}

    result = _mark_require_evidence_unresolved(outcome, plan, ["road-x"])

    marked = result["task_results"][0]
    assert isinstance(marked, TaskExecutionResult)
    assert marked.target_id == "road-x"
    assert marked.status == "failed"
    assert marked.task_id == "road_construction:road-x"
    assert any(item["code"] == "require_source_evidence" for item in marked.diagnostics)


def test_zone_worker_skips_bsms_marked_by_repair_directive() -> None:
    from app.contracts.domain.selection_contracts import TargetAssignment
    from app.contracts.workflow.parse_contracts import ZoneTarget
    from app.domain.materialization.execute_state import ExecuteAgentState
    from shapely.geometry import Polygon, mapping

    target = ZoneTarget(
        target_id="zone-A",
        zone_id="planning-zone-A",
        land_use="设施农用地",
        area_ha=1.0,
        candidate_bsms=["P1", "P2"],
    )
    task = WorkerTask(
        task_id="parcel_transformation:zone-A",
        worker_type=WorkerType.PARCEL_TRANSFORMATION,
        target_id="zone-A",
        target_type="zone",
        expected_output_kind="polygon",
        assignment=TargetAssignment(
            target_id="zone-A",
            target_type="zone",
            target_binding=target.model_dump(mode="json"),
        ),
    )

    def assignment(bsm: str) -> AuthoritativeZoneParcelAssignment:
        return AuthoritativeZoneParcelAssignment(
            target_id="zone-A",
            zone_id="planning-zone-A",
            bsm=bsm,
            land_use="设施农用地",
            classification_system="gbt21010",
            classification_code="1207",
            area_ha=1.0,
            suitability_score=0.9,
            score_breakdown={},
            lineage=ZoneAssignmentLineage(
                lineage_id=f"lineage-{bsm}",
                target_id="zone-A",
                zone_id="planning-zone-A",
                source_instruction_id="i1",
                source_report_key="r1",
                claim_refs=["c1"],
                classification_evidence_refs=["cl1"],
                candidate_provenance_refs=["cp1"],
                parcel_provenance_refs=[f"parcel-{bsm}"],
                geometry_ref=f"bundle://parcel/{bsm}",
            ),
        )

    parcel = lambda bsm: {  # noqa: E731
        "bsm": bsm,
        "area_ha": 1.0,
        "geometry": mapping(Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])),
    }
    state = ExecuteAgentState(
        execution_plan=ExecutionPlan(worker_tasks=[task]),
        parcel_by_bsm={"P1": parcel("P1"), "P2": parcel("P2")},
        repair_directives={
            "zone-A": {
                "directive_type": "rebuild_geometry",
                "affected_bsms": ["P1"],
                "exclude_bsms": [],
                "rebuild_strategy": "repair_invalid_geometry",
            }
        },
    )
    allocation = GlobalZoneAllocationResult(
        status="OPTIMAL",
        feasible=True,
        complete=True,
        assignments=[assignment("P1"), assignment("P2")],
        overlay_targets=[],
    )

    assert _repair_skip_bsms(state, "zone-A") == {"P1"}
    result = _zone_worker(state, allocation_result=allocation)

    assert [change.bsm for change in result.parcel_changes] == ["P2"]
    assert any(
        item["code"] == "assignment_skipped_by_repair" and item["bsm"] == "P1"
        for item in result.unresolved_items
    )
    assert result.task_results[0].status == "succeeded"
