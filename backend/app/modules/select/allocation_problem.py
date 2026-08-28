"""Typed allocation problems reusing domain portfolio contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.select.model import (
    AllocationAssignment,
    AllocationStatus,
    PortfolioDecision,
)


class AllocationProblem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    zone_id: str
    target_area_ha: float = 0.0
    candidate_bsms: list[str] = Field(default_factory=list)
    preserved_bsms: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def usable_bsms(self) -> list[str]:
        preserved = set(self.preserved_bsms)
        return [bsm for bsm in self.candidate_bsms if bsm not in preserved]


class AllocationProblemSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    problems: list[AllocationProblem] = Field(default_factory=list)
    portfolio_decision: PortfolioDecision | None = None

    @property
    def total_target_area_ha(self) -> float:
        return sum(problem.target_area_ha for problem in self.problems)


__all__ = [
    "AllocationAssignment",
    "AllocationProblem",
    "AllocationProblemSet",
    "AllocationStatus",
    "PortfolioDecision",
]
