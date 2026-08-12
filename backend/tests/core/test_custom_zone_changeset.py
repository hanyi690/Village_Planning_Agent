"""Custom vocabulary zones must cross EXECUTE only with a legal decision."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from shapely.geometry import Polygon, mapping

from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.zone_worker import _zone_worker, _zone_worker_node
from app.contracts.artifacts.classification_ref import (
    ClassificationDecision,
    ClassificationSystem,
)
from app.contracts.workflow.execution_plan_contracts import (
    ExecutionPlan,
    WorkerTask,
    WorkerType,
    ZoneAllocationSolution,
    ZoneAssignmentEntry,
)
from app.contracts.workflow.parse_contracts import ZoneTarget
from app.contracts.domain.selection_contracts import TargetAssignment
from app.contracts.domain.custom_zone_contracts import (
    CustomZoneTarget,
    TypingRule,
    Vocabulary,
    VocabularyCategory,
)
from app.domain.materialization.plan_builder import (
    build_execution_plan,
    classification_boundary_diagnostics,
)
from app.domain.materialization.zoning.custom_zone_changeset import (
    materialize_custom_zone_changes,
)
from app.data.encodings.dicts.vocabularies.loader import register_vocabulary
from app.contracts.spatial.spatial_delivery_contracts import SpatialLayerRef
from app.infrastructure.gis.spatial_data_port import GeoJSONSpatialDataPort
from app.infrastructure.export.delivery_snapshot import build_delivery_spatial_snapshot


def _vocabulary(*, rules: list[TypingRule] | None = None) -> Vocabulary:
    return Vocabulary(
        name="test-vocabulary",
        categories=[
            VocabularyCategory(
                code="CUSTOM_ZONE",
                name_zh="自定义功能区",
                typing_rules=rules or [],
            )
        ],
    )


def _parcels() -> dict[str, dict]:
    return {
        "P001": {
            "bsm": "P001",
            "area_ha": 1.0,
            "dlbm": "0101",
            "geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        },
        "P002": {
            "bsm": "P002",
            "area_ha": 2.0,
            "dlbm": "0201",
            "geometry": Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
        },
    }


def _resolved_decision(target_id: str = "custom-zone-1") -> ClassificationDecision:
    return ClassificationDecision(
        target_id=target_id,
        code_system=ClassificationSystem.GBT21010,
        candidate_codes=["1207"],
        selected_code="1207",
        evidence_refs=["human-review:custom-zone"],
        status="resolved",
    )


def target_with_resolved_decision() -> CustomZoneTarget:
    return CustomZoneTarget(
        target_id="custom-zone-1",
        vocabulary_name="test-vocabulary",
        category_code="CUSTOM_ZONE",
        target_bsms=["P001", "P002"],
        classification_decision=_resolved_decision(),
    )


def target_without_decision() -> CustomZoneTarget:
    return CustomZoneTarget(
        target_id="custom-zone-1",
        vocabulary_name="test-vocabulary",
        category_code="CUSTOM_ZONE",
        target_bsms=["P001"],
    )


def target_with_resolved_decision_and_rules() -> CustomZoneTarget:
    return CustomZoneTarget(
        target_id="custom-zone-1",
        vocabulary_name="test-vocabulary",
        category_code="CUSTOM_ZONE",
        target_bsms=[],
        area_target_ha=1.0,
        classification_decision=_resolved_decision(),
    )


def target_with_invalid_decision() -> CustomZoneTarget:
    return CustomZoneTarget.model_construct(
        target_id="custom-zone-1",
        vocabulary_name="test-vocabulary",
        category_code="CUSTOM_ZONE",
        target_bsms=["P001"],
        classification_decision={"status": "resolved", "selected_code": "INVALID"},
    )


def test_resolved_custom_zone_creates_reclassify_changes():
    result = materialize_custom_zone_changes(
        target_with_resolved_decision(), _parcels(), vocabulary=_vocabulary()
    )

    assert [change.bsm for change in result.changes] == ["P001", "P002"]
    assert all(change.action == "reclassify" for change in result.changes)
    assert {change.after_classification.code for change in result.changes} == {"1207"}
    assert all(change.derived_from_bsms == [change.bsm] for change in result.changes)
    assert {change.intervention_id for change in result.changes} == {"custom-zone-1"}
    assert result.changes[0].before_geometry_wkt == _parcels()["P001"]["geometry"].wkt
    assert result.changes[0].after_geometry_wkt == _parcels()["P001"]["geometry"].wkt


def test_custom_category_never_becomes_legal_code_without_decision():
    result = materialize_custom_zone_changes(
        target_without_decision(), _parcels(), vocabulary=_vocabulary()
    )

    assert result.changes == []
    assert any(item["code"] == "classification_unresolved" for item in result.unresolved_items)


def test_custom_zone_uses_generator_selection_and_preserves_audit():
    target = target_with_resolved_decision_and_rules()
    result = materialize_custom_zone_changes(
        target,
        _parcels(),
        vocabulary=_vocabulary(rules=[TypingRule(kind="dlbm_in", value=["0101"])]),
    )

    assert {change.bsm for change in result.changes} == {"P001"}
    assert result.audit is not None
    assert sum(change.new_area_ha for change in result.changes) == 1.0


def test_invalid_resolved_code_is_fail_closed():
    result = materialize_custom_zone_changes(
        target_with_invalid_decision(), _parcels(), vocabulary=_vocabulary()
    )

    assert result.changes == []
    assert any(
        item["code"] in {"classification_invalid", "classification_unresolved"}
        for item in result.unresolved_items
    )


def test_protection_line_excluded_parcel_is_not_materialized():
    result = materialize_custom_zone_changes(
        target_with_resolved_decision(),
        _parcels(),
        vocabulary=_vocabulary(),
        three_lines={
            "ecological_redline": [
                {"geometry": Polygon([(1.5, -1), (3.5, -1), (3.5, 2), (1.5, 2)])}
            ]
        },
    )

    assert [change.bsm for change in result.changes] == ["P001"]


def test_custom_zone_is_scheduled_as_an_existing_zone_task():
    intent = type("Intent", (), {"custom_zone_targets": [target_with_resolved_decision()]})()
    selection = type("Selection", (), {"target_assignments": []})()

    plan = build_execution_plan(intent, selection, [])

    assert [(task.target_type, task.target_id) for task in plan.worker_tasks] == [
        ("zone", "custom-zone-1")
    ]
    assert plan.worker_tasks[0].worker_type.value == "parcel_transformation"


def test_unresolved_custom_zone_is_not_scheduled():
    target = target_without_decision()
    intent = type("Intent", (), {"custom_zone_targets": [target]})()
    selection = type("Selection", (), {"target_assignments": []})()

    plan = build_execution_plan(intent, selection, [])

    assert plan.worker_tasks == []
    assert [item["code"] for item in classification_boundary_diagnostics(intent, plan)] == [
        "classification_decision_required"
    ]


def test_scheduled_custom_zone_reaches_worker_and_delivery(tmp_path):
    target = target_with_resolved_decision()
    intent = type("Intent", (), {"custom_zone_targets": [target]})()
    selection = type("Selection", (), {"target_assignments": []})()
    register_vocabulary("test-vocabulary", _vocabulary())
    plan = build_execution_plan(intent, selection, [])

    state = ExecuteAgentState(execution_plan=plan, parcel_by_bsm=_parcels())
    result = _zone_worker(state)

    assert [change.bsm for change in result.parcel_changes] == ["P001", "P002"]
    assert result.task_results[0].status == "succeeded"
    assert asyncio.run(_zone_worker_node(state))["allocation_summary"]["custom_zone_count"] == 2

    current = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"BSM": bsm},
                "geometry": mapping(parcel["geometry"]),
            }
            for bsm, parcel in _parcels().items()
        ],
    }
    current_path = tmp_path / "current.geojson"
    output_path = tmp_path / "planned.geojson"
    current_path.write_text(json.dumps(current), encoding="utf-8")
    snapshot = build_delivery_spatial_snapshot(
        SpatialLayerRef(artifact_ref="current", path=str(current_path), layer_name="current"),
        result.parcel_changes,
        data_port=GeoJSONSpatialDataPort(),
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert snapshot.change_summary["modified"] == 2
    assert {feature["properties"]["change_status"] for feature in payload["features"]} == {
        "modified"
    }


def test_worker_normalizes_list_protection_lines_before_materializing_custom_zone():
    target = target_with_resolved_decision()
    intent = type("Intent", (), {"custom_zone_targets": [target]})()
    selection = type("Selection", (), {"target_assignments": []})()
    register_vocabulary("test-vocabulary", _vocabulary())
    plan = build_execution_plan(intent, selection, [])
    protection = Polygon([(1.5, -1), (3.5, -1), (3.5, 2), (1.5, 2)])

    result = _zone_worker(ExecuteAgentState(
        execution_plan=plan,
        parcel_by_bsm=_parcels(),
        kg_three_lines=[{"subtype": "ecological_redline", "geometry": protection}],
    ))

    assert [change.bsm for change in result.parcel_changes] == ["P001"]


def test_custom_reservation_excludes_mip_candidates_and_reports_explicit_overlap():
    class CapturingAllocator:
        def __init__(self):
            self.candidates = {}

        def allocate(self, targets, candidates, constraints, metadata):
            self.candidates = candidates
            return ZoneAllocationSolution(
                feasible=True,
                assignments=[ZoneAssignmentEntry(bsm="P003", zone_id="ordinary-mip")],
            )

    custom = target_with_resolved_decision()
    ordinary_overlap = ZoneTarget(
        target_id="ordinary-overlap",
        zone_id="ordinary-overlap",
        land_use="ordinary",
        candidate_bsms=["P001"],
        classification_decision=_resolved_decision("ordinary-overlap"),
    )
    ordinary_mip = ZoneTarget(
        target_id="ordinary-mip",
        zone_id="ordinary-mip",
        land_use="ordinary",
        classification_decision=_resolved_decision("ordinary-mip"),
    )
    intent = type("Intent", (), {
        "zone_targets": [ordinary_overlap, ordinary_mip],
        "custom_zone_targets": [custom],
    })()
    selection = type("Selection", (), {"target_assignments": []})()
    register_vocabulary("test-vocabulary", _vocabulary())
    plan = build_execution_plan(intent, selection, [])
    allocator = CapturingAllocator()
    parcels = _parcels()
    parcels["P003"] = {
        "bsm": "P003",
        "area_ha": 1.5,
        "geometry": mapping(Polygon([(4, 0), (5, 0), (5, 1), (4, 1)])),
    }

    result = _zone_worker(ExecuteAgentState(
        execution_plan=plan,
        parcel_by_bsm=parcels,
        ports=SimpleNamespace(zone_allocator=allocator),
    ))

    assert set(allocator.candidates["ordinary-mip"]) == {"P003"}
    assert [change.bsm for change in result.parcel_changes].count("P001") == 1
    assert len({change.bsm for change in result.parcel_changes}) == len(result.parcel_changes)
    assert any(
        item["code"] == "target_overlap" and item["target_id"] == "ordinary-overlap"
        for item in result.unresolved_items
    )


def test_invalid_custom_task_binding_is_returned_as_a_failed_task():
    binding = target_with_resolved_decision().model_dump(mode="json")
    binding["classification_decision"] = "invalid-persisted-decision"
    task = WorkerTask(
        task_id="parcel_transformation:custom-zone-1",
        worker_type=WorkerType.PARCEL_TRANSFORMATION,
        target_id="custom-zone-1",
        target_type="zone",
        expected_output_kind="parcel",
        assignment=TargetAssignment(
            target_id="custom-zone-1",
            target_type="zone",
            target_binding=binding,
        ),
    )

    result = _zone_worker(ExecuteAgentState(
        execution_plan=ExecutionPlan(worker_tasks=[task]),
        parcel_by_bsm=_parcels(),
    ))

    assert result.task_results[0].status == "failed"
    assert result.task_results[0].task_id == task.task_id
    assert any(
        item["code"] == "custom_zone_binding_invalid" and item["target_id"] == "custom-zone-1"
        for item in result.unresolved_items
    )


def test_worker_fails_closed_for_decision_target_id_mismatch():
    target = target_with_resolved_decision().model_copy(update={
        "classification_decision": _resolved_decision("different-target"),
    })
    intent = type("Intent", (), {"custom_zone_targets": [target]})()
    selection = type("Selection", (), {"target_assignments": []})()
    register_vocabulary("test-vocabulary", _vocabulary())

    result = _zone_worker(ExecuteAgentState(
        execution_plan=build_execution_plan(intent, selection, []),
        parcel_by_bsm=_parcels(),
    ))

    assert result.parcel_changes == []
    assert result.task_results[0].status == "failed"
    assert any(item["code"] == "classification_invalid" for item in result.unresolved_items)


def test_partial_custom_materialization_does_not_report_success():
    target = target_with_resolved_decision().model_copy(update={
        "target_bsms": ["P001", "P404"],
    })

    result = materialize_custom_zone_changes(target, _parcels(), vocabulary=_vocabulary())

    assert [change.bsm for change in result.changes] == ["P001"]
    assert any(item["code"] == "missing_bsm" for item in result.unresolved_items)
    assert not any(item["code"] == "custom_zone_materialized" for item in result.diagnostics)
