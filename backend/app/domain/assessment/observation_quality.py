"""Type-aware quality validation for the L1 planning fact union."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from app.domain.assessment.dimension_contracts import get_dimension_semantic_contract
from app.domain.assessment.observation_draft import (
    L1ConstraintFact,
    L1DemandFact,
    L1DocumentObservationFact,
    L1PlanningFactDraft,
    L1RiskOpportunityFact,
    L1ScopedMetricFact,
    L1SpatialEntityFact,
    L1SpatialRelationFact,
)


_FACT_ADAPTER = TypeAdapter(L1PlanningFactDraft)


def _has_structured_spatial_signal(fact: Any) -> bool:
    """Return whether a fact carries an explicit spatial work-item signal."""

    locator = getattr(fact, "locator", None)
    if locator is not None and (
        getattr(locator, "place_names", None)
        or getattr(locator, "relation", "")
        or getattr(locator, "source_feature_ids", None)
    ):
        return True
    for mention in getattr(fact, "spatial_mentions", None) or []:
        if (
            getattr(mention, "scope_mentions", None)
            or getattr(mention, "relation", "")
            or getattr(mention, "source_feature_ids", None)
            or str(getattr(mention, "target_name", "") or "").strip()
        ):
            return True
        if str(getattr(mention, "resolution_state", "") or "").strip() in {
            "needs_retrieval",
            "conflict",
            "source_exhausted",
        }:
            return True
    return False


def validate_observations(
    observations: list,
    *,
    dimension_key: str = "",
    max_defect_ratio: float = 0.5,
) -> dict:
    """Validate typed completeness without requiring every fact to be spatial.

    ``dimension_key`` makes the L1 fact vocabulary executable: the union
    chooses the shape at generation time, while the dimension contract decides
    whether that shape belongs in this pass.
    """

    contract = get_dimension_semantic_contract(dimension_key, 1)
    allowed_fact_types = {
        str(value).strip()
        for value in contract.get("l1_fact_types", [])
        if str(value).strip()
    }

    total = len(observations or [])
    if total == 0:
        return {
            "ok": True,
            "total": 0,
            "missing_name": 0,
            "no_place": 0,
            "invalid_semantics": 0,
            "invalid_relation": 0,
            "invalid_fact_type": 0,
            "dimension_mismatch": 0,
            "defect_ratio": 0.0,
            "feedback": "",
        }

    missing_name = 0
    no_place = 0
    invalid_semantics = 0
    invalid_relation = 0
    invalid_fact_type = 0
    dimension_mismatch = 0
    defect_rows = 0
    for raw in observations:
        row_defective = False
        try:
            fact = (
                raw
                if hasattr(raw, "fact_type")
                else _FACT_ADAPTER.validate_python(raw)
            )
        except Exception:
            invalid_fact_type += 1
            invalid_semantics += 1
            defect_rows += 1
            continue

        fact_type = fact.fact_type
        if allowed_fact_types and fact_type not in allowed_fact_types:
            dimension_mismatch += 1
        has_semantics = bool(
            str(getattr(fact, "semantic_type", "") or "").strip()
            or str(getattr(fact, "description", "") or "").strip()
            or getattr(fact, "value", None) is not None
        )
        if isinstance(fact, L1SpatialEntityFact):
            missing_name += not bool(fact.name.strip())
            no_place += not _has_structured_spatial_signal(fact)
            has_semantics = has_semantics or bool(
                fact.name.strip() or fact.entity_type.strip()
            )
        elif isinstance(fact, L1SpatialRelationFact):
            relation_ok = bool(
                fact.subject_ref.strip()
                and fact.predicate.strip()
                and fact.object_ref.strip()
            )
            invalid_relation += not relation_ok
            row_defective = row_defective or (not relation_ok)
            has_semantics = has_semantics or bool(
                fact.subject_ref.strip() or fact.object_ref.strip()
            )
        elif isinstance(fact, L1ScopedMetricFact):
            missing_name += not bool(fact.metric.strip())
            no_place += 1
            has_semantics = has_semantics or bool(fact.metric.strip())
        elif isinstance(fact, L1DemandFact):
            missing_name += not bool(fact.demand_type.strip())
            no_place += not _has_structured_spatial_signal(fact)
            has_semantics = has_semantics or bool(fact.demand_type.strip())
        elif isinstance(fact, L1ConstraintFact):
            missing_name += not bool(fact.constraint_type.strip())
            no_place += not _has_structured_spatial_signal(fact)
            has_semantics = has_semantics or bool(fact.constraint_type.strip())
        elif isinstance(fact, L1RiskOpportunityFact):
            missing_name += not bool(fact.subject.strip())
            no_place += not _has_structured_spatial_signal(fact)
            has_semantics = has_semantics or bool(fact.subject.strip())
        elif isinstance(fact, L1DocumentObservationFact):
            missing_name += not bool(fact.subject.strip())
            no_place += 1
            has_semantics = has_semantics or bool(fact.subject.strip())

        if not has_semantics:
            invalid_semantics += 1
            row_defective = True

        if row_defective:
            defect_rows += 1

    defects = min(total, defect_rows)
    ratio = round(defects / total, 3)
    feedback = ""
    if ratio >= max_defect_ratio:
        feedback = (
            f"L1 事实质量不达标：共 {total} 条，"
            f"{invalid_fact_type} 条 fact_type 无效，"
            f"{invalid_semantics} 条事实缺少类型所需语义，"
            f"{invalid_relation} 条空间关系缺少 subject/predicate/object，"
            f"缺陷占比 {ratio:.0%}。请按 fact_type 重写；"
            "非空间指标或全村诉求不得编造点位，且不得使用本维度未声明的 fact_type。"
        )
    return {
        "ok": ratio < max_defect_ratio,
        "total": total,
        "missing_name": int(missing_name),
        "no_place": int(no_place),
        "invalid_semantics": invalid_semantics,
        "invalid_relation": invalid_relation,
        "invalid_fact_type": invalid_fact_type,
        "dimension_mismatch": dimension_mismatch,
        "defect_ratio": ratio,
        "feedback": feedback,
    }


__all__ = ["validate_observations"]
