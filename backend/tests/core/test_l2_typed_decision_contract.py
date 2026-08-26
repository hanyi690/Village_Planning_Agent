from app.contracts.domain.l2_contracts import (
    L2DecisionSet,
    PlanningObjective,
    PriorityDecision,
    SpatialStructureIntent,
    StrategyRule,
)
from app.domain.objectives.aggregate import merge_decision_sets


def test_l2_decision_set_is_the_authoritative_semantic_input() -> None:
    decision = L2DecisionSet(
        dimension_key="planning_strategies",
        objectives=[
            PlanningObjective(
                objective_id="obj-1",
                statement="提升公共服务可达性",
                kind="goal",
                status="proposed",
            )
        ],
        strategies=[
            StrategyRule(
                strategy_id="strategy-1",
                statement="优先补齐公共服务短板",
                strength="proposed",
                objective_refs=["obj-1"],
            )
        ],
        priorities=[
            PriorityDecision(
                priority_id="priority-1",
                rank=1,
                strategy_refs=["strategy-1"],
                statement="先补齐公共服务短板",
            )
        ],
        spatial_structures=[
            SpatialStructureIntent(
                structure_id="structure-1",
                statement="形成村庄公共服务节点体系",
                grounding_requirements=["demand_points", "candidate_geometry"],
            )
        ],
    )

    strategy = merge_decision_sets([decision], run_id="run-1")

    assert strategy.schema_version == "2.0"
    assert strategy.decision_sets[0].dimension_key == "planning_strategies"
    assert strategy.development_goals == ["提升公共服务可达性"]
    assert strategy.implementation_priorities == [
        "先补齐公共服务短板",
        "优先补齐公共服务短板",
    ]
    assert strategy.spatial_structure == "形成村庄公共服务节点体系"
    assert strategy.strategy_conflicts == []


def test_l2_merge_does_not_infer_conflicts_from_prose() -> None:
    decision = L2DecisionSet(
        dimension_key="planning_strategies",
        objectives=[
            PlanningObjective(
                objective_id="obj-1",
                statement="兼顾产业发展与生态保护",
                kind="goal",
                status="proposed",
            )
        ],
        strategies=[
            StrategyRule(
                strategy_id="strategy-1",
                statement="产业与生态协同推进",
                strength="proposed",
                objective_refs=["obj-1"],
            )
        ],
    )

    strategy = merge_decision_sets([decision], run_id="run-2")

    # Conflict entries are model-declared typed objects.  Shared words in a
    # statement must not create a deterministic lexical conflict.
    assert strategy.strategy_conflicts == []
