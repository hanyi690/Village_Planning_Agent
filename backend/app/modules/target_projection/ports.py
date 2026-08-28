"""TARGET_PROJECTION boundary ports."""

from __future__ import annotations

from typing import Protocol

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.target_projection.parse_result_contracts import IntentCompilationResult


class TargetProjectionConsumerPort(Protocol):
    def load_projection(self, artifact_ref: ArtifactRef) -> IntentCompilationResult:
        """Reload the authoritative projection for GROUND."""


__all__ = ["TargetProjectionConsumerPort"]
