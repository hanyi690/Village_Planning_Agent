"""External search gate; decision is made before any provider call."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.contracts.base import JsonObject


class ExternalSearchDecisionCode(StrEnum):
    """Why an external search request was gated."""

    ALLOWED = "allowed"
    DIMENSION_NOT_ALLOWED = "dimension_not_allowed"
    FRESHNESS_MISS = "freshness_miss"
    BUDGET_EXCEEDED = "budget_exceeded"
    DOMAIN_NOT_ALLOWED = "domain_not_allowed"
    POLICY_EMPTY = "policy_empty"


@dataclass
class ExternalSearchDecision:
    """Typed decision produced before any provider call."""

    allowed: bool
    code: ExternalSearchDecisionCode
    reason: str = ""
    budget: JsonObject = field(default_factory=dict)


class ExternalSearchPolicy:
    """Gates external search by dimension, freshness, cost and allowlist."""

    def __init__(
        self,
        allowed_dimensions: list[str] | None = None,
        freshness: dict[str, Any] | None = None,
        max_cost: float | None = None,
        allowlist: list[str] | None = None,
    ) -> None:
        self.allowed_dimensions = list(allowed_dimensions or [])
        self.freshness = dict(freshness or {})
        self.max_cost = max_cost
        self.allowlist = list(allowlist or [])

    def evaluate(
        self,
        dimension_key: str,
        query_purpose: str = "",
        source_domain: str = "",
        budget: JsonObject | None = None,
        freshness: JsonObject | None = None,
    ) -> ExternalSearchDecision:
        """Return a typed decision; no provider is contacted here."""
        if not self.allowed_dimensions and not self.allowlist:
            return ExternalSearchDecision(
                allowed=False,
                code=ExternalSearchDecisionCode.POLICY_EMPTY,
                reason="no external search dimension or domain allowlist configured",
            )

        if self.allowed_dimensions and dimension_key not in self.allowed_dimensions:
            return ExternalSearchDecision(
                allowed=False,
                code=ExternalSearchDecisionCode.DIMENSION_NOT_ALLOWED,
                reason=f"dimension '{dimension_key}' not in allowlist",
            )

        if self.allowlist and source_domain and source_domain not in self.allowlist:
            return ExternalSearchDecision(
                allowed=False,
                code=ExternalSearchDecisionCode.DOMAIN_NOT_ALLOWED,
                reason=f"source domain '{source_domain}' not in allowlist",
            )

        if self.max_cost is not None:
            est = self._estimated_cost(budget)
            if est is not None and est > self.max_cost:
                return ExternalSearchDecision(
                    allowed=False,
                    code=ExternalSearchDecisionCode.BUDGET_EXCEEDED,
                    reason=f"estimated cost {est} exceeds max {self.max_cost}",
                    budget=budget or {},
                )

        if self.freshness and freshness:
            if not self._within_freshness(freshness):
                return ExternalSearchDecision(
                    allowed=False,
                    code=ExternalSearchDecisionCode.FRESHNESS_MISS,
                    reason="source age exceeds configured freshness window",
                )

        return ExternalSearchDecision(
            allowed=True,
            code=ExternalSearchDecisionCode.ALLOWED,
            reason="",
            budget=budget or {},
        )

    def _estimated_cost(self, budget: JsonObject | None) -> float | None:
        if not budget:
            return None
        for key in ("estimated_cost", "cost", "max_cost"):
            value = budget.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None

    def _within_freshness(self, freshness: JsonObject) -> bool:
        allowed_window = self.freshness.get("max_age_days")
        if allowed_window is None:
            return True
        source_age_days = freshness.get("age_days")
        if source_age_days is None:
            return True
        try:
            return float(source_age_days) <= float(allowed_window)
        except (TypeError, ValueError):
            return False


__all__ = ["ExternalSearchDecision", "ExternalSearchDecisionCode", "ExternalSearchPolicy"]
