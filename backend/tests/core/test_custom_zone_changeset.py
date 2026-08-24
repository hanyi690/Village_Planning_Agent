"""Custom vocabulary zones must cross EXECUTE only with a legal decision."""

from __future__ import annotations

from shapely.geometry import Polygon, mapping

from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.zone_worker import _zone_worker
from app.contracts.artifacts.classification_ref import (
    ClassificationDecision,
    ClassificationSystem,
)
from app.contracts.workflow.execution_plan_contracts import (
    ExecutionPlan,
    WorkerTask,
    WorkerType,
)
from app.contracts.workflow.parse_contracts import ZoneTarget
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.workflow.materialization_contracts import TargetAssignment
from app.contracts.domain.custom_zone_contracts import (
    CustomZoneTarget,
    TypingRule,
    Vocabulary,
    VocabularyCategory,
)
from app.domain.materialization.execution_boundaries import classification_boundary_diagnostics
from app.domain.materialization.zoning.custom_zone_changeset import (
    materialize_custom_zone_changes,
)
from app.data.encodings.dicts.vocabularies.loader import register_vocabulary


def build_execution_plan(intent, selection, _briefs, **_kwargs):
    """Test-local approval-bound task fixture for custom-zone workers."""
    targets = {
        target.target_id: target
        for field in ("custom_zone_targets", "zone_targets")
        for target in getattr(intent, field, [])
    }
    tasks = []
    for assignment in selection.target_assignments:
        target = targets.get(assignment.target_id)
        if target is None:
            continue
        decision = getattr(target, "classification_decision", None)
        role = getattr(target, "materialization_role", "")
        if getattr(decision, "status", "") != "resolved" and role not in {
            "functional_overlay", "protection_overlay", "restoration_overlay",
        }:
            continue
        refs = list(assignment.input_artifact_refs or [])
        tasks.append(WorkerTask(
            task_id=f"parcel_transformation:{assignment.target_id}",
            worker_type=WorkerType.PARCEL_TRANSFORMATION,
            target_id=assignment.target_id,
            target_type=assignment.target_type,
            expected_output_kind=assignment.expected_output_kind,
            assignment=assignment,
            input_artifact_refs=refs,
        ))
    return ExecutionPlan(worker_tasks=tasks)


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


def _ready_selection(*targets):
    return type("Selection", (), {
        "target_assignments": [
            TargetAssignment(
                target_id=target.target_id,
                target_type="zone",
                status="ready",
                expected_output_kind=getattr(target, "expected_output_kind", "parcel"),
                target_binding=target.model_dump(mode="json"),
            )
            for target in targets
        ]
    })()


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
    target = target_with_resolved_decision()
    intent = type("Intent", (), {"custom_zone_targets": [target]})()
    selection = _ready_selection(target)

    plan = build_execution_plan(
        intent,
        selection,
        [],
    )

    assert [(task.target_type, task.target_id) for task in plan.worker_tasks] == [
        ("zone", "custom-zone-1")
    ]
    assert plan.worker_tasks[0].worker_type.value == "parcel_transformation"
    assert plan.worker_tasks[0].input_artifact_refs == []


def test_unresolved_custom_zone_is_not_scheduled():
    target = target_without_decision()
    intent = type("Intent", (), {"custom_zone_targets": [target]})()
    selection = _ready_selection(target)

    plan = build_execution_plan(intent, selection, [])

    assert plan.worker_tasks == []
    assert [item["code"] for item in classification_boundary_diagnostics(intent, plan)] == [
        "classification_decision_required"
    ]


def test_scheduled_custom_zone_reaches_worker_as_functional_overlay():
    target = target_with_resolved_decision()
    intent = type("Intent", (), {"custom_zone_targets": [target]})()
    selection = _ready_selection(target)
    register_vocabulary("test-vocabulary", _vocabulary())
    plan = build_execution_plan(intent, selection, [])

    state = ExecuteAgentState(execution_plan=plan, parcel_by_bsm=_parcels())
    result = _zone_worker(state)

    assert result.parcel_changes == []
    assert result.task_results[0].status == "succeeded"
    layer = result.layers[0]
    assert layer["layerType"] == "functional_zone_overlay"
    assert {
        feature["properties"]["bsm"]
        for feature in layer["data"]["features"]
    } == {"P001", "P002"}
    assert sum(
        len((layer.get("data") or {}).get("features") or [])
        for layer in result.layers
        if str(layer.get("layerType") or "").endswith("overlay")
    ) == 2


def test_worker_does_not_reclassify_or_query_three_lines_for_functional_overlay():
    target = target_with_resolved_decision()
    intent = type("Intent", (), {"custom_zone_targets": [target]})()
    selection = _ready_selection(target)
    register_vocabulary("test-vocabulary", _vocabulary())
    plan = build_execution_plan(intent, selection, [])
    protection = Polygon([(1.5, -1), (3.5, -1), (3.5, 2), (1.5, 2)])

    result = _zone_worker(ExecuteAgentState(
        execution_plan=plan,
        parcel_by_bsm=_parcels(),
        kg_three_lines=[{"subtype": "ecological_redline", "geometry": protection}],
    ))

    assert result.parcel_changes == []
    assert {
        feature["properties"]["bsm"]
        for feature in result.layers[0]["data"]["features"]
    } == {"P001", "P002"}


def test_zone_worker_never_calls_legacy_allocator_or_builds_full_parcel_pool():
    class CapturingAllocator:
        def __init__(self):
            self.called = False

        def allocate(self, targets, candidates, constraints, metadata):
            self.called = True
            raise AssertionError("legacy allocator must not be called by materialization")

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
    selection = _ready_selection(custom, ordinary_overlap, ordinary_mip)
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
        ports=type("Ports", (), {"zone_allocator": allocator})(),
    ))

    assert allocator.called is False
    assert result.parcel_changes == []
    assert any(
        item["code"] == "approved_zone_binding_missing"
        for item in result.unresolved_items
    )
    functional = next(
        layer for layer in result.layers
        if layer["layerType"] == "functional_zone_overlay"
    )
    assert {
        feature["properties"]["bsm"]
        for feature in functional["data"]["features"]
    } == {"P001", "P002"}


def test_zone_worker_defers_scope_candidate_without_expanding_to_parcel():
    target = ZoneTarget(
        target_id="scope-zone",
        zone_id="scope-zone",
        land_use="生态控制范围",
        classification_decision=_resolved_decision("scope-zone"),
    )
    candidate = CandidateGeometry(
        candidate_id="candidate:scope-zone",
        target_id="scope-zone",
        kind="polygon",
        role="scope_geometry",
        wkt="POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))",
        source_ref="l1:fact:scope-zone",
    )
    assignment = TargetAssignment(
        target_id="scope-zone",
        target_type="zone",
        status="placed",
        target_binding={"candidate_id": candidate.candidate_id},
    )
    plan = ExecutionPlan(worker_tasks=[WorkerTask(
        task_id="parcel_transformation:scope-zone",
        worker_type=WorkerType.PARCEL_TRANSFORMATION,
        target_id="scope-zone",
        target_type="zone",
        expected_output_kind="polygon",
        assignment=assignment,
        candidate_id=candidate.candidate_id,
    )])

    result = _zone_worker(ExecuteAgentState(
        execution_plan=plan,
        candidate_geometry_by_id={candidate.candidate_id: candidate},
        parcel_by_bsm=_parcels(),
    ))

    assert result.parcel_changes == []
    assert result.layers == []
    assert result.task_results[0].status == "deferred"
    assert any(
        item["code"] == "candidate_geometry_not_executable"
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
    selection = _ready_selection(target)
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
