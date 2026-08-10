from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.agent.bootstrap.graph import (
    END_DIAGNOSTIC,
    apply_human_review_decision,
    route_after_human_review,
    route_after_validate,
)
from app.agent.reconcile.aggregate import build_coverage_matrix
from app.agent.reconcile.aggregate import check_target_execution_coverage
from app.agent.reconcile.gate import evaluate_reconcile_gate
from app.agent.validate.checks import check_topology, check_traceability
from app.agent.validate.gate import evaluate_validate_gate
from app.modules.schema.contracts.execution_plan_contracts import (
    ExecutionOutcome,
    ExecutionPlan,
    ExecutionResult,
    WorkerTask,
    WorkerType,
)
from app.modules.schema.contracts.planned_state_contracts import PlannedParcel, PlannedState
from app.modules.schema.contracts.planned_state_contracts import PlannedZone
from app.modules.schema.contracts.reconciliation_contracts import (
    CoverageMatrix,
    CoverageMatrixRow,
    ReconciliationInconsistency,
    ReconciliationReport,
)
from app.modules.schema.contracts.selection_contracts import TargetAssignment
from app.modules.schema.contracts.validation_report_contracts import (
    ValidationCheck,
    ValidationIssue,
    ValidationReport,
)
from app.modules.ports.artifact_store import ArtifactRef
from app.services.artifact_store import FilesystemArtifactStore


def _task(
    target_id: str,
    output_kind: str,
    *,
    target_type: str = 'project',
) -> WorkerTask:
    worker_type = {
        'point': WorkerType.FACILITY_PLACEMENT,
        'line': WorkerType.ROAD_CONSTRUCTION,
        'action': WorkerType.NON_SPATIAL_ACTION,
    }.get(output_kind, WorkerType.PROJECT_FOOTPRINT)
    return WorkerTask(
        task_id=f'{worker_type.value}:{target_id}',
        worker_type=worker_type,
        target_id=target_id,
        target_type=target_type,
        expected_output_kind=output_kind,
        assignment=TargetAssignment(
            target_id=target_id,
            target_type=target_type,
            status='ready',
            expected_output_kind=output_kind,
        ),
    )


def _failed_validation_report() -> ValidationReport:
    check = ValidationCheck(
        check_id='traceability',
        check_name='traceability',
        passed=False,
        actual_value="failed=['facility-1']",
        expected_value='point output',
        responsible_stage='EXECUTE',
        affected_parcels=['BSM-facility-parcel'],
        affected_target_ids=['facility-1'],
    )
    issue = ValidationIssue(
        stage='EXECUTE',
        severity='error',
        code='traceability',
        message='facility-1 has no point output',
        check_id='traceability',
    )
    return ValidationReport(
        checks=[check],
        overall_passed=False,
        issues_by_stage={'EXECUTE': [issue]},
    )


def test_persisted_semantic_checksum_stops_identical_retry_loop(tmp_path):
    store = FilesystemArtifactStore(tmp_path)
    first_outcome = ExecutionOutcome(
        artifact_id='outcome-payload-1',
        created_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        task_results=[
            ExecutionResult(
                task_id='task-old',
                target_id='facility-1',
                status='failed',
                expected_output_kind='point',
            )
        ],
    )
    second_outcome = first_outcome.model_copy(update={
        'artifact_id': 'outcome-payload-2',
        'created_at': first_outcome.created_at + timedelta(minutes=1),
    })
    first_ref = store.store(
        ArtifactRef(
            artifact_id='persisted-outcome-1',
            module='execute',
            run_id='semantic-retry',
            artifact_type='ExecutionOutcome',
        ),
        first_outcome.model_dump(mode='json'),
    )
    second_ref = store.store(
        ArtifactRef(
            artifact_id='persisted-outcome-2',
            module='execute',
            run_id='semantic-retry',
            artifact_type='ExecutionOutcome',
        ),
        second_outcome.model_dump(mode='json'),
    )

    assert first_ref.checksum != second_ref.checksum
    assert first_ref.semantic_checksum == second_ref.semantic_checksum

    report = _failed_validation_report()
    first_gate = evaluate_validate_gate(
        report,
        input_artifact_refs={
            'execution_outcome': first_ref.model_dump(mode='json'),
        },
    )
    second_gate = evaluate_validate_gate(
        report.model_copy(update={
            'artifact_id': 'validation-report-2',
            'created_at': report.created_at + timedelta(minutes=1),
        }),
        input_artifact_refs={
            'execution_outcome': second_ref.model_dump(mode='json'),
        },
        previous_gate=first_gate,
    )

    assert first_gate.feedback_route == 'RETRY_EXECUTE'
    assert second_gate.feedback_route == 'HUMAN'
    assert second_gate.route_reason == 'identical_no_progress'


