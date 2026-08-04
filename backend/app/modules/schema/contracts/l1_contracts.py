"""L1 stage contracts — baseline snapshot of facts, constraints, and gaps."""

from __future__ import annotations

from pydantic import BaseModel

from .contract_meta import ContractMeta, StageIssue
from .evidence_contracts import EvidenceSource
from .provenance import Provenance


class L1Snapshot(ContractMeta):
    facts: list[str] = []
    constraints: list[str] = []
    issues: list[StageIssue] = []
    opportunities: list[str] = []
    evidence_gaps: list[str] = []
    sources: list[EvidenceSource] = []
    provenance: "Provenance | None" = None

__all__ = [
    "L1Snapshot",
]