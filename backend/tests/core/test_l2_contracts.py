from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from app.contracts.domain import l2_contracts
from app.contracts.domain.l2_contracts import (
    L2DecisionSet,
    PlanningObjective,
    SpatialStructureIntent,
    StrategyRule,
)


def _strict_models() -> list[type]:
    result: list[type] = []
    for _, value in inspect.getmembers(l2_contracts, inspect.isclass):
        if value.__module__ != l2_contracts.__name__:
            continue
        if hasattr(value, "model_config"):
            result.append(value)
    return result


@pytest.mark.parametrize("model_cls", _strict_models(), ids=lambda cls: cls.__name__)
def test_l2_models_forbid_extra(model_cls: type) -> None:
    assert model_cls.model_config.get("extra") == "forbid"


def test_l2_mutable_defaults_are_isolated() -> None:
    first = L2DecisionSet()
    second = L2DecisionSet()

    first.objectives.append(
        PlanningObjective(
            objective_id="obj-1",
            statement="提升公共服务可达性",
        )
    )
    first.diagnostics.append("diagnostic-1")

    assert second.objectives == []
    assert second.diagnostics == []


def test_l2_contract_rejects_extra_empty_id_and_confidence_range() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PlanningObjective.model_validate({
            "objective_id": "obj-1",
            "statement": "提升公共服务可达性",
            "unexpected": True,
        })

    with pytest.raises(ValidationError, match="id_must_be_nonempty"):
        PlanningObjective.model_validate({
            "objective_id": " ",
            "statement": "提升公共服务可达性",
        })

    with pytest.raises(ValidationError, match="confidence_out_of_range"):
        StrategyRule.model_validate({
            "strategy_id": "strategy-1",
            "statement": "优先补齐公共服务短板",
            "confidence": 1.1,
        })


def test_l2_contract_closes_namespace_relation_and_grounding() -> None:
    with pytest.raises(ValidationError, match="source_fact_refs_must_use_l1_fact_namespace"):
        PlanningObjective.model_validate({
            "objective_id": "obj-1",
            "statement": "保护文化资源",
            "source_fact_refs": ["bundle://feature/not-a-fact"],
        })

    with pytest.raises(ValidationError, match="relation_kind_not_in_closed_set"):
        SpatialStructureIntent.model_validate({
            "structure_id": "structure-1",
            "statement": "形成文化廊道",
            "relation_kind": "文化廊道",
            "source_fact_refs": ["l1:fact:fact-1"],
        })

    with pytest.raises(ValidationError, match="grounding_requirement_not_in_closed_set"):
        SpatialStructureIntent.model_validate({
            "structure_id": "structure-1",
            "statement": "形成文化廊道",
            "relation_kind": "serve",
            "source_fact_refs": ["l1:fact:fact-1"],
            "grounding_requirements": ["candidate_geometry", "古树坐标"],
        })
