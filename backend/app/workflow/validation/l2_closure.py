"""Deterministic fail-closed validation for typed L2 decision graphs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from typing import Any

from app.contracts.l2.l2_contracts import (
    CanonicalGroundingRequirement,
    CanonicalRelationKind,
    L2DecisionSet,
    L2Strategy,
)


_CLOSED_GROUNDING_REQUIREMENTS = set(CanonicalGroundingRequirement.__args__)
_CLOSED_RELATION_KINDS = set(CanonicalRelationKind.__args__)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _raise_if_errors(errors: list[str]) -> None:
    if errors:
        raise ValueError("\n".join(errors))


def _collect_ids(decision_set: L2DecisionSet) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    rows.extend((item.objective_id, "objective") for item in decision_set.objectives)
    rows.extend((item.metric_id, "metric") for item in decision_set.metrics)
    rows.extend((item.strategy_id, "strategy") for item in decision_set.strategies)
    rows.extend((item.priority_id, "priority") for item in decision_set.priorities)
    rows.extend((item.structure_id, "spatial_structure") for item in decision_set.spatial_structures)
    rows.extend((item.conflict_id, "conflict") for item in decision_set.conflicts)
    rows.extend((item.gap_id, "evidence_gap") for item in decision_set.evidence_gaps)
    return rows


def _validate_source_fact_refs(
    refs: Sequence[str],
    *,
    field_name: str,
    owner_id: str,
    known_l1_fact_ids: Collection[str] | None,
) -> list[str]:
    errors: list[str] = []
    for ref in refs:
        text = _text(ref)
        if not text.startswith("l1:fact:"):
            errors.append(f"{field_name}:{owner_id}:wrong_namespace:{text}")
            continue
        if known_l1_fact_ids is not None and text not in known_l1_fact_ids:
            errors.append(f"{field_name}:{owner_id}:dangling:{text}")
    return errors


def validate_metric_quantity(metric: Any) -> list[str]:
    errors: list[str] = []
    unit = _text(metric.unit)
    value = metric.value
    if isinstance(value, (int, float)) and not unit:
        errors.append(f"metric_quantity_unit_missing:{metric.metric_id}")
        return errors
    if isinstance(value, str):
        raw = _text(value)
        if not raw:
            return errors
        numeric_chars: list[str] = []
        suffix_chars: list[str] = []
        in_suffix = False
        for char in raw:
            if (char.isdigit() or char in {".", "-", "+", " "}) and not in_suffix:
                numeric_chars.append(char)
                continue
            in_suffix = True
            suffix_chars.append(char)
        numeric_text = "".join(numeric_chars).strip()
        suffix_text = "".join(suffix_chars).strip()
        try:
            float(numeric_text)
        except ValueError:
            errors.append(f"metric_quantity_invalid:{metric.metric_id}")
            return errors
        if not unit and not suffix_text:
            errors.append(f"metric_quantity_unit_missing:{metric.metric_id}")
        elif unit and suffix_text and suffix_text != unit:
            errors.append(f"metric_unit_mismatch:{metric.metric_id}:{suffix_text}!={unit}")
    return errors


def _validate_prerequisite_cycles(strategy_refs: dict[str, list[str]]) -> list[str]:
    errors: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    strategy_ids = set(strategy_refs)

    def walk(node: str, trail: list[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            cycle_start = trail.index(node)
            cycle = trail[cycle_start:] + [node]
            errors.append(f"prerequisite_cycle:{'->'.join(cycle)}")
            return
        visiting.add(node)
        for parent in strategy_refs.get(node, []):
            if parent not in strategy_ids:
                errors.append(f"prerequisite_missing:{node}:{parent}")
                continue
            walk(parent, [*trail, parent])
        visiting.remove(node)
        visited.add(node)

    for strategy_id in sorted(strategy_refs):
        walk(strategy_id, [strategy_id])
    return errors


def validate_l2_decision_set(
    decision_set: L2DecisionSet | dict[str, Any],
    *,
    known_l1_fact_ids: Collection[str] | None = None,
) -> L2DecisionSet:
    decision = (
        decision_set
        if isinstance(decision_set, L2DecisionSet)
        else L2DecisionSet.model_validate(decision_set)
    )
    errors: list[str] = []

    counts = Counter(item_id for item_id, _kind in _collect_ids(decision))
    errors.extend(
        f"duplicate_id:{item_id}"
        for item_id in sorted(key for key, count in counts.items() if count > 1)
    )

    objective_ids = {item.objective_id for item in decision.objectives}
    strategy_ids = {item.strategy_id for item in decision.strategies}

    for objective in decision.objectives:
        if objective.status == "observed" and not objective.source_fact_refs:
            errors.append(f"observed_objective_evidence_missing:{objective.objective_id}")
        errors.extend(
            _validate_source_fact_refs(
                objective.source_fact_refs,
                field_name="objective_source_fact_refs",
                owner_id=objective.objective_id,
                known_l1_fact_ids=known_l1_fact_ids,
            )
        )

    for metric in decision.metrics:
        if metric.status == "observed" and not metric.source_fact_refs:
            errors.append(f"observed_metric_evidence_missing:{metric.metric_id}")
        errors.extend(
            _validate_source_fact_refs(
                metric.source_fact_refs,
                field_name="metric_source_fact_refs",
                owner_id=metric.metric_id,
                known_l1_fact_ids=known_l1_fact_ids,
            )
        )
        errors.extend(validate_metric_quantity(metric))

    for strategy in decision.strategies:
        if not strategy.source_fact_refs:
            errors.append(f"proposed_strategy_evidence_missing:{strategy.strategy_id}")
        errors.extend(
            _validate_source_fact_refs(
                strategy.source_fact_refs,
                field_name="strategy_source_fact_refs",
                owner_id=strategy.strategy_id,
                known_l1_fact_ids=known_l1_fact_ids,
            )
        )
        for ref in strategy.objective_refs:
            if ref not in objective_ids:
                errors.append(f"strategy_objective_ref_missing:{strategy.strategy_id}:{ref}")

    for priority in decision.priorities:
        for ref in priority.strategy_refs:
            if ref not in strategy_ids:
                errors.append(f"priority_strategy_ref_missing:{priority.priority_id}:{ref}")

    for structure in decision.spatial_structures:
        if not structure.source_fact_refs:
            errors.append(f"spatial_structure_evidence_missing:{structure.structure_id}")
        errors.extend(
            _validate_source_fact_refs(
                structure.source_fact_refs,
                field_name="spatial_structure_source_fact_refs",
                owner_id=structure.structure_id,
                known_l1_fact_ids=known_l1_fact_ids,
            )
        )
        for ref in structure.objective_refs:
            if ref not in objective_ids:
                errors.append(
                    f"spatial_structure_objective_ref_missing:{structure.structure_id}:{ref}"
                )
        relation_kind = _text(structure.relation_kind)
        if not relation_kind:
            errors.append(f"spatial_relation_missing:{structure.structure_id}")
        elif relation_kind not in _CLOSED_RELATION_KINDS:
            errors.append(f"spatial_relation_not_closed:{structure.structure_id}:{relation_kind}")
        for grounding in structure.grounding_requirements:
            grounding_text = _text(grounding)
            if grounding_text not in _CLOSED_GROUNDING_REQUIREMENTS:
                errors.append(
                    f"grounding_requirement_not_closed:{structure.structure_id}:{grounding_text}"
                )

    for conflict in decision.conflicts:
        for ref in conflict.objective_refs:
            if ref not in objective_ids:
                errors.append(f"conflict_objective_ref_missing:{conflict.conflict_id}:{ref}")
        for ref in conflict.strategy_refs:
            if ref not in strategy_ids:
                errors.append(f"conflict_strategy_ref_missing:{conflict.conflict_id}:{ref}")
        endpoint_count = len(set([*conflict.objective_refs, *conflict.strategy_refs]))
        if endpoint_count < 2:
            errors.append(f"conflict_endpoints_incomplete:{conflict.conflict_id}")

    prerequisite_refs = {
        item.strategy_id: [_text(ref) for ref in item.prerequisite_refs if _text(ref)]
        for item in decision.strategies
    }
    errors.extend(_validate_prerequisite_cycles(prerequisite_refs))

    _raise_if_errors(errors)
    return decision


def validate_l2_strategy_graph(
    strategy_graph: L2Strategy | Sequence[L2DecisionSet] | dict[str, Any],
    *,
    known_l1_fact_ids: Collection[str] | None = None,
) -> L2Strategy | list[L2DecisionSet]:
    if isinstance(strategy_graph, L2Strategy):
        strategy = strategy_graph
        decision_sets = list(strategy.decision_sets or [])
    elif isinstance(strategy_graph, Sequence) and not isinstance(strategy_graph, dict):
        strategy = None
        decision_sets = [
            item if isinstance(item, L2DecisionSet) else L2DecisionSet.model_validate(item)
            for item in strategy_graph
        ]
    else:
        strategy = L2Strategy.model_validate(strategy_graph)
        decision_sets = list(strategy.decision_sets or [])

    validated: list[L2DecisionSet] = []
    errors: list[str] = []
    for decision in decision_sets:
        try:
            validated.append(
                validate_l2_decision_set(
                    decision,
                    known_l1_fact_ids=known_l1_fact_ids,
                )
            )
        except ValueError as exc:
            errors.extend(line for line in str(exc).splitlines() if line.strip())

    counts = Counter(
        item_id
        for decision in validated
        for item_id, _kind in _collect_ids(decision)
    )
    errors.extend(
        f"duplicate_id:{item_id}"
        for item_id in sorted(key for key, count in counts.items() if count > 1)
    )

    prerequisite_refs = {
        item.strategy_id: [_text(ref) for ref in item.prerequisite_refs if _text(ref)]
        for decision in validated
        for item in decision.strategies
    }
    errors.extend(_validate_prerequisite_cycles(prerequisite_refs))

    _raise_if_errors(errors)
    return strategy if strategy is not None else validated


__all__ = [
    "validate_l2_decision_set",
    "validate_l2_strategy_graph",
    "validate_metric_quantity",
]
