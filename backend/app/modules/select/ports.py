"""SELECT boundary ports."""

from __future__ import annotations

from typing import Protocol

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.select.scenario import ScenarioSet


class SelectConsumerPort(Protocol):
    def load_scenario_set(self, artifact_ref: ArtifactRef) -> ScenarioSet:
        """Reload the solver-owned scenario set for approval and execution."""


__all__ = ["SelectConsumerPort"]