def test_validate_traceability_uses_target_output_kind_not_parcel_count():
    point_task = _task('facility-1', 'point', target_type='facility')
    action_task = _task('policy-1', 'action')
    plan = ExecutionPlan(worker_tasks=[point_task, action_task])
    outcome = ExecutionOutcome(
        task_results=[
            ExecutionResult(
                task_id=action_task.task_id,
                target_id='policy-1',
                status='succeeded',
                expected_output_kind='action',
                output_artifacts=['action'],
            ),
            ExecutionResult(
                task_id=point_task.task_id,
                target_id='facility-1',
                status='succeeded',
                expected_output_kind='point',
                output_artifacts=['point'],
            ),
        ]
    )

    checks = check_traceability(
        None,
        execution_plan=plan,
        execution_outcome=outcome,
    )

    assert len(checks) == 1
    assert checks[0].passed is True
    assert 'point' in checks[0].expected_value
    assert 'action' in checks[0].expected_value


def test_topology_gap_check_ignores_disjoint_project_footprints():
    planned_state = PlannedState(
        parcels=[
            PlannedParcel(bsm='project-a', geometry='POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))'),
            PlannedParcel(bsm='project-b', geometry='POLYGON ((10 0, 11 0, 11 1, 10 1, 10 0))'),
        ]
    )

    checks = check_topology(planned_state)

    gap_check = next(check for check in checks if check.check_id == 'topology_gaps')
    assert gap_check.passed is True
    assert gap_check.actual_value == 'not_applicable:no_partition_domain'


def test_disjoint_zones_do_not_imply_a_partition_domain():
    planned_state = PlannedState(
        zones=[
            PlannedZone(name='zone-a', geometry='POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))'),
            PlannedZone(name='zone-b', geometry='POLYGON ((10 0, 11 0, 11 1, 10 1, 10 0))'),
        ]
    )

    gap_check = next(
        check for check in check_topology(planned_state)
        if check.check_id == 'topology_gaps'
    )

    assert gap_check.passed is True
    assert gap_check.actual_value == 'not_applicable:no_partition_domain'


def test_explicit_partition_domain_checks_declared_boundary_for_gaps():
    from app.modules.schema.contracts.planned_state_contracts import CoverageDomain

    planned_state = PlannedState(
        zones=[
            PlannedZone(name='zone-a', geometry='POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))'),
            PlannedZone(name='zone-b', geometry='POLYGON ((2 0, 3 0, 3 1, 2 1, 2 0))'),
        ],
        coverage_domains=[
            CoverageDomain(
                domain_id='land-use-partition',
                domain_type='partition',
                boundary_geometry='POLYGON ((0 0, 3 0, 3 1, 0 1, 0 0))',
                zone_refs=['zone-a', 'zone-b'],
            )
        ],
    )

    gap_check = next(
        check for check in check_topology(planned_state)
        if check.check_id == 'topology_gaps'
    )

    assert gap_check.passed is False
    assert 'land-use-partition' in gap_check.actual_value


