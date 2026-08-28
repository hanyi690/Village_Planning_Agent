"""Deterministic objective and feasibility terms for scenario allocation.

This module deliberately contains no solver-specific code.  A relation is a
hard feasibility term when its criticality is ``hard``; soft relations only
contribute their measured score to the objective.  Missing measurements never
receive a neutral success value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.contracts.ground.constraint_factor import ConstraintFactor, RelationSatisfaction


@dataclass(frozen=True)
class RelationTerm:
    relation_id: str
    hard: bool
    weight: float = 1.0


def relation_terms(factors: Iterable[ConstraintFactor]) -> tuple[RelationTerm, ...]:
    return tuple(
        RelationTerm(
            relation_id=factor.factor_id.removeprefix("factor:"),
            hard=bool(factor.hard),
            weight=max(float(factor.weight), 0.0),
        )
        for factor in sorted(factors, key=lambda item: item.factor_id)
    )


def hard_relation_blocked(satisfaction: RelationSatisfaction) -> bool:
    """Fail closed for every hard result other than an explicit satisfaction."""

    return satisfaction.criticality == "hard" and satisfaction.status != "satisfied"


def satisfaction_score(satisfaction: RelationSatisfaction) -> float:
    """Map measured relation status to a bounded soft objective score."""

    if satisfaction.status == "satisfied":
        return 1.0
    if satisfaction.status == "partially_satisfied":
        return max(0.0, min(1.0, float(satisfaction.score)))
    # violated, deferred and not_evaluable are deliberately not neutral.
    return 0.0


def relation_objective(
    factors: Iterable[ConstraintFactor],
    satisfactions: Iterable[RelationSatisfaction],
) -> float:
    by_id = {
        item.relation_id or item.factor_ids[0].removeprefix("factor:"): item
        for item in satisfactions
        if item.relation_id or item.factor_ids
    }
    total = 0.0
    for term in relation_terms(factors):
        if term.hard:
            continue
        total += term.weight * satisfaction_score(by_id.get(term.relation_id, RelationSatisfaction(
            relation_id=term.relation_id,
            subject_ref="",
            status="not_evaluable",
        )))
    return total


__all__ = [
    "RelationTerm",
    "hard_relation_blocked",
    "relation_objective",
    "relation_terms",
    "satisfaction_score",
]
