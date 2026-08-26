from __future__ import annotations

import pytest

from app.contracts.domain.l2_contracts import (
    ConflictHypothesis,
    L2DecisionSet,
    PlanningObjective,
    SpatialStructureIntent,
    StrategyRule,
    TargetMetric,
)
from app.domain.validation.l2_closure import (
    validate_l2_decision_set,
    validate_l2_strategy_graph,
)


def _valid_decision_set() -> L2DecisionSet:
    return L2DecisionSet(
        dimension_key="planning_strategies",
        objectives=[
            PlanningObjective(
                objective_id="obj-1",
                statement="提升公共服务可达性",
                kind="goal",
                status="observed",
                source_fact_refs=["l1:fact:fact-1"],
            )
        ],
        metrics=[
            TargetMetric(
                metric_id="metric-1",
                name="公共服务覆盖率",
                value=95,
                unit="%",
                direction="increase",
                status="observed",
                source_fact_refs=["l1:fact:fact-1"],
            )
        ],
        strategies=[
            StrategyRule(
                strategy_id="strategy-1",
                statement="优先补齐公共服务短板",
                action="guide",
                strength="proposed",
                objective_refs=["obj-1"],
                source_fact_refs=["l1:fact:fact-1"],
            )
        ],
        spatial_structures=[
            SpatialStructureIntent(
                structure_id="structure-1",
                statement="形成服务网络",
                relation_kind="serve",
                objective_refs=["obj-1"],
                source_fact_refs=["l1:fact:fact-1"],
                grounding_requirements=["candidate_geometry", "network_snapshot"],
            )
        ],
    )


def test_validate_l2_decision_set_accepts_closed_graph() -> None:
    decision = _valid_decision_set()

    result = validate_l2_decision_set(
        decision,
        known_l1_fact_ids={"l1:fact:fact-1"},
    )

    assert result.dimension_key == "planning_strategies"


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda decision: decision.model_copy(
                update={
                    "objectives": [
                        *decision.objectives,
                        decision.objectives[0].model_copy(update={"statement": "重复 ID"}),
                    ]
                }
            ),
            "duplicate_id:obj-1",
        ),
        (
            lambda decision: decision.model_copy(
                update={
                    "strategies": [
                        decision.strategies[0].model_copy(
                            update={"source_fact_refs": ["bundle://feature/not-a-fact"]}
                        )
                    ]
                }
            ),
            "strategy_source_fact_refs:strategy-1:wrong_namespace:bundle://feature/not-a-fact",
        ),
        (
            lambda decision: decision.model_copy(
                update={
                    "strategies": [
                        decision.strategies[0].model_copy(update={"source_fact_refs": ["l1:fact:missing"]})
                    ]
                }
            ),
            "strategy_source_fact_refs:strategy-1:dangling:l1:fact:missing",
        ),
        (
            lambda decision: decision.model_copy(
                update={
                    "strategies": [
                        decision.strategies[0].model_copy(update={"objective_refs": ["obj-missing"]})
                    ]
                }
            ),
            "strategy_objective_ref_missing:strategy-1:obj-missing",
        ),
        (
            lambda decision: decision.model_copy(
                update={
                    "strategies": [
                        decision.strategies[0].model_copy(update={"prerequisite_refs": ["strategy-2"]}),
                        StrategyRule(
                            strategy_id="strategy-2",
                            statement="第二条策略",
                            action="guide",
                            strength="proposed",
                            objective_refs=["obj-1"],
                            prerequisite_refs=["strategy-1"],
                            source_fact_refs=["l1:fact:fact-1"],
                        ),
                    ]
                }
            ),
            "prerequisite_cycle:strategy-1->strategy-2->strategy-1",
        ),
        (
            lambda decision: decision.model_copy(
                update={
                    "metrics": [
                        decision.metrics[0].model_copy(update={"value": 95, "unit": ""})
                    ]
                }
            ),
            "metric_quantity_unit_missing:metric-1",
        ),
        (
            lambda decision: decision.model_copy(
                update={
                    "metrics": [
                        decision.metrics[0].model_copy(update={"value": "95亩", "unit": "公顷"})
                    ]
                }
            ),
            "metric_unit_mismatch:metric-1:亩!=公顷",
        ),
        (
            lambda decision: decision.model_copy(
                update={
                    "objectives": [
                        decision.objectives[0].model_copy(update={"source_fact_refs": []})
                    ]
                }
            ),
            "observed_objective_evidence_missing:obj-1",
        ),
        (
            lambda decision: decision.model_copy(
                update={
                    "spatial_structures": [
                        decision.spatial_structures[0].model_copy(update={"relation_kind": "文化廊道"})
                    ]
                }
            ),
            "spatial_relation_not_closed:structure-1:文化廊道",
        ),
        (
            lambda decision: decision.model_copy(
                update={
                    "spatial_structures": [
                        decision.spatial_structures[0].model_copy(
                            update={"grounding_requirements": ["candidate_geometry", "古树坐标"]}
                        )
                    ]
                }
            ),
            "grounding_requirement_not_closed:structure-1:古树坐标",
        ),
        (
            lambda decision: decision.model_copy(
                update={
                    "conflicts": [
                        ConflictHypothesis(
                                conflict_id="conf-1",
                                description="孤立冲突",
                                severity="warning",
                                objective_refs=["obj-1"],
                            strategy_refs=[],
                        )
                    ]
                }
            ),
            "conflict_endpoints_incomplete:conf-1",
        ),
    ],
)
def test_validate_l2_decision_set_fails_closed(mutator, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        validate_l2_decision_set(
            mutator(_valid_decision_set()),
            known_l1_fact_ids={"l1:fact:fact-1"},
        )


def test_validate_l2_strategy_graph_rejects_cross_set_duplicate_ids() -> None:
    first = _valid_decision_set().model_copy(update={"dimension_key": "planning_a"})
    second = _valid_decision_set().model_copy(update={"dimension_key": "planning_b"})

    with pytest.raises(ValueError, match="duplicate_id:obj-1"):
        validate_l2_strategy_graph(
            [first, second],
            known_l1_fact_ids={"l1:fact:fact-1"},
        )
