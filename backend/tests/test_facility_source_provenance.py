from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.parcel_change_contracts import ParcelChangeSet
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, WorkerTask, WorkerType
from app.contracts.domain.selection_contracts import TargetAssignment
from app.contracts.workflow.parse_contracts import FacilityTarget, SpatialPlanningIntent
from app.domain.delivery.render_layers import build_planned_overlay_layers
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.facility_worker import _facility_worker
from app.domain.materialization.planned_state_builder import changeset_to_planned_state


def _state() -> tuple[ExecuteAgentState, str, str]:
    target_id = "facility:health:001"
    candidate_id = "candidate:facility:health:001"
    target = FacilityTarget(target_id=target_id, type="health", action="new")
    assignment = TargetAssignment(
        target_id=target_id,
        target_type="facility",
        status="placed",
        expected_output_kind="point",
        anchor_point=(9.0, 9.0),
        target_binding={"candidate_id": candidate_id, **target.model_dump(mode="json")},
    )
    task = WorkerTask(
        task_id=f"facility_placement:{target_id}",
        worker_type=WorkerType.FACILITY_PLACEMENT,
        target_id=target_id,
        target_type="facility",
        expected_output_kind="point",
        assignment=assignment,
        candidate_id=candidate_id,
        target_binding={"candidate_id": candidate_id},
        scenario_id="scenario:source-backed",
    )
    candidate = CandidateGeometry(
        candidate_id=candidate_id,
        target_id=target_id,
        kind="point",
        role="execution_geometry",
        wkt="POINT (1 2)",
        granularity="exact_feature",
        source_ref="kg:facility:health:001",
        source_refs=["bundle:facility:health:001"],
        source_bsms=["P-001"],
        hard_constraint_status="passed",
    )
    return (
        ExecuteAgentState(
            tasks_to_run=["facility"],
            parcel_by_bsm={"P-unused": {"geometry": {}}},
            candidate_geometry_by_id={candidate_id: candidate},
            execution_plan=ExecutionPlan(
                plan_id="plan:source-backed",
                worker_tasks=[task],
            ),
        ),
        target_id,
        candidate_id,
    )


def test_facility_worker_uses_selected_point_and_emits_candidate_provenance():
    state, target_id, candidate_id = _state()
    result = _facility_worker(state)
    feature = result.layers[0]["data"]["features"][0]
    properties = feature["properties"]
    assert feature["geometry"] == {"type": "Point", "coordinates": [1.0, 2.0]}
    assert properties["candidate_id"] == candidate_id
    assert properties["source_refs"] == [
        "bundle:facility:health:001",
        "kg:facility:health:001",
    ]
    assert properties["source_bsms"] == ["P-001"]
    assert properties["geometry_ref"] == "kg:facility:health:001"
    assert result.scenario_features[0].source_refs == properties["source_refs"]
    assert result.scenario_features[0].candidate_id == candidate_id
    assert result.scenario_features[0].target_id == target_id


def test_planned_facility_and_render_layer_keep_candidate_provenance():
    state, target_id, candidate_id = _state()
    result = _facility_worker(state)
    intent = SpatialPlanningIntent(
        facilities=[FacilityTarget(target_id=target_id, type="health", action="new")]
    )
    planned = changeset_to_planned_state(ParcelChangeSet(), intent, result.layers)
    facility = planned.facilities[0]
    assert facility.candidate_id == candidate_id
    assert facility.source_bsms == ["P-001"]
    assert facility.source_refs == [
        "bundle:facility:health:001",
        "kg:facility:health:001",
    ]
    assert facility.geometry_ref == "kg:facility:health:001"
    assert facility.geometry == "POINT (1 2)"
    layer = next(
        item for item in build_planned_overlay_layers(planned)
        if item["layerType"] == "facility_point"
    )
    rendered = layer["data"]["features"][0]["properties"]
    assert rendered["candidate_id"] == candidate_id
    assert rendered["source_bsms"] == ["P-001"]
    assert rendered["source_refs"] == facility.source_refs
    assert rendered["geometry_ref"] == "kg:facility:health:001"
