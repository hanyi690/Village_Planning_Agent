"""EXECUTE zone tests: only approval-bound scenario geometry is authoritative."""

from types import SimpleNamespace

from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, WorkerTask, WorkerType
from app.contracts.workflow.materialization_contracts import TargetAssignment
from app.contracts.workflow.parse_contracts import ZoneTarget
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.zone_worker import _zone_worker


def _candidate(candidate_id: str, wkt: str) -> CandidateGeometry:
    return CandidateGeometry(
        candidate_id=candidate_id,
        target_id="zone-A",
        kind="polygon",
        role="execution_geometry",
        wkt=wkt,
        source_bsms=["approved-parcel"],
        source_feature_ids=["source-feature:approved"],
        entity_refs=["entity:approved"],
        relation_refs=["relation:approved"],
        evidence_refs=["evidence:approved"],
        hard_constraint_status="passed",
    )


def _state(candidate: CandidateGeometry) -> ExecuteAgentState:
    target = ZoneTarget(
        target_id="zone-A",
        zone_id="planning-zone-A",
        land_use="设施农用地",
        area_ha=1.0,
        candidate_bsms=["approved-parcel"],
    )
    binding = {
        **target.model_dump(mode="json"),
        "candidate_id": candidate.candidate_id,
        "candidate_geometry_wkt": candidate.wkt,
        "geometry_role": candidate.role,
        "source_feature_ids": candidate.source_feature_ids,
        "entity_refs": candidate.entity_refs,
        "relation_refs": candidate.relation_refs,
        "evidence_refs": candidate.evidence_refs,
    }
    task = WorkerTask(
        task_id="zone_synthesis:zone-A",
        worker_type=WorkerType.PARCEL_TRANSFORMATION,
        target_id="zone-A",
        target_type="zone",
        expected_output_kind="polygon",
        assignment=TargetAssignment(
            target_id="zone-A",
            target_type="zone",
            expected_output_kind="polygon",
            status="placed",
            target_binding=binding,
        ),
        scenario_id="scenario-approved",
        candidate_id=candidate.candidate_id,
        candidate_ids=[candidate.candidate_id],
        target_binding=binding,
        source_feature_ids=candidate.source_feature_ids,
        entity_refs=candidate.entity_refs,
        relation_refs=candidate.relation_refs,
        evidence_refs=candidate.evidence_refs,
    )
    return ExecuteAgentState(
        execution_plan=ExecutionPlan(
            scenario_id="scenario-approved",
            candidate_ids=[candidate.candidate_id],
            worker_tasks=[task],
        ),
        candidate_geometry_by_id={candidate.candidate_id: candidate},
        parcel_by_bsm={
            "approved-parcel": {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                }
            }
        },
        tasks_to_run=["layout"],
    )


def test_zone_worker_materializes_only_approved_candidate_geometry():
    candidate = _candidate(
        "candidate:approved",
        "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
    )

    result = _zone_worker(_state(candidate))

    assert result.task_results[0].status == "succeeded"
    layer = next(layer for layer in result.layers if layer["layerType"] == "planned_zone")
    feature = layer["data"]["features"][0]
    assert feature["properties"]["candidate_id"] == candidate.candidate_id
    assert feature["properties"]["source_feature_ids"] == candidate.source_feature_ids
    assert feature["properties"]["entity_refs"] == candidate.entity_refs


def test_zone_worker_defers_fully_unavailable_parcel_candidate():
    candidate = _candidate(
        "candidate:unavailable",
        "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
    ).model_copy(update={
        "spatial_domain_kind": "parcel_extent",
        "source_area_ha": 1.0,
        "planning_area_ha": 0.0,
        "availability_status": "fully_unavailable",
    })

    result = _zone_worker(_state(candidate))

    assert result.task_results[0].status == "deferred"
    assert result.task_results[0].diagnostics[0]["code"] == (
        "candidate_geometry_fully_unavailable"
    )
    assert result.layers == []


def test_zone_worker_keeps_partial_parcel_candidate_executable():
    candidate = _candidate(
        "candidate:partial",
        "POLYGON ((0 0, 0 0.5, 0.5 0.5, 0.5 0, 0 0))",
    ).model_copy(update={
        "spatial_domain_kind": "parcel_extent",
        "source_area_ha": 1.0,
        "planning_area_ha": 0.25,
        "eligible_area_ha": 0.6,
        "excluded_area_ha": 0.4,
        "availability_status": "partially_available",
    })

    result = _zone_worker(_state(candidate))

    assert result.task_results[0].status == "succeeded"
    feature = next(layer for layer in result.layers if layer["layerType"] == "planned_zone")[
        "data"
    ]["features"][0]
    assert feature["properties"]["availability_status"] == "partially_available"
    assert feature["properties"]["excluded_area_ha"] == 0.4


def test_contradictory_global_allocation_cannot_change_approved_zone_output():
    candidate = _candidate(
        "candidate:approved",
        "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
    )
    state = _state(candidate)
    state.ports = SimpleNamespace(
        global_zone_allocation_result={
            "assignments": [{"target_id": "zone-A", "bsm": "wrong-parcel"}],
        }
    )

    result = _zone_worker(state)

    feature = next(layer for layer in result.layers if layer["layerType"] == "planned_zone")["data"]["features"][0]
    assert feature["properties"]["candidate_id"] == candidate.candidate_id
    assert feature["properties"]["source_bsms"] == candidate.source_bsms
    assert not any("global_zone_allocation" in str(item) for item in result.unresolved_items)


def test_zone_worker_keeps_two_approved_candidates_as_two_task_lineage_rows():
    first = _candidate(
        "candidate:approved-1",
        "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
    )
    second = _candidate(
        "candidate:approved-2",
        "POLYGON ((2 2, 2 3, 3 3, 3 2, 2 2))",
    )
    state = _state(first)
    first_task = state.execution_plan.worker_tasks[0]
    second_binding = dict(first_task.target_binding)
    second_binding.update({
        "candidate_id": second.candidate_id,
        "candidate_geometry_wkt": second.wkt,
    })
    second_task = first_task.model_copy(update={
        "task_id": "parcel_transformation:zone-A:candidate:approved-2",
        "candidate_id": second.candidate_id,
        "candidate_ids": [second.candidate_id],
        "target_binding": second_binding,
        "assignment": first_task.assignment.model_copy(update={"target_binding": second_binding}),
    })
    state.execution_plan = state.execution_plan.model_copy(update={
        "candidate_ids": [first.candidate_id, second.candidate_id],
        "worker_tasks": [first_task, second_task],
    })
    state.candidate_geometry_by_id[second.candidate_id] = second

    result = _zone_worker(state)

    assert len(result.task_results) == 2
    assert {item.candidate_id for item in result.task_results} == {
        first.candidate_id,
        second.candidate_id,
    }
    features = next(layer for layer in result.layers if layer["layerType"] == "planned_zone")["data"]["features"]
    assert {item["properties"]["candidate_id"] for item in features} == {
        first.candidate_id,
        second.candidate_id,
    }
