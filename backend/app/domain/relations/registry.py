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


def build_default_relation_registry() -> RelationEvaluatorRegistry:
    """Build the one closed evaluator registry used by runtime and preflight."""

    from .geometry_evaluators import GeometryRelationEvaluator
    from .service import NetworkRelationEvaluator

    geometry = GeometryRelationEvaluator()
    connect = NetworkRelationEvaluator("connect")
    access = NetworkRelationEvaluator("access")
    access_via = NetworkRelationEvaluator("access_via")
    serve = NetworkRelationEvaluator("serve")
    registry = RelationEvaluatorRegistry([geometry, connect, access, access_via, serve])
    for key in (
        "near",
        "far",
        "contain",
        "contains",
        "within",
        "within_allowed_area",
        "avoid",
        "avoid_constraint",
        "adjacent",
        "intersects",
        "overlaps",
        "co_locate",
    ):
        registry.register_alias(key, geometry)
    registry.register_alias("connect_network", connect)
    registry.register_alias("provide_access", access_via)
    registry.register_alias("serve", serve)
    return registry


__all__ = ["RelationEvaluator", "RelationEvaluatorRegistry", "build_default_relation_registry"]
