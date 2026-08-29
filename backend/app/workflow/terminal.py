"""Typed terminal results for rejected or exhausted workflow dispatches."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.workflow.routing.dispatch import DispatchDiagnostic


class TerminalStatus(StrEnum):
    DIAGNOSTIC_ONLY = "diagnostic_only"
    COMPLETED = "completed"


class TerminalResult(BaseModel):
    """Authoritative terminal projection carried by the workflow checkpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: TerminalStatus
    stage: str
    reason: str
    diagnostic: DispatchDiagnostic | None = None
    retryable: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)


def diagnostic_terminal(diagnostic: DispatchDiagnostic) -> TerminalResult:
    return TerminalResult(
        status=TerminalStatus.DIAGNOSTIC_ONLY,
        stage=diagnostic.target_stage or diagnostic.source_stage or "workflow",
        reason=diagnostic.message,
        diagnostic=diagnostic,
        retryable=diagnostic.retryable,
    )


def terminal_patch(result: TerminalResult) -> dict[str, object]:
    """Return a compact state patch understood by the existing root adapter."""
    payload = result.model_dump(mode="json")
    return {
        "delivery_status": result.status.value,
        "diagnostic_terminal": payload,
        "terminal_ref": payload,
        "dispatch_diagnostic": payload.get("diagnostic"),
    }


__all__ = ["TerminalResult", "TerminalStatus", "diagnostic_terminal", "terminal_patch"]
