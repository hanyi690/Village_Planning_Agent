"""Bounded validation-adjustment execution protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.contracts.workflow.repair import AdjustmentExecutionResult


@runtime_checkable
class ValidationAdjustmentExecutor(Protocol):
    """Apply typed validation adjustments without invoking workflow stages."""

    async def apply(self, state: object, report: object) -> AdjustmentExecutionResult:
        """Return new artifact refs or a typed rejection/failure result."""
        ...


__all__ = ["AdjustmentExecutionResult", "ValidationAdjustmentExecutor"]
