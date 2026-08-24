"""Contract probes for the ScenarioSet -> approval -> materializer boundary."""

from types import SimpleNamespace

import pytest

from app.contracts.planning.approval import ApprovedExecutionInput
from app.contracts.planning.scenario import (
    BackendCertificatePayload,
    derive_backend_selection_digest,
    derive_solver_model_digest,
    PlanningScenario,
    ScenarioSet,
    ScenarioTargetSelection,
    SolverCertificate,
)
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.domain.allocation.approval_input import build_approved_execution_input
from app.domain.materialization.approved_plan_builder import (
    bind_approved_execution_plan,
    build_execution_plan_draft,
)
from app.domain.materialization.execution_boundaries import (
    candidate_geometry_drift_diagnostics,
)


def _fixtures():
    candidate = CandidateGeometry(
        candidate_id="candidate:site-1",
        target_id="site-1",
        kind="polygon",
        role="execution_geometry",
        wkt="POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
        source_ref="parcel:1",
        source_bsms=["bsm-1"],
        evidence_refs=["evidence:1"],
        hard_constraint_status="passed",
        availability_status="partially_available",
        eligible_area_ha=3.2,
        excluded_area_ha=0.8,
        adjacent_parcel_bsms=["bsm-2"],
        adjacency_evidence_refs=["bundle:landuse_current:bsm-1:adjacent:bsm-2"],
    )
    scenario = PlanningScenario(
        scenario_id="scenario-1",
        baseline_ref="baseline-1",
        problem_fingerprint="problem-1",
        target_selections=[
            ScenarioTargetSelection(
                target_id="site-1",
                selection_mode="choose_one",
                candidate_ids=[candidate.candidate_id],
            )
        ],
        status="complete",
    )
    proof = BackendCertificatePayload(
        backend_id="test-backend",
        backend_version="1",
        problem_kind="single_choice",
        problem_fingerprint="problem-1",
        input_digest="input-1",
        solver_config={
            "deterministic_seed": 0,
            "search_limit": 0,
            "time_limit_seconds": None,
            "max_scenarios": 8,
            "objective_definitions": [],
            "backend_version": "1",
            "replay_settings": {},
        },
        selected_candidate_ids={"site-1": [candidate.candidate_id]},
        selection_digest=derive_backend_selection_digest(
            {"site-1": [candidate.candidate_id]},
            [],
        ),
        status="feasible",
    )
    certificate = SolverCertificate(
        problem_fingerprint="problem-1",
        model_digest=derive_solver_model_digest(proof, deterministic_seed=0, search_limit=0),
        solver_version="test",
        status="feasible",
        feasible_scenario_count=1,
        problem_kind="single_choice",
        backend_id="test-backend",
        backend_version="1",
        backend_certificate=proof,
    )
    scenario_set = ScenarioSet(
        set_id="scenario-set-1",
        problem_fingerprint="problem-1",
        scenarios=[scenario],
        feasible_scenario_ids=[scenario.scenario_id],
        recommended_scenario_id=scenario.scenario_id,
        solver_certificate=certificate,
    )
    intent = SimpleNamespace(
        site_area_targets=[
            SimpleNamespace(
                target_id="site-1",
                requires_spatial=True,
                expected_output_kind="polygon",
                action="new",
            )
        ]
    )
    problem = SimpleNamespace(candidate_geometries=[candidate])
    return scenario_set, scenario, intent, problem, candidate


def _forged_same_id_member(scenario: PlanningScenario) -> PlanningScenario:
    return PlanningScenario(**{
        **scenario.model_dump(mode="python", exclude={"fingerprint"}),
        "target_selections": [ScenarioTargetSelection(
            target_id="site-1",
            selection_mode="choose_one",
            candidate_ids=["candidate:forged"],
        )],
    })


