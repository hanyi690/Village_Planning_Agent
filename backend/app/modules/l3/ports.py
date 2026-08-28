"""L3 boundary ports."""

from __future__ import annotations

from typing import Protocol

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.l3.l3_contracts import PlanningProgram


class L3ProgramConsumerPort(Protocol):
    def load_program(self, artifact_ref: ArtifactRef) -> PlanningProgram:
        """Reload the authoritative L3 program for TARGET_PROJECTION."""


__all__ = ["L3ProgramConsumerPort"]
