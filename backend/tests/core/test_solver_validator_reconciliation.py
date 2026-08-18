from app.contracts.planning.constraint_factor import RelationMeasurement, RelationSatisfaction
from app.contracts.planning.scenario import PlanningScenario
from app.domain.validation.relation_validation import FinalScenarioValidation
from app.domain.validation.scenario_reconciliation import reconcile_scenario_relations


def _row(status: str, value: float, version: str = "relation-evaluator-v1") -> RelationSatisfaction:
    return RelationSatisfaction(
        relation_id="r1",
        scenario_id="s1",
        subject_ref="a",
        object_ref="b",
        status=status,
        criticality="hard",
        subject_feature_refs=["feature:a"],
        object_feature_refs=["feature:b"],
        measurement=RelationMeasurement(value=value, threshold=10, operator="lte", method="distance", unit="m"),
        evaluation_trace=["distance:feature:a:feature:b"],
        evaluator_version=version,
    )


def test_reconciliation_records_final_status_and_measurement_drift() -> None:
    scenario = PlanningScenario(
        scenario_id="s1", baseline_ref="b", problem_fingerprint="p",
        relation_satisfactions=[_row("satisfied", 5)],
    )
    final = FinalScenarioValidation(
        scenario_id="s1", final_fingerprint="f", evaluator_version="relation-evaluator-v1",
        passed=False, satisfactions=[_row("violated", 15)],
    )
    report = reconcile_scenario_relations(scenario, final)
    assert not report.passed
    assert "r1" in report.changed_relation_ids
    assert any(item.code == "relation_status_changed" for item in report.findings)


def test_reconciliation_rejects_evaluator_version_drift() -> None:
    scenario = PlanningScenario(
        scenario_id="s1", baseline_ref="b", problem_fingerprint="p",
        relation_satisfactions=[_row("satisfied", 5, "solver-v1")],
    )
    final = FinalScenarioValidation(
        scenario_id="s1", final_fingerprint="f", evaluator_version="relation-evaluator-v2",
        passed=True, satisfactions=[_row("satisfied", 5, "relation-evaluator-v2")],
    )
    report = reconcile_scenario_relations(scenario, final)
    assert any(item.code == "evaluator_version_changed" for item in report.findings)