def test_plan_is_projected_from_approved_scenario_member():
    scenario_set, scenario, intent, problem, candidate = _fixtures()

    draft = build_execution_plan_draft(
        scenario_set,
        scenario,
        intent,
        problem,
    )
    approval = build_approved_execution_input(
        scenario_set=scenario_set,
        scenario=scenario,
        scenario_set_ref=scenario_set.set_id,
        scenario_ref=scenario.scenario_id,
        approval_id="approval-1",
        approval_status="auto",
        execution_plan=draft,
    )
    plan = bind_approved_execution_plan(draft, approval, scenario_set, scenario)

    assert len(plan.worker_tasks) == 1
    task = plan.worker_tasks[0]
    assert task.candidate_id == candidate.candidate_id
    assert task.target_binding["candidate_geometry_wkt"] == candidate.wkt
    assert task.target_binding["evidence_refs"] == candidate.evidence_refs
    assert task.scenario_id == scenario.scenario_id
    assert plan.problem_fingerprint == scenario.problem_fingerprint
    assert task.source_feature_ids == candidate.source_feature_ids
    assert task.entity_refs == candidate.entity_refs
    assert task.relation_refs == task.relation_ids
    assert task.availability_status == "partially_available"
    assert task.eligible_area_ha == 3.2
    assert task.excluded_area_ha == 0.8
    assert task.adjacent_parcel_bsms == ["bsm-2"]
    assert task.adjacency_evidence_refs == [
        "bundle:landuse_current:bsm-1:adjacent:bsm-2"
    ]
    assert task.assignment.adjacent_parcel_bsms == ["bsm-2"]


def test_scoped_plan_excludes_explicitly_deferred_intent_target():
    scenario_set, scenario, intent, problem, _candidate = _fixtures()
    intent.site_area_targets.append(
        SimpleNamespace(
            target_id="road-deferred",
            requires_spatial=True,
            expected_output_kind="line",
            action="new",
        )
    )
    problem.deferred_target_ids = ["road-deferred"]

    draft = build_execution_plan_draft(scenario_set, scenario, intent, problem)

    assert [task.target_id for task in draft.worker_tasks] == ["site-1"]


@pytest.mark.parametrize(
    ("approval_status", "approval_fields"),
    [
        ("auto", {}),
        (
            "human_approved",
            {
                "approved_by": "reviewer:1",
                "approval_reason": "manual selection",
            },
        ),
    ],
)
def test_approval_builder_rejects_forged_same_id_scenario_member(
    approval_status,
    approval_fields,
):
    scenario_set, scenario, intent, problem, _candidate = _fixtures()
    draft = build_execution_plan_draft(scenario_set, scenario, intent, problem)
    forged = _forged_same_id_member(scenario)

    approval = build_approved_execution_input(
        scenario_set=scenario_set,
        scenario=forged,
        scenario_set_ref=scenario_set.set_id,
        scenario_ref=forged.scenario_id,
        approval_id=f"approval:forged:{approval_status}",
        approval_status=approval_status,
        execution_plan=draft,
        **approval_fields,
    )

    assert approval is None


def test_assert_and_plan_binding_reject_forged_same_id_scenario_member():
    scenario_set, scenario, intent, problem, _candidate = _fixtures()
    draft = build_execution_plan_draft(scenario_set, scenario, intent, problem)
    approval = build_approved_execution_input(
        scenario_set=scenario_set,
        scenario=scenario,
        scenario_set_ref=scenario_set.set_id,
        scenario_ref=scenario.scenario_id,
        approval_id="approval:formal-member",
        approval_status="auto",
        execution_plan=draft,
    )
    assert approval is not None
    forged = _forged_same_id_member(scenario)

    with pytest.raises(ValueError, match="formal ScenarioSet member"):
        approval.assert_matches(scenario_set, forged)
    with pytest.raises(ValueError, match="formal ScenarioSet member"):
        bind_approved_execution_plan(draft, approval, scenario_set, forged)


def test_missing_approved_geometry_fails_closed():
    scenario_set, scenario, intent, _problem, _candidate = _fixtures()
    empty_problem = SimpleNamespace(candidate_geometries=[])

    draft = build_execution_plan_draft(
        scenario_set,
        scenario,
        intent,
        SimpleNamespace(candidate_geometries=[_candidate]),
    )
    approval = build_approved_execution_input(
        scenario_set=scenario_set,
        scenario=scenario,
        scenario_set_ref=scenario_set.set_id,
        scenario_ref=scenario.scenario_id,
        approval_id="approval-1",
        approval_status="auto",
        execution_plan=draft,
    )

    with pytest.raises(ValueError, match="candidate geometry is missing"):
        build_execution_plan_draft(
            scenario_set,
            scenario,
            intent,
            empty_problem,
        )


