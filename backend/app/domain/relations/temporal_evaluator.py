"""Execution-trace-only evaluator for temporal ``precedes`` relations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Sequence

from pydantic import BaseModel, Field

from app.contracts.planning.constraint_factor import (
    ConstraintFactor,
    RelationMeasurement,
    RelationSatisfaction,
)
from app.contracts.planning.relation_parameters import PrecedesParameters


class ExecutionEvent(BaseModel):
    task_id: str
    event: Literal["start", "complete"]
    timestamp: float | datetime


class ExecutionTrace(BaseModel):
    events: list[ExecutionEvent] = Field(default_factory=list)

    def timestamp_for(self, task_id: str, event: Literal["start", "complete"]) -> float | None:
        values = [
            _timestamp(item.timestamp)
            for item in self.events
            if item.task_id == task_id and item.event == event
        ]
        return min(values) if values else None


def _timestamp(value: float | datetime) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


def evaluate_precedes(
    factor: ConstraintFactor,
    trace: ExecutionTrace | None,
    *,
    scenario_id: str = "",
    evaluator_version: str = "relation-evaluator-v1",
) -> RelationSatisfaction:
    """Evaluate only observed execution events; plans are not evidence."""

    relation_id = factor.factor_id.removeprefix("factor:")
    base = dict(
        relation_id=relation_id,
        scenario_id=scenario_id,
        subject_ref=factor.subject_ref,
        object_ref=factor.object_ref,
        criticality="hard" if factor.hard else "soft",
        factor_ids=[factor.factor_id],
        evidence_refs=list(factor.evidence_refs),
        evaluator_version=evaluator_version,
    )
    if trace is None:
        return RelationSatisfaction(
            **base,
            status="pending",
            detail="precedes requires an observed ExecutionTrace",
        )
    if not isinstance(factor.parameters, PrecedesParameters):
        return RelationSatisfaction(
            **base,
            status="deferred",
            detail="precedes is missing typed PrecedesParameters",
        )

    required_event = factor.parameters.required_event
    subject_time = trace.timestamp_for(factor.subject_ref, required_event)
    object_time = trace.timestamp_for(factor.object_ref, "start")
    if subject_time is None or object_time is None:
        return RelationSatisfaction(
            **base,
            status="pending",
            detail="ExecutionTrace lacks required precedes events",
        )
    value = object_time - subject_time
    status = "satisfied" if value >= 0 else "violated"
    return RelationSatisfaction(
        **base,
        status=status,
        measurement=RelationMeasurement(
            value=value,
            unit="s",
            threshold=0,
            operator="gte",
            method="execution_trace_event_order",
        ),
        evaluation_trace=[
            f"subject:{factor.subject_ref}:{required_event}",
            f"object:{factor.object_ref}:start",
        ],
        score=1.0 if status == "satisfied" else 0.0,
    )


__all__ = ["ExecutionEvent", "ExecutionTrace", "evaluate_precedes"]
