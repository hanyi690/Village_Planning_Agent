"""EXECUTE boundary ports."""

from __future__ import annotations

from typing import Protocol

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.execute.execution_plan_contracts import ExecutionResult


class ExecutionResultConsumerPort(Protocol):
    def load_execution_result(self, artifact_ref: ArtifactRef) -> ExecutionResult:
        """Reload the authoritative execution result for VALIDATE."""


__all__ = ["ExecutionResultConsumerPort"]
