from __future__ import annotations

from app.contracts.workflow.materialization_contracts import TargetAssignment
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, WorkerTask, WorkerType
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.worker_common import _scenario_features_for_layer
from app.domain.materialization.planned_state_builder import changeset_to_planned_state
from app.contracts.spatial.parcel_change_contracts import ParcelChangeSet


def _state() -> ExecuteAgentState:
    task = WorkerTask(
        task_id="facility_1",
        worker_type=WorkerType.FACILITY_PLACEMENT,
        target_id="facility-1",
        target_type="facility",
        expected_output_kind="point",
        assignment=TargetAssignment(
            target_id="facility-1",
            target_type="facility",
            status="placed",
            selected_bsm="B001",
            expected_output_kind="point",
            target_binding={"target_id": "facility-1"},
        ),
        scenario_id="scenario-1",
        candidate_id="candidate:facility-1:B001",
        relation_ids=["serve-1"],
        target_binding={"target_id": "facility-1"},
        input_artifact_refs=["artifact:selection:1"],
    )
    return ExecuteAgentState(
        execution_plan=ExecutionPlan(plan_id="plan-1", worker_tasks=[task]),
    )


def test_worker_layer_becomes_complete_scenario_feature_lineage() -> None:
    state = _state()
    layer = {
        "layerType": "facility_point",
        "data": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"target_id": "facility-1"},
                "geometry": {"type": "Point", "coordinates": [116.1, 24.1]},
            }],
        },
    }

    features = _scenario_features_for_layer(
        state, layer, generation_operation="facility_worker"
    )

    assert len(features) == 1
    feature = features[0]
    assert feature.scenario_id == "scenario-1"
    assert feature.target_id == "facility-1"
    assert feature.candidate_id == "candidate:facility-1:B001"
    assert feature.relation_ids == ["serve-1"]
    assert feature.source_refs == ["artifact:selection:1"]
    assert feature.generation_operation == "facility_worker"
    assert layer["data"]["features"][0]["properties"]["feature_id"] == feature.feature_id


def test_planned_state_does_not_infer_single_target_for_unbound_layer() -> None:
    state = changeset_to_planned_state(
        ParcelChangeSet(changes=[]),
        intent=None,
        layout_configs=[{
            "layerType": "facility_point",
            "data": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "Point", "coordinates": [116.1, 24.1]},
                }],
            },
        }],
    )

    assert state.facilities == []
