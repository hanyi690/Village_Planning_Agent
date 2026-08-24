"""Facility execution must keep a point candidate local to its footprint."""

from shapely.geometry import Polygon, mapping

from app.contracts.artifacts.classification_ref import ClassificationDecision, ClassificationSystem
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, WorkerTask, WorkerType
from app.contracts.workflow.parse_contracts import FacilityTarget
from app.contracts.workflow.materialization_contracts import TargetAssignment
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.facility_worker import _facility_worker


def test_facility_point_candidate_creates_local_footprint_not_whole_bsm():
    target = FacilityTarget(
        target_id="facility-local",
        type="卫生室",
        action="new",
        classification_decision=ClassificationDecision(
            target_id="facility-local",
            code_system=ClassificationSystem.GBT21010,
            candidate_codes=["1207"],
            selected_code="1207",
            evidence_refs=["l1:fact:facility-local"],
            status="resolved",
        ),
    )
    candidate = CandidateGeometry(
        candidate_id="candidate:facility-local",
        target_id=target.target_id,
        kind="point",
        role="execution_geometry",
        wkt="POINT (0.5 0.5)",
        source_ref="bundle:facility:local",
    )
    assignment = TargetAssignment(
        target_id=target.target_id,
        target_type="facility",
        status="placed",
        target_binding={
            **target.model_dump(mode="json"),
            "candidate_id": candidate.candidate_id,
        },
    )
    plan = ExecutionPlan(worker_tasks=[WorkerTask(
        task_id="facility_placement:facility-local",
        worker_type=WorkerType.FACILITY_PLACEMENT,
        target_id=target.target_id,
        target_type="facility",
        expected_output_kind="point",
        assignment=assignment,
        candidate_id=candidate.candidate_id,
    )])
    large_parcel = {
        "bsm": "P-LARGE",
        "area_ha": 400.0,
        "geometry": mapping(Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])),
    }

    result = _facility_worker(ExecuteAgentState(
        execution_plan=plan,
        candidate_geometry_by_id={candidate.candidate_id: candidate},
        parcel_by_bsm={"P-LARGE": large_parcel},
    ))

    assert result.task_results[0].status == "succeeded"
    assert len(result.parcel_changes) == 1
    change = result.parcel_changes[0]
    assert change.action == "create"
    assert change.derived_from_bsms == []
    assert change.new_area_ha < 1.0


def test_facility_worker_defers_fully_unavailable_candidate():
    target = FacilityTarget(
        target_id="facility-unavailable",
        type="卫生室",
        action="new",
        classification_decision=ClassificationDecision(
            target_id="facility-unavailable",
            code_system=ClassificationSystem.GBT21010,
            candidate_codes=["1207"],
            selected_code="1207",
            evidence_refs=["l1:fact:facility-unavailable"],
            status="resolved",
        ),
    )
    candidate = CandidateGeometry(
        candidate_id="candidate:facility-unavailable",
        target_id=target.target_id,
        kind="point",
        role="execution_geometry",
        wkt="POINT (0.5 0.5)",
        availability_status="fully_unavailable",
    )
    assignment = TargetAssignment(
        target_id=target.target_id,
        target_type="facility",
        status="placed",
        target_binding={
            **target.model_dump(mode="json"),
            "candidate_id": candidate.candidate_id,
        },
    )
    plan = ExecutionPlan(worker_tasks=[WorkerTask(
        task_id="facility_placement:facility-unavailable",
        worker_type=WorkerType.FACILITY_PLACEMENT,
        target_id=target.target_id,
        target_type="facility",
        expected_output_kind="point",
        assignment=assignment,
        candidate_id=candidate.candidate_id,
    )])

    result = _facility_worker(ExecuteAgentState(
        execution_plan=plan,
        candidate_geometry_by_id={candidate.candidate_id: candidate},
    ))

    assert result.task_results[0].status == "deferred"
    assert result.task_results[0].diagnostics[0]["code"] == (
        "candidate_geometry_fully_unavailable"
    )
    assert result.parcel_changes == []