def test_reconciliation_joins_reordered_results_by_target_and_output_kind():
    covered_task = _task('facility-1', 'point', target_type='facility')
    failed_task = _task('road-1', 'line', target_type='road')
    deferred_task = _task('policy-1', 'action')
    plan = ExecutionPlan(
        worker_tasks=[covered_task, failed_task],
        deferred_tasks=[deferred_task],
    )
    outcome = ExecutionOutcome(
        task_results=[
            ExecutionResult(
                task_id=failed_task.task_id,
                target_id='road-1',
                status='failed',
                expected_output_kind='line',
            ),
            ExecutionResult(
                task_id=deferred_task.task_id,
                target_id='policy-1',
                status='deferred',
                expected_output_kind='action',
            ),
            ExecutionResult(
                task_id=covered_task.task_id,
                target_id='facility-1',
                status='succeeded',
                expected_output_kind='point',
                output_artifacts=['point'],
            ),
        ]
    )

    matrix = build_coverage_matrix(
        execution_plan=plan,
        execution_outcome=outcome,
    )

    rows = {row.target_id: row for row in matrix.rows}
    assert {target_id: row.status for target_id, row in rows.items()} == {
        'facility-1': 'covered',
        'road-1': 'failed',
        'policy-1': 'deferred',
    }
    assert rows['facility-1'].expected_output_kind == 'point'
    assert rows['road-1'].expected_output_kind == 'line'


def test_reconciliation_accepts_regenerated_task_id_for_same_stable_key():
    task = _task('facility-1', 'point', target_type='facility')
    plan = ExecutionPlan(worker_tasks=[task])
    outcome = ExecutionOutcome(task_results=[
        ExecutionResult(
            task_id='regenerated-task-id',
            target_id='facility-1',
            status='succeeded',
            expected_output_kind='point',
            output_artifacts=['point'],
        )
    ])

    matrix = build_coverage_matrix(
        execution_plan=plan,
        execution_outcome=outcome,
    )

    assert matrix.rows[0].status == 'covered'
    assert matrix.rows[0].execution_task_id == task.task_id
    assert check_target_execution_coverage(plan, outcome) == []


def test_reconciliation_reports_contradictory_duplicate_results():
    task = _task('facility-1', 'point', target_type='facility')
    plan = ExecutionPlan(worker_tasks=[task])
    outcome = ExecutionOutcome(task_results=[
        ExecutionResult(
            task_id='attempt-1',
            target_id='facility-1',
            status='succeeded',
            expected_output_kind='point',
            output_artifacts=['point'],
        ),
        ExecutionResult(
            task_id='attempt-2',
            target_id='facility-1',
            status='failed',
            expected_output_kind='point',
        ),
    ])

    matrix = build_coverage_matrix(
        execution_plan=plan,
        execution_outcome=outcome,
    )
    inconsistencies = check_target_execution_coverage(plan, outcome)

    assert matrix.rows[0].status == 'failed'
    assert any(item.field == 'duplicate_execution_outcome' for item in inconsistencies)


def test_deferred_target_reports_contradictory_actual_outcome():
    task = _task('facility-1', 'point', target_type='facility')
    plan = ExecutionPlan(deferred_tasks=[task])
    outcome = ExecutionOutcome(task_results=[
        ExecutionResult(
            task_id='late-result',
            target_id='facility-1',
            status='succeeded',
            expected_output_kind='point',
            output_artifacts=['point'],
        )
    ])

    traceability = check_traceability(
        None,
        execution_plan=plan,
        execution_outcome=outcome,
    )[0]
    matrix = build_coverage_matrix(
        execution_plan=plan,
        execution_outcome=outcome,
    )
    inconsistencies = check_target_execution_coverage(plan, outcome)

    assert traceability.passed is False
    assert traceability.affected_target_ids == ['facility-1']
    assert matrix.rows[0].status == 'failed'
    assert any(item.field == 'deferred_outcome_contradiction' for item in inconsistencies)


