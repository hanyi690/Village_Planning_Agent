"""Stable exports for the four independent planning output roots."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.domain.allocation.model import PortfolioDecision
from app.domain.demand.model import DemandPortfolio
from app.domain.suitability.model import SuitabilitySurface

from .base import JsonObject, StrictContractModel


class ScenarioSnapshot(StrictContractModel):
    """Materialized end-state projection produced after allocation and changes."""

    status: Literal["complete", "partial", "unresolved"] = "partial"
    current_state_ref: str = ""
    decision_refs: list[str] = Field(default_factory=list)
    materialized_change_refs: list[str] = Field(default_factory=list)
    metrics: JsonObject = Field(default_factory=dict)
    coverage: JsonObject = Field(default_factory=dict)


__all__ = [
    "DemandPortfolio",
    "PortfolioDecision",
    "ScenarioSnapshot",
    "SuitabilitySurface",
]
