from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shapely.geometry import Polygon, mapping

from app.contracts.domain.selection_contracts import TargetAssignment
from app.contracts.spatial.global_zone_allocation_contracts import (
    AuthoritativeZoneParcelAssignment,
    GlobalZoneAllocationResult,
    ZoneAssignmentLineage,
    ZoneOverlayTargetRef,
)
from app.contracts.workflow.execution_plan_contracts import (
    ExecutionPlan,
    WorkerTask,
    WorkerType,
)
from app.contracts.workflow.parse_contracts import ZoneTarget
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.land_design_worker import design_all, design_zone_parcel
from app.domain.materialization.nodes.zone_worker import _zone_worker
from app.domain.materialization.worker_contract import WorkerInput
from app.domain.materialization.zone_worker import run_worker


def _parcel(bsm: str) -> dict:
    return {
        "bsm": bsm,
        "area_ha": 1.0,
        "geometry": mapping(Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])),
    }


def _assignment(
    target_id: str = "zone-A",
    bsm: str = "P1",
) -> AuthoritativeZoneParcelAssignment:
    return AuthoritativeZoneParcelAssignment(
        target_id=target_id,
        zone_id=f"planning-{target_id}",
        bsm=bsm,
        land_use="设施农用地",
        classification_system="gbt21010",
        classification_code="1207",
        area_ha=1.0,
        suitability_score=0.9,
        score_breakdown={"composite": 0.9},
        lineage=ZoneAssignmentLineage(
            lineage_id=f"lineage-{target_id}-{bsm}",
            target_id=target_id,
            zone_id=f"planning-{target_id}",
            source_instruction_id=f"instruction-{target_id}",
            source_report_key=f"report-{target_id}",
            claim_refs=[f"claim-{target_id}"],
            classification_evidence_refs=[f"classification-{target_id}"],
            candidate_provenance_refs=[f"candidate-{target_id}-{bsm}"],
            parcel_provenance_refs=[f"parcel-{bsm}"],
            geometry_ref=f"bundle://parcel/{bsm}",
        ),
    )


def _allocation(
    assignments: list[AuthoritativeZoneParcelAssignment],
    *,
    overlays: list[ZoneOverlayTargetRef] | None = None,
) -> GlobalZoneAllocationResult:
    return GlobalZoneAllocationResult(
        status="OPTIMAL",
        feasible=True,
        complete=True,
        assignments=assignments,
        overlay_targets=overlays or [],
    )


def _state(*target_ids: str) -> ExecuteAgentState:
    tasks = []
    for target_id in target_ids:
        target = ZoneTarget(
            target_id=target_id,
            zone_id=f"planning-{target_id}",
            land_use="设施农用地",
            area_ha=1.0,
            candidate_bsms=["P1", "P2"],
        )
        tasks.append(
            WorkerTask(
                task_id=f"parcel_transformation:{target_id}",
                worker_type=WorkerType.PARCEL_TRANSFORMATION,
                target_id=target_id,
                target_type="zone",
                expected_output_kind="polygon",
                assignment=TargetAssignment(
                    target_id=target_id,
                    target_type="zone",
                    target_binding=target.model_dump(mode="json"),
                ),
            )
        )
    return ExecuteAgentState(
        execution_plan=ExecutionPlan(worker_tasks=tasks),
        parcel_by_bsm={"P1": _parcel("P1"), "P2": _parcel("P2")},
    )


def test_land_design_rejects_zone_target_and_only_consumes_authoritative_assignment():
    target = ZoneTarget(
        target_id="zone-A",
        zone_id="planning-zone-A",
        land_use="设施农用地",
        candidate_bsms=["P1", "P2"],
    )

    assert design_zone_parcel(target, {"P1": _parcel("P1"), "P2": _parcel("P2")}) == []

    changes = design_zone_parcel(_assignment(), {"P1": _parcel("P1")})

    assert [change.bsm for change in changes] == ["P1"]
    assert changes[0].intervention_id == "zone-A"
    assert changes[0].project_ref == "zone-A"


def test_design_all_requires_explicit_zone_assignments_instead_of_intent_candidates():
    target = ZoneTarget(
        target_id="zone-A",
        zone_id="planning-zone-A",
        land_use="设施农用地",
        candidate_bsms=["P1"],
    )
    intent = SimpleNamespace(
        project_targets=[],
        facilities=[],
        zone_targets=[target],
    )
    selection = SimpleNamespace(selected_combination=[])

    without_artifact = design_all(intent, selection, [], {"P1": _parcel("P1")})
    with_artifact = design_all(
        intent,
        selection,
        [],
        {"P1": _parcel("P1")},
        zone_assignments=[_assignment()],
    )

    assert without_artifact.changes == []
    assert [change.bsm for change in with_artifact.changes] == ["P1"]


