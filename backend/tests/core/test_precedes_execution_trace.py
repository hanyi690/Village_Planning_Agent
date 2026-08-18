from __future__ import annotations

from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import PrecedesParameters
from app.domain.relations.service import RelationEvaluationContext, evaluate_relations
from app.domain.relations.temporal_evaluator import ExecutionEvent, ExecutionTrace


def _factor() -> ConstraintFactor:
    return ConstraintFactor(
        factor_id="factor:precedes-1",
        kind="precedes",
        evaluator_key="precedes",
        subject_ref="road-1",
        object_ref="facility-1",
        hard=True,
        parameters=PrecedesParameters(required_event="complete"),
    )


def test_precedes_without_execution_trace_is_pending() -> None:
    result = evaluate_relations(
        [_factor()],
        [],
        RelationEvaluationContext(scenario_id="scenario-1"),
    )[0]

    assert result.status == "pending"
    assert result.measurement is None


def test_precedes_uses_observed_execution_events_only() -> None:
    trace = ExecutionTrace(
        events=[
            ExecutionEvent(task_id="road-1", event="complete", timestamp=10),
            ExecutionEvent(task_id="facility-1", event="start", timestamp=11),
        ]
    )
    result = evaluate_relations(
        [_factor()],
        [],
        RelationEvaluationContext(scenario_id="scenario-1", execution_trace=trace),
    )[0]

    assert result.status == "satisfied"
    assert result.measurement is not None
    assert result.measurement.value == 1


def test_precedes_is_violated_when_observed_order_is_reversed() -> None:
    trace = ExecutionTrace(
        events=[
            ExecutionEvent(task_id="road-1", event="complete", timestamp=20),
            ExecutionEvent(task_id="facility-1", event="start", timestamp=11),
        ]
    )
    result = evaluate_relations(
        [_factor()],
        [],
        RelationEvaluationContext(scenario_id="scenario-1", execution_trace=trace),
    )[0]

    assert result.status == "violated"
