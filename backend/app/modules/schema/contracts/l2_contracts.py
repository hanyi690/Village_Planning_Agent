"""L2 stage contracts — development strategy and conflicts."""

from __future__ import annotations

from pydantic import BaseModel

from .contract_meta import ContractMeta
from .provenance import Provenance


class StrategyConflict(BaseModel):
    description: str
    between: list[str] = []
    severity: str = "warning"


class L2Strategy(ContractMeta):
    development_goals: list[str] = []
    spatial_structure: str = ""
    implementation_priorities: list[str] = []
    strategy_conflicts: list[StrategyConflict] = []
    evidence_refs: list[str] = []
    provenance: "Provenance | None" = None

__all__ = [
    "StrategyConflict",
    "L2Strategy",
]