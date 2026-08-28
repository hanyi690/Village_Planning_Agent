"""Stable exports for the four independent planning output roots."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.modules.select.model import PortfolioDecision
from app.modules.l2.demand_model import DemandPortfolio
from app.modules.l2.suitability_model import SuitabilitySurface

from app.contracts.base import JsonObject, StrictContractModel


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
