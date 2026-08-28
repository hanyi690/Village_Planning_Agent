"""GROUND boundary ports."""

from __future__ import annotations

from typing import Protocol

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.ground.grounding_contracts import GroundingResult


class GroundingConsumerPort(Protocol):
    def load_grounding(self, artifact_ref: ArtifactRef) -> GroundingResult:
        """Reload the authoritative grounded candidate domain for SELECT."""


__all__ = ["GroundingConsumerPort"]
