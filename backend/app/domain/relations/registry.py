"""Closed-set evaluator registry with fail-closed unknown-key handling."""

from __future__ import annotations

from typing import Protocol, Sequence

from app.contracts.planning.constraint_factor import ConstraintFactor, RelationSatisfaction


class RelationEvaluator(Protocol):
    evaluator_key: str

    def evaluate(
        self,
        factor: ConstraintFactor,
        features: dict[str, Sequence[object]],
        context: object,
    ) -> RelationSatisfaction: ...


class RelationEvaluatorRegistry:
    def __init__(self, evaluators: Sequence[RelationEvaluator] = ()) -> None:
        self._evaluators = {item.evaluator_key: item for item in evaluators}

    def register(self, evaluator: RelationEvaluator) -> None:
        self._evaluators[evaluator.evaluator_key] = evaluator

    def register_alias(self, evaluator_key: str, evaluator: RelationEvaluator) -> None:
        self._evaluators[evaluator_key] = evaluator

    def get(self, evaluator_key: str) -> RelationEvaluator | None:
        return self._evaluators.get(evaluator_key)

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._evaluators))


__all__ = ["RelationEvaluator", "RelationEvaluatorRegistry"]