def test_identical_validate_fingerprints_escalate_without_execute_loop():
    report = _failed_validation_report()
    refs = {
        'execution_plan': {'artifact_id': 'plan-a', 'checksum': 'plan-sum'},
        'execution_outcome': {'artifact_id': 'outcome-a', 'checksum': 'outcome-sum'},
    }

    first = evaluate_validate_gate(report, input_artifact_refs=refs)
    repeated = evaluate_validate_gate(
        report,
        input_artifact_refs=refs,
        previous_gate=first,
    )

    assert first.feedback_route == 'RETRY_EXECUTE'
    assert first.input_checksum
    assert first.output_checksum
    assert first.issue_fingerprint
    assert repeated.feedback_route == 'HUMAN'
    assert repeated.progress_made is False
    assert repeated.route_reason == 'identical_no_progress'
    assert route_after_validate({'validate_gate': repeated.model_dump(mode='json')}) == 'human_review'


def test_human_retry_cannot_restart_identical_structural_gate():
    state = {
        'paused_stage': 'validate',
        'human_review_decisions': {'action': 'retry'},
        'validate_gate': {
            'passed': False,
            'feedback_route': 'HUMAN',
            'progress_made': False,
            'inputs_changed': False,
        },
    }

    assert route_after_human_review(state) == END_DIAGNOSTIC


def test_retry_limit_routes_to_diagnostic_state():
    state = {
        'max_retries': 1,
        'retry_counts': {'validate': 1},
        'validate_gate': {
            'stage': 'validate',
            'passed': False,
            'feedback_route': 'RETRY_EXECUTE',
            'issue_fingerprint': 'blocked',
        },
    }

    assert route_after_validate(state) == END_DIAGNOSTIC
    assert state['delivery_status'] == 'diagnostic_only'
    assert state['validate_gate']['feedback_route'] == 'END_DIAGNOSTIC'


def test_identical_reconcile_fingerprints_escalate_without_execute_loop():
    report = ReconciliationReport(
        coverage_matrix=CoverageMatrix(rows=[
            CoverageMatrixRow(
                target_id='road-1',
                target_type='road',
                expected_output_kind='line',
                status='failed',
            )
        ]),
        inconsistencies=[
            ReconciliationInconsistency(
                intervention_id='road-1',
                field='execution_status',
                expected='covered:line',
                actual='failed:line',
                severity='error',
                responsible_stage='EXECUTE',
            )
        ]
    )
    refs = {
        'execution_plan': {'artifact_id': 'plan-a', 'checksum': 'plan-sum'},
        'execution_outcome': {'artifact_id': 'outcome-a', 'checksum': 'outcome-sum'},
    }

    first = evaluate_reconcile_gate(report, input_artifact_refs=refs)
    repeated = evaluate_reconcile_gate(
        report,
        input_artifact_refs=refs,
        previous_gate=first,
    )

    assert first.feedback_route == 'RETRY_EXECUTE'
    assert repeated.feedback_route == 'HUMAN'
    assert repeated.progress_made is False
    assert repeated.pending_requests[0].context['target_ids'] == ['road-1']


@pytest.mark.asyncio
async def test_human_accept_cannot_pass_structural_validate_failure():
    state = {
        'human_review_items': [{'request_id': 'validate-1'}],
        'paused_stage': 'validate',
        'validate_gate': {
            'stage': 'validate',
            'passed': False,
            'feedback_route': 'HUMAN',
            'issue_fingerprint': 'same-issue',
        },
        'human_review_decisions': {'action': 'accept'},
    }

    patch = await apply_human_review_decision(state)
    routed = route_after_human_review({**state, **patch})

    assert patch['validate_gate']['passed'] is False
    assert patch['validate_gate']['feedback_route'] == 'END_DIAGNOSTIC'
    assert patch['delivery_status'] == 'diagnostic_only'
    assert routed == END_DIAGNOSTIC


