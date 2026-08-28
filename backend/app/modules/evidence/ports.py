"""Ports between Evidence semantics and the centralized retrieval runtime."""

from __future__ import annotations

from typing import Protocol

from app.contracts.evidence.evidence_contracts import ExplorationResult
from app.contracts.evidence.requirement_contracts import EvidenceRequirement

from .application import EvidenceContext


class EvidenceRuntimePort(Protocol):
    async def retrieve(
        self,
        requirement: EvidenceRequirement,
        context: EvidenceContext,
    ) -> ExplorationResult: ...


__all__ = ["EvidenceRuntimePort"]