@pytest.mark.parametrize("selection_mode", ["all_members", "choose_subset"])
def test_multi_candidate_selection_expands_losslessly_into_materializer_tasks(selection_mode):
    scenario_set, _scenario, intent, _problem, first = _fixtures()
    second = first.model_copy(
        update={
            "candidate_id": "candidate:site-2",
            "source_ref": "parcel:2",
            "source_bsms": ["bsm-2"],
            "evidence_refs": ["evidence:2"],
            "wkt": "POLYGON ((2 2, 2 3, 3 3, 3 2, 2 2))",
        }
    )
    scenario = PlanningScenario(**{
        **scenario_set.scenarios[0].model_dump(
            mode="python",
            exclude={"fingerprint"},
        ),
        "target_selections": [ScenarioTargetSelection(
            target_id="site-1",
            selection_mode=selection_mode,
            candidate_ids=[first.candidate_id, second.candidate_id],
        )],
        "status": "complete",
    })
    selected = {"site-1": [first.candidate_id, second.candidate_id]}
    proof = BackendCertificatePayload(
        backend_id="test-backend",
        backend_version="1",
        problem_kind="parcel_assignment",
        problem_fingerprint=scenario.problem_fingerprint,
        input_digest=f"input:{selection_mode}",
        solver_config={
            "deterministic_seed": 0,
            "search_limit": 0,
            "time_limit_seconds": None,
            "max_scenarios": 8,
            "objective_definitions": [],
            "backend_version": "1",
            "replay_settings": {},
        },
        selected_candidate_ids=selected,
        selection_digest=derive_backend_selection_digest(selected, []),
        status="feasible",
    )
    scenario_set = ScenarioSet(
        set_id=scenario_set.set_id,
        problem_fingerprint=scenario.problem_fingerprint,
        scenarios=[scenario],
        feasible_scenario_ids=[scenario.scenario_id],
        recommended_scenario_id=scenario.scenario_id,
        solver_certificate=SolverCertificate(
            problem_fingerprint=scenario.problem_fingerprint,
            model_digest=derive_solver_model_digest(
                proof,
                deterministic_seed=0,
                search_limit=0,
            ),
            solver_version="test-backend:1",
            status="feasible",
            feasible_scenario_count=1,
            problem_kind="parcel_assignment",
            backend_id="test-backend",
            backend_version="1",
            backend_certificate=proof,
        ),
    )
    draft = build_execution_plan_draft(
        scenario_set,
        scenario,
        intent,
        SimpleNamespace(candidate_geometries=[first, second]),
    )

    assert [task.candidate_id for task in draft.worker_tasks] == [
        first.candidate_id,
        second.candidate_id,
    ]
    assert all(len(task.candidate_ids) == 1 for task in draft.worker_tasks)
    assert {
        task.target_binding["candidate_id"] for task in draft.worker_tasks
    } == {first.candidate_id, second.candidate_id}
    assert {
        task.target_binding["evidence_refs"][0] for task in draft.worker_tasks
    } == {"evidence:1", "evidence:2"}
    approval = build_approved_execution_input(
        scenario_set=scenario_set,
        scenario=scenario,
        scenario_set_ref=scenario_set.set_id,
        scenario_ref=scenario.scenario_id,
        approval_id=f"approval-{selection_mode}",
        approval_status="auto",
        execution_plan=draft,
    )
    bound = bind_approved_execution_plan(draft, approval, scenario_set, scenario)
    assert set(bound.candidate_ids) == {first.candidate_id, second.candidate_id}
    assert len(bound.worker_tasks) == 2
    assert {
        task.target_binding["candidate_id"]: task.target_binding["evidence_refs"]
        for task in bound.worker_tasks
    } == {
        first.candidate_id: first.evidence_refs,
        second.candidate_id: second.evidence_refs,
    }


@pytest.mark.parametrize("field, value", [
    ("wkt", "POLYGON ((10 10, 10 11, 11 11, 11 10, 10 10))"),
    ("role", "parcel_candidate"),
    ("evidence_refs", ["evidence:changed"]),
])
def test_execute_rejects_approved_candidate_catalog_drift(field, value):
    scenario_set, scenario, intent, problem, candidate = _fixtures()
    draft = build_execution_plan_draft(scenario_set, scenario, intent, problem)
    changed = candidate.model_copy(update={field: value})

    assert candidate_geometry_drift_diagnostics(draft, {candidate.candidate_id: candidate}) == []
    diagnostics = candidate_geometry_drift_diagnostics(draft, {candidate.candidate_id: changed})

    assert diagnostics
    assert diagnostics[0]["code"] == "EXECUTE_APPROVED_CANDIDATE_GEOMETRY_MISMATCH"
    assert diagnostics[0]["candidate_id"] == candidate.candidate_id