def test_zone_worker_materializes_only_allocator_assignments_not_target_candidates():
    result = _zone_worker(
        _state("zone-A"),
        allocation_result=_allocation([_assignment("zone-A", "P1")]),
    )

    assert [change.bsm for change in result.parcel_changes] == ["P1"]
    assert result.task_results[0].status == "succeeded"
    assignment_layer = next(
        layer for layer in result.layers
        if layer["layerType"] == "authoritative_zone_assignment"
    )
    properties = assignment_layer["data"]["features"][0]["properties"]
    assert properties["target_id"] == "zone-A"
    assert properties["project_ref"] == "zone-A"
    assert properties["lineage_id"] == "lineage-zone-A-P1"
    assert properties["geometry_ref"] == "bundle://parcel/P1"


def test_zone_worker_without_global_allocation_artifact_fails_closed():
    result = _zone_worker(_state("zone-A"))

    assert result.parcel_changes == []
    assert result.task_results[0].status == "failed"
    assert any(
        item["code"] == "global_zone_allocation_missing"
        for item in result.unresolved_items
    )


def test_zone_worker_rejects_invalid_allocation_payload_without_candidate_fallback():
    result = _zone_worker(
        _state("zone-A"),
        allocation_result={"status": "OPTIMAL", "assignments": "not-a-list"},
    )

    assert result.parcel_changes == []
    assert result.task_results[0].status == "failed"
    assert any(
        item["code"] == "global_zone_allocation_invalid"
        for item in result.unresolved_items
    )


def test_duplicate_assignment_bsm_blocks_entire_zone_materialization():
    duplicate = GlobalZoneAllocationResult.model_construct(
        status="OPTIMAL",
        feasible=True,
        complete=True,
        assignments=[_assignment("zone-A", "P1"), _assignment("zone-B", "P1")],
        area_balances=[],
        unassigned_bsms=[],
        overlay_targets=[],
        objective_value=0.0,
        diagnostics=[],
        input_provenance_refs=[],
    )

    result = _zone_worker(_state("zone-A", "zone-B"), allocation_result=duplicate)

    assert result.parcel_changes == []
    assert all(item.status == "failed" for item in result.task_results)
    assert any(
        item["code"] == "authoritative_assignment_duplicate_bsm"
        for item in result.unresolved_items
    )


def test_missing_assignment_parcel_blocks_all_zone_changes_instead_of_partial_write():
    result = _zone_worker(
        _state("zone-A", "zone-B"),
        allocation_result=_allocation(
            [_assignment("zone-A", "P1"), _assignment("zone-B", "P404")]
        ),
    )

    assert result.parcel_changes == []
    assert any(
        item["code"] == "assignment_parcel_missing" and item["bsm"] == "P404"
        for item in result.unresolved_items
    )


def test_protection_overlay_is_independent_from_authoritative_land_use_change():
    overlay = ZoneOverlayTargetRef(
        target_id="protect-1",
        materialization_role="protection_overlay",
        candidate_bsms=["P1"],
        provenance_refs=["claim-protect-1"],
    )

    result = _zone_worker(
        _state("zone-A"),
        allocation_result=_allocation([_assignment()], overlays=[overlay]),
    )

    assert [change.bsm for change in result.parcel_changes] == ["P1"]
    assert {layer["layerType"] for layer in result.layers} == {
        "authoritative_zone_assignment",
        "protection_overlay",
    }
    overlay_feature = next(
        layer for layer in result.layers if layer["layerType"] == "protection_overlay"
    )["data"]["features"][0]
    assert overlay_feature["properties"]["materialization_role"] == "protection_overlay"
    assert overlay_feature["properties"]["project_ref"] == "protect-1"
    assert overlay_feature["properties"]["bsm"] == "P1"


def test_explicit_adapter_can_read_allocation_from_dependency_without_state_slot():
    state = _state("zone-A")
    state.ports = SimpleNamespace(
        global_zone_allocation_result=_allocation([_assignment()])
    )

    result = _zone_worker(state)

    assert [change.bsm for change in result.parcel_changes] == ["P1"]


def test_canonical_zone_wrapper_requires_artifact_ref_and_typed_dependency():
    missing_ref = WorkerInput(
        worker="zone",
        target_ref="zone-A",
        task_ref="parcel_transformation:zone-A",
    )

    blocked = asyncio.run(run_worker(missing_ref, deps={"state": _state("zone-A")}))

    assert blocked.status == "blocked"
    assert blocked.code == "worker_needs_explicit_input"

    explicit = missing_ref.model_copy(update={
        "input_refs": {"global_zone_allocation_ref": "artifact:zone-allocation"}
    })
    completed = asyncio.run(run_worker(
        explicit,
        deps={
            "state": _state("zone-A"),
            "global_zone_allocation_result": _allocation([_assignment()]),
        },
    ))

    assert completed.status == "succeeded"
    assert completed.change_refs == ["P1", "authoritative_zone_assignment"]
