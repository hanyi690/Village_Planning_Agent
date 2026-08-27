from __future__ import annotations

import asyncio

from app.contracts.domain.l2_contracts import (
    L2DecisionSet,
    PlanningObjective,
    PriorityDecision,
    StrategyRule,
    TargetMetric,
)
from app.domain.objectives.worker import (
    _validate_l2_decision_with_one_closed_set_reask,
)
from app.domain.validation.l1_fact_catalog import build_l1_fact_catalog
from app.domain.validation.l2_boundary import normalize_l2_decision_boundary
from app.domain.validation.l2_closure import validate_l2_decision_set


def _provider_decision_with_repairable_boundary_errors() -> L2DecisionSet:
    return L2DecisionSet(
        dimension_key="planning_strategies",
        objectives=[
            PlanningObjective(
                objective_id="objective-1",
                statement="提升公共服务可达性",
                kind="goal",
                status="observed",
                source_fact_refs=["l1:fact:invented"],
            )
        ],
        metrics=[
            TargetMetric(
                metric_id="metric-1",
                name="覆盖率",
                value=95,
                unit="",
                direction="increase",
                status="proposed",
                source_fact_refs=["l1:fact:invented"],
            )
        ],
        strategies=[
            StrategyRule(
                strategy_id="strategy-1",
                statement="优先补齐服务短板",
                strength="proposed",
                source_fact_refs=["l1:fact:invented"],
            )
        ],
        priorities=[
            PriorityDecision(
                priority_id="priority-1",
                rank=1,
                strategy_refs=["strategy-missing"],
                statement="先补齐服务短板",
            )
        ],
    )


def test_l2_boundary_only_keeps_provable_objects() -> None:
    catalog = build_l1_fact_catalog([{"fact_id": "l1:fact:known"}])

    result = normalize_l2_decision_boundary(
        _provider_decision_with_repairable_boundary_errors(),
        catalog=catalog,
    )

    assert result.changed is True
    assert result.decision.objectives[0].source_fact_refs == []
    assert result.decision.objectives[0].status == "proposed"
    assert result.decision.metrics == []
    assert result.decision.strategies == []
    assert result.decision.priorities == []
    assert any("source_fact_refs_dropped" in item for item in result.decision.diagnostics)
    assert any("metric_quarantined" in item for item in result.decision.diagnostics)
    assert any("strategy_quarantined" in item for item in result.decision.diagnostics)
    assert any("priority_quarantined" in item for item in result.decision.diagnostics)

    validate_l2_decision_set(
        result.decision,
        known_l1_fact_ids={"l1:fact:known"},
    )


def test_l2_boundary_is_idempotent() -> None:
    catalog = build_l1_fact_catalog([{"fact_id": "l1:fact:known"}])
    first = normalize_l2_decision_boundary(
        _provider_decision_with_repairable_boundary_errors(),
        catalog=catalog,
    )
    second = normalize_l2_decision_boundary(first.decision, catalog=catalog)

    assert second.changed is False
    assert second.decision.model_dump(mode="json") == first.decision.model_dump(mode="json")


def test_l2_worker_uses_boundary_after_one_failed_reask() -> None:
    invalid = _provider_decision_with_repairable_boundary_errors()
    catalog = build_l1_fact_catalog([{"fact_id": "l1:fact:known"}])
    feedback: list[str] = []

    async def run_decision(message: str) -> L2DecisionSet:
        feedback.append(message)
        return invalid

    result, error = asyncio.run(
        _validate_l2_decision_with_one_closed_set_reask(
            invalid,
            catalog=catalog,
            catalog_digest=catalog.digest,
            run_decision=run_decision,
        )
    )

    assert feedback
    assert error == ""
    assert result.metrics == []
    assert result.strategies == []
    validate_l2_decision_set(
        result,
        known_l1_fact_ids={"l1:fact:known"},
    )