def test_execution_result_mapper_preserves_each_approved_candidate_lineage():
    from app.workflow.stages.execute import _task_results_from_execution

    scenario_set, base_scenario, intent, first_problem, first = _fixtures()
    second = first.model_copy(update={
        "candidate_id": "candidate:site-2",
        "source_feature_ids": ["source-feature:2"],
        "entity_refs": ["entity:2"],
        "relation_refs": ["relation:2"],
        "evidence_refs": ["evidence:2"],
        "wkt": "POLYGON ((2 2, 2 3, 3 3, 3 2, 2 2))",
    })
    scenario = base_scenario.model_copy(update={
        "target_selections": [ScenarioTargetSelection(
            target_id="site-1",
            selection_mode="all_members",
            candidate_ids=[first.candidate_id, second.candidate_id],
        )]
    })
    scenario_set = scenario_set.model_copy(update={"scenarios": [scenario]})
    problem = SimpleNamespace(candidate_geometries=[first, second])
    draft = build_execution_plan_draft(scenario_set, scenario, intent, problem)
    records = []
    for task in draft.worker_tasks:
        records.append({
            "task_id": task.task_id,
            "status": "succeeded",
            "feature_ids": [f"feature:{task.candidate_id}"],
            "source_feature_ids": list(task.source_feature_ids),
            "entity_refs": list(task.entity_refs),
            "relation_refs": list(task.relation_refs),
        })

    mapped = _task_results_from_execution(draft, {
        "tasks_to_run": ["site_area"],
        "worker_results": [{"worker_type": "site_area", "task_results": records}],
        "execution_errors": [],
        "action_results": [],
    })

    by_candidate = {item.candidate_id: item for item in mapped["task_results"]}
    assert set(by_candidate) == {first.candidate_id, second.candidate_id}
    for task in draft.worker_tasks:
        result = by_candidate[task.candidate_id]
        assert result.feature_ids == [f"feature:{task.candidate_id}"]
        assert result.source_feature_ids == task.source_feature_ids
        assert result.entity_refs == task.entity_refs
        assert result.relation_refs == task.relation_refs


def test_legacy_selection_fallbacks_are_not_materializer_authority():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "app"
    project_source = (root / "domain/materialization/nodes/project_worker.py").read_text()
    road_source = (root / "domain/materialization/nodes/road_worker.py").read_text()
    builder_source = (root / "domain/materialization/approved_plan_builder.py").read_text()

    assert "full_ranking" not in project_source
    assert "execute_road_planning_from_agent_state" not in road_source
    assert "RoadPlannerPort" not in road_source
    assert "SiteSelectionDecision" not in builder_source
    assert "build_execution_plan_draft" in builder_source


def test_select_formal_call_graph_uses_scenario_draft_and_binding():
    from pathlib import Path

    select_source = (
        Path(__file__).resolve().parents[2] / "app/workflow/stages/select.py"
    ).read_text()

    assert "build_execution_plan_draft" in select_source
    assert "bind_approved_execution_plan" in select_source
    assert "build_worker_projection" not in select_source
    assert "build_execution_plan(" not in select_source
    assert "SiteSelectionDecision" not in select_source
    assert "site_selection" not in select_source
    assert "allocate_zones_for_select" not in select_source
    assert "allocate_non_zone_for_select" not in select_source


def test_artifact_ref_tombstones_invalidate_old_approval_and_plan():
    from app.workflow.state import _merge_artifact_refs
    from app.workflow.plan_state.state import _merge_artifact_refs as _merge_plan_refs

    current = {
        "approved_execution_input": {"digest": "old-approval"},
        "execution_plan": {"digest": "old-plan"},
        "scenario_set": {"digest": "scenario"},
    }
    update = {"approved_execution_input": None, "execution_plan": None}

    assert "approved_execution_input" not in _merge_artifact_refs(current, update)
    assert "execution_plan" not in _merge_artifact_refs(current, update)
    assert "scenario_set" in _merge_plan_refs(current, update)
