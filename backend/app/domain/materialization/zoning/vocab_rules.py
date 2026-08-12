"""词汇表规则 DSL — TypingRule ↔ expr_eval.Condition 统一。

Migrated from agent/gis/vocab/rules.py per docs/architecture/agent-graph.md §5.

消除双实现：generator 的 _eval_rule 删除，统一走 expr_eval 求值。
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.contracts.domain.custom_zone_contracts import TypingRule
from app.modules.schema.encodings.dicts.expr_eval import Condition, MappingContext


def rule_to_condition(rule: TypingRule) -> Condition:
    """TypingRule → expr_eval.Condition（有界映射，谓词白名单）。"""
    kind = rule.kind
    value = rule.value
    if kind == "and":
        return Condition(kind="and", children=[rule_to_condition(c) for c in (rule.children or [])])
    if kind == "any":
        return Condition(kind="or", children=[rule_to_condition(c) for c in (rule.children or [])])
    if kind == "not":
        return Condition(kind="not", children=[rule_to_condition(c) for c in (rule.children or [])])
    if kind == "dlbm_in":
        return Condition(kind="comparison", field="dlbm", op="in", value=[str(v) for v in (value or [])])
    if kind == "field_equals":
        return Condition(kind="comparison", field=str(value.get("field", "")), op="==", value=value.get("value"))
    if kind == "within_zone":
        return Condition(kind="func", func="within_zone", args=[value])
    if kind == "not_within_zone":
        return Condition(
            kind="not",
            children=[Condition(kind="func", func="within_zone", args=[value])],
        )
    if kind == "slope_lt":
        return Condition(kind="comparison", field="slope_deg", op="lt", value=float(value))
    if kind == "road_distance_lt":
        return Condition(kind="comparison", field="road_distance_m", op="lt", value=float(value))
    if kind == "near_poi":
        return Condition(kind="func", func="poi_match", args=[value])
    return Condition(kind="null")


def parcel_to_context(parcel: Dict[str, Any]) -> MappingContext:
    """parcel dict → expr_eval.MappingContext（dlbm/area/slope/road/zone/poi）。"""
    return MappingContext(
        parcel_attrs={
            "dlbm": str(parcel.get("dlbm", "")),
            "area_ha": float(parcel.get("area_ha", 0) or 0),
            "slope_deg": float(parcel.get("slope_deg", 999) or 999),
            "road_distance_m": float(parcel.get("road_distance_m", 99999) or 99999),
        },
        zone_membership=list(parcel.get("zone_membership", []) or []),
        poi_hits=list(parcel.get("poi_hits", []) or []),
    )


def evaluate_rules(
    rules: List[TypingRule],
    ctx: MappingContext,
) -> bool:
    """any-of semantics: 任一规则命中即入选（兼容既有多规则行为）。"""
    if not rules:
        return False
    return any(rule_to_condition(r).evaluate(ctx) for r in rules)


__all__ = ["rule_to_condition", "parcel_to_context", "evaluate_rules"]
