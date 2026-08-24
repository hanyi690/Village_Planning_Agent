from types import SimpleNamespace

from app.contracts.spatial.planned_state_contracts import (
    PlannedFacility,
    PlannedState,
    PlannedRoad,
)
from app.contracts.workflow.materialization_contracts import TargetAssignment
from app.contracts.workflow.execution_plan_contracts import (
    ExecutionPlan,
    TaskExecutionResult,
    WorkerTask,
    WorkerType,
)
from app.domain.delivery.render_layers import build_planned_overlay_layers
from app.domain.validation.validate_checks import check_bundle_snapshot_lineage


def test_render_layers_preserve_feature_and_snapshot_lineage() -> None:
    state = PlannedState(
        facilities=[
            PlannedFacility(
                name="祠堂",
                facility_type="ancestral_hall",
                geometry="POINT (116 23)",
                derived_from_target="facility-1",
                feature_bsms=["44142621100000000123"],
                source_feature_ids=["poi:ancestral-hall-1"],
                entity_refs=["kg:entity:facility-1"],
                relation_refs=["kg:relation:within-village"],
                evidence_refs=["l1:fact:ancestral-hall"],
                l1_snapshot_ref="artifact://l1/snapshot-1",
                bundle_snapshot_digest="bundle-1",
            )
        ],
        roads=[
            PlannedRoad(
                name="村道",
                geometry="LINESTRING (116 23, 116.001 23.001)",
                derived_from_target="road-1",
                evidence_refs=["kg:relation:road-connects"],
                bundle_snapshot_digest="bundle-1",
            )
        ],
    )

    layers = build_planned_overlay_layers(state)
    facility = next(layer for layer in layers if layer["layerType"] == "facility_point")
    feature = facility["data"]["features"][0]
    properties = feature["properties"]

    assert properties["feature_bsms"] == ["44142621100000000123"]
    assert properties["source_feature_ids"] == ["poi:ancestral-hall-1"]
    assert properties["entity_refs"] == ["kg:entity:facility-1"]
    assert properties["relation_refs"] == ["kg:relation:within-village"]
    assert properties["evidence_refs"] == ["l1:fact:ancestral-hall"]
    assert properties["l1_snapshot_ref"] == "artifact://l1/snapshot-1"
    assert properties["bundle_snapshot_digest"] == "bundle-1"


def test_bundle_snapshot_validation_rejects_mixed_task_lineage() -> None:
    assignment = TargetAssignment(target_id="lineage-target", target_type="facility")
    plan = ExecutionPlan(
        worker_tasks=[
            WorkerTask(
                task_id="task-1",
                worker_type=WorkerType.FACILITY_PLACEMENT,
                target_id="facility-1",
                target_type="facility",
                expected_output_kind="point",
                assignment=assignment,
                bundle_snapshot_digest="bundle-1",
            ),
            WorkerTask(
                task_id="task-2",
                worker_type=WorkerType.ROAD_CONSTRUCTION,
                target_id="road-1",
                target_type="road",
                expected_output_kind="line",
                assignment=assignment,
                bundle_snapshot_digest="bundle-2",
            ),
        ]
    )
    result = SimpleNamespace(
        task_results=[
            TaskExecutionResult(
                task_id="task-1",
                target_id="facility-1",
                status="succeeded",
                bundle_snapshot_digest="bundle-1",
            )
        ],
        bundle_snapshot_digest="",
    )

    check = check_bundle_snapshot_lineage(
        None,
        plan,
        result,
        current_bundle_digest="bundle-1",
    )[0]

    assert check.passed is False
    assert check.code == "bundle_snapshot_lineage"
    assert "bundle-2" in check.actual_value
