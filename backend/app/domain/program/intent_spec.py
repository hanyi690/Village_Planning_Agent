"""Typed per-task intent specifications at the program boundary (M4/M6).

Each task carries ``{intent, site_selection_ref, geometry_expectation, deps,
parent_refs, expected_output_kind}``.  These specs are derived from typed
program/decision inputs, never from claim or report text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.workflow.execution_plan_contracts import WorkerType

GeometryExpectation = Literal["parcel", "polygon", "point", "line", "action"]
ImplementationPhase = Literal["short", "medium", "long"]


class TaskIntentSpec(BaseModel):
    """One typed execution-intent per target, without any spatial fact."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    target_id: str
    intent: str
    worker_type: WorkerType = WorkerType.PROJECT_FOOTPRINT
    site_selection_ref: str = ""
    geometry_expectation: GeometryExpectation = "action"
    deps: list[str] = Field(default_factory=list)
    parent_refs: list[str] = Field(default_factory=list)
    expected_output_kind: GeometryExpectation = "action"


class PlanningHumanDecision(BaseModel):
    """Explicit HUMAN-approved decision for one program target."""

    model_config = ConfigDict(extra="forbid")

    target_id: str
    approved: bool = True
    name: str = ""
    scale: str = ""
    implementation_phase: ImplementationPhase = "short"
    area_range_ha: tuple[float, float] | None = None
    spatial_requirements: dict = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)


class PlanningIntentSpecSet(BaseModel):
    """Versioned container of per-task intent specs plus program refs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    demand_portfolio_ref: str = ""
    portfolio_decision_ref: str = ""
    task_specs: list[TaskIntentSpec] = Field(default_factory=list)


__all__ = [
    "GeometryExpectation",
    "ImplementationPhase",
    "PlanningHumanDecision",
    "PlanningIntentSpecSet",
    "TaskIntentSpec",
]
