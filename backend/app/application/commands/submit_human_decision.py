"""Compare-and-set command for HUMAN review decisions (blueprint M9 surface).

The canonical implementation lives in ``submit_human_review``; this module is
the stable import path requested by the M9 module blueprint.
"""

from __future__ import annotations

from typing import Literal

from app.application.commands.submit_human_review import (
    HumanDecisionConflictError,
    HumanDecisionNotFoundError,
    SubmitHumanDecisionCommand,
    SubmitHumanDecisionResult,
    SubmitHumanDecisionService,
    submit_human_decision_service,
)


class HumanEventIdMismatchError(HumanDecisionConflictError):
    """The supplied event_id does not match the active interrupt token."""


def assert_event_id_matches(values: dict[str, object], expected_event_id: str) -> None:
    """Compare-and-set guard for the HUMAN interrupt event_id token."""

    interrupt = values.get("human_interrupt")
    active_event_id = interrupt.get("event_id") if isinstance(interrupt, dict) else None
    if active_event_id != expected_event_id:
        raise HumanEventIdMismatchError(
            f"event_id {expected_event_id!r} does not match the active interrupt {active_event_id!r}"
        )
    if values.get("human_review_resume_consumed"):
        raise HumanDecisionConflictError("checkpoint was already resumed")


async def submit_human_decision(
    session_id: str,
    *,
    event_id: str,
    action: Literal["retry", "approve", "reject"],
    decisions: dict[str, object] | None = None,
    service: SubmitHumanDecisionService | None = None,
) -> SubmitHumanDecisionResult:
    """Validate the event_id against the active interrupt, then forward."""

    executor = service or submit_human_decision_service
    current = await executor._runtime.current_values(session_id)
    if not current:
        raise HumanDecisionNotFoundError("session not found")
    assert_event_id_matches(dict(current), event_id)
    return await executor.execute(
        SubmitHumanDecisionCommand(
            session_id=session_id,
            event_id=event_id,
            action=action,
            decisions=dict(decisions or {}),
        )
    )


__all__ = [
    "HumanDecisionConflictError",
    "HumanDecisionNotFoundError",
    "HumanEventIdMismatchError",
    "SubmitHumanDecisionCommand",
    "SubmitHumanDecisionResult",
    "SubmitHumanDecisionService",
    "assert_event_id_matches",
    "submit_human_decision",
    "submit_human_decision_service",
]
