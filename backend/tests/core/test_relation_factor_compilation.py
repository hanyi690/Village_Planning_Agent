from __future__ import annotations

from app.contracts.planning.intent_graph import PlanRelationIntent, PlanningIntentGraph
from app.contracts.planning.relation_parameters import DistanceParameters, PrecedesParameters
from app.domain.ground.constraint_factors import compile_constraint_factors


def test_factor_compiler_preserves_typed_parameters_and_evaluator_keys() -> None:
    graph = PlanningIntentGraph(
        relations=[
            PlanRelationIntent(
                relation_id="near-1",
                relation_template="near",
                subject_ref="facility-1",
                object_ref="village-1",
                criticality="hard",
                parameters=DistanceParameters(max_distance_m=500, metric="euclidean"),
            ),
            PlanRelationIntent(
                relation_id="precedes-1",
                relation_template="precedes",
                subject_ref="road-1",
                object_ref="facility-1",
                criticality="hard",
                parameters=PrecedesParameters(required_event="complete"),
            ),
        ]
    )

    factors = compile_constraint_factors(graph)

    assert factors[0].evaluator_key == "near"
    assert isinstance(factors[0].parameters, DistanceParameters)
    assert factors[1].evaluator_key == "precedes"
    assert factors[1].status == "pending"
    assert isinstance(factors[1].parameters, PrecedesParameters)


def test_missing_parameters_are_deferred_not_satisfied() -> None:
    graph = {
        "relations": [
            {
                "relation_id": "serve-1",
                "relation_template": "serve",
                "subject_ref": "facility-1",
                "object_ref": "demand-1",
                "criticality": "hard",
            }
        ]
    }

    factor = compile_constraint_factors(graph)[0]

    assert factor.status == "deferred"
    assert factor.status != "satisfied"

