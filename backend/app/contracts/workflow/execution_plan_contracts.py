from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.contracts.artifacts import ArtifactRef

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.provenance import Provenance
from app.contracts.domain.selection_contracts import TargetAssignment


class WorkerType(str, Enum):
    PROJECT_FOOTPRINT = "project_footprint"
    PARCEL_TRANSFORMATION = "parcel_transformation"
    FACILITY_PLACEMENT = "facility_placement"
    ROAD_CONSTRUCTION = "road_construction"
    RESTORATION = "restoration"
    ZONE_SYNTHESIS = "zone_synthesis"
    AXIS_CONSTRUCTION = "axis_construction"
    NON_SPATIAL_ACTION = "non_spatial_action"


class WorkerTask(BaseModel):
    task_id: str
    worker_type: WorkerType
    target_id: str
    target_type: str
    expected_output_kind: Literal["parcel", "polygon", "point", "line", "action"]
    assignment: TargetAssignment
    payload: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    input_artifact_refs: list[str] = Field(default_factory=list)


class TaskExecutionResult(BaseModel):
    """Result for one scheduled execution task."""

    task_id: str
    target_id: str = ""
    status: Literal["pending", "running", "succeeded", "deferred", "failed"] = "pending"
    expected_output_kind: Literal["parcel", "polygon", "point", "line", "action"] = "parcel"
    output_artifacts: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    diagnostics: list[dict] = Field(default_factory=list)


class TypedActionResult(BaseModel):
    """Typed non-spatial execution output for one action target."""

    target_id: str
    action: str = ""
    status: str = "succeeded"
    expected_output_kind: Literal["action"] = "action"
    details: dict = Field(default_factory=dict)


class ExecutionResult(ContractMeta):
    """Authoritative EXECUTE root artifact.

    Child execution facts are referenced here instead of being exposed as
    independent workflow outputs.  The workflow carries only this root
    artifact ref; delivery and validation load its exact child refs.
    """

    schema_version: Literal["3.0"] = "3.0"
    execution_plan_ref: ArtifactRef | None = Field(default=None)
    parcel_changeset_ref: ArtifactRef
    planned_state_ref: ArtifactRef
    deferral_ledger_ref: ArtifactRef | None = Field(default=None)
    layout_configs_ref: ArtifactRef
    task_results: list[TaskExecutionResult] = Field(default_factory=list)
    action_results: list[TypedActionResult] = Field(default_factory=list)
    diagnostics: list[dict] = Field(default_factory=list)

    @field_validator("execution_plan_ref", mode="before")
    @classmethod
    def empty_ref_means_omitted(cls, value: object) -> object:
        if value == {}:
            return None
        return value


class ExecutionPlan(ContractMeta):
    """EXECUTE worker scheduling plan.

    ``context_version`` / ``provenance`` are inherited from ``ContractMeta``.
    PARSE/SELECT contracts are referenced lazily as ``Any`` to avoid circular
    imports (parse_contracts / selection_contracts import this package).
    """

    schema_version: Literal["2.0"] = "2.0"
    plan_id: str = ""
    portfolio_decision_ref: str = ""
    worker_tasks: list[WorkerTask] = Field(default_factory=list)
    deferred_tasks: list[WorkerTask] = Field(default_factory=list)
    dependencies: list[dict] = Field(default_factory=list)
    provenance: "Provenance | None" = None

    land_design_briefs: list[Any] = Field(default_factory=list)


class ZoneAssignmentEntry(BaseModel):
    """Single bsm -> zone allocation decision."""

    bsm: str
    zone_id: str = ""
    land_use: str = ""
    area_ha: float = 0.0
    source: str = "allocator"


class ParcelAllocationProblem(BaseModel):
    """Global zone-allocation problem input (zone targets + candidate parcels)."""

    targets: dict[str, float] = Field(default_factory=dict)
    candidates: dict[str, list[str]] = Field(default_factory=dict)
    constraints: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ZoneAllocationSolution(BaseModel):
    """Global zone-allocation solution produced by a ZoneAllocatorPort."""

    assignments: list[ZoneAssignmentEntry] = Field(default_factory=list)
    unassigned_bsms: list[str] = Field(default_factory=list)
    objective_value: float = 0.0
    feasible: bool = False
    diagnostics: list[str] = Field(default_factory=list)


class WorkerResult(BaseModel):
    """Unified output envelope produced by a single EXECUTE worker."""

    worker_type: str
    task_results: list[TaskExecutionResult] = Field(default_factory=list)
    layers: list[Any] = Field(default_factory=list)
    parcel_changes: list[Any] = Field(default_factory=list)
    action_results: list[TypedActionResult] = Field(default_factory=list)
    relations: list[Any] = Field(default_factory=list)
    unresolved_items: list[Any] = Field(default_factory=list)
    diagnostics: list[Any] = Field(default_factory=list)
    provenance: Any = None


class RoadPlanResult(BaseModel):
    """Output envelope of the RoadPlannerPort adapter."""

    layers: list[Any] = Field(default_factory=list)
    road_plan: Any = None
    road_network_changes: list[Any] = Field(default_factory=list)
    connectivity_report: dict[str, Any] = Field(default_factory=dict)
    unresolved_items: list[Any] = Field(default_factory=list)
    available: bool = False


__all__ = [
    "WorkerType",
    "WorkerTask",
    "TaskExecutionResult",
    "ExecutionResult",
    "TypedActionResult",
    "ExecutionPlan",
    "ZoneAssignmentEntry",
    "ParcelAllocationProblem",
    "ZoneAllocationSolution",
    "WorkerResult",
    "RoadPlanResult",
]