@pytest.mark.asyncio
async def test_human_target_deferral_creates_new_plan_revision(monkeypatch):
    task = _task('facility-1', 'point', target_type='facility')
    plan = ExecutionPlan(plan_id='plan-v1', worker_tasks=[task])
    outcome = ExecutionOutcome(
        task_results=[
            ExecutionResult(
                task_id=task.task_id,
                target_id=task.target_id,
                status='failed',
                expected_output_kind='point',
            )
        ]
    )
    stored = {}

    def load_artifact(state, key, model):
        return {
            'execution_plan': plan,
            'execution_outcome': outcome,
            'deferral_ledger': None,
            'site_selection': None,
        }.get(key)

    def store_artifact(state, key, module, artifact_type, payload):
        stored[key] = payload
        return {
            'artifact_id': f'{key}-revision',
            'artifact_type': artifact_type,
            'checksum': f'{key}-checksum',
        }

    monkeypatch.setattr(
        'app.agent.bootstrap.artifact_runtime.load_artifact',
        load_artifact,
    )
    monkeypatch.setattr(
        'app.agent.bootstrap.artifact_runtime.store_artifact',
        store_artifact,
    )
    state = {
        'human_review_items': [{'request_id': 'validate-1'}],
        'human_review_event_id': 'review-1',
        'paused_stage': 'validate',
        'validate_gate': {
            'stage': 'validate',
            'passed': False,
            'feedback_route': 'HUMAN',
            'pending_requests': [
                {'context': {'target_ids': ['facility-1']}}
            ],
        },
        'artifact_refs': {
            'execution_plan': {'artifact_id': 'plan-v1'},
            'execution_outcome': {'artifact_id': 'outcome-v1'},
            'validation_report': {'artifact_id': 'validate-v1'},
        },
        'human_review_decisions': {
            'action': 'accept',
            'deferred_target_ids': ['facility-1'],
            'decided_by': 'planner@example.test',
            'feedback': 'Defer the failed facility target.',
        },
    }

    patch = await apply_human_review_decision(state)

    revised_plan = stored['execution_plan']
    assert revised_plan.plan_id != plan.plan_id
    assert revised_plan.worker_tasks == []
    assert revised_plan.deferred_tasks[0].target_id == 'facility-1'
    assert stored['deferral_ledger'].entries[0].target_id == 'facility-1'
    assert patch['validate_gate']['passed'] is False
    assert route_after_human_review({**state, **patch}) == 'execute'


@pytest.mark.asyncio
async def test_non_target_structural_check_cannot_defer_parcel_bsm(monkeypatch):
    task = _task('facility-target-1', 'point', target_type='facility')
    plan = ExecutionPlan(worker_tasks=[task])
    outcome = ExecutionOutcome(task_results=[
        ExecutionResult(
            task_id=task.task_id,
            target_id=task.target_id,
            status='failed',
            expected_output_kind='point',
        )
    ])
    report = ValidationReport(
        checks=[
            ValidationCheck(
                check_id='topology_validity',
                passed=False,
                responsible_stage='EXECUTE',
                affected_parcels=['BSM-physical-1'],
                affected_target_ids=[],
            )
        ],
        overall_passed=False,
        issues_by_stage={
            'EXECUTE': [
                ValidationIssue(
                    stage='EXECUTE',
                    severity='error',
                    code='topology_validity',
                    message='invalid parcel geometry',
                    check_id='topology_validity',
                )
            ]
        },
    )
    gate = evaluate_validate_gate(report).model_dump(mode='json')
    assert gate['pending_requests'][0]['context']['target_ids'] == []

    monkeypatch.setattr(
        'app.agent.bootstrap.artifact_runtime.load_artifact',
        lambda state, key, model: {
            'execution_plan': plan,
            'execution_outcome': outcome,
            'deferral_ledger': None,
            'site_selection': None,
        }.get(key),
    )
    state = {
        'human_review_items': [{'request_id': 'validate-topology'}],
        'paused_stage': 'validate',
        'validate_gate': gate,
        'human_review_decisions': {
            'action': 'accept',
            'deferred_target_ids': ['facility-target-1'],
        },
    }

    patch = await apply_human_review_decision(state)

    assert patch['fatal_error']['code'] == 'HUMAN_DEFER_TARGET_NOT_BLOCKING'
