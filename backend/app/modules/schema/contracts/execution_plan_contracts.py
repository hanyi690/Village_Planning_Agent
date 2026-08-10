from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .contract_meta import ContractMeta
from .provenance import Provenance


class WorkerType(str, Enum):
    PROJECT_FOOTPRINT = "project_footprint"
    PARCEL_TRANSFORMATION = "parcel_transformation"
    FACILITY_PLACEMENT = "facility_placement"
    ROAD_CONSTRUCTION = "road_construction"
    RESTORATION = "restoration"
    ZONE_SYNTHESIS = "zone_synthesis"


class WorkerTask(BaseModel):
    task_id: str
    worker_type: WorkerType
    payload: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    task_id: str
    status: str = "pending"  # "pending" | "running" | "succeeded" | "failed"
    output_artifacts: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class TypedActionResult(BaseModel):
    """Typed non-spatial execution output for one action target."""

    target_id: str
    action: str = ""
    status: str = "succeeded"
    expected_output_kind: Literal["action"] = "action"
    details: dict = Field(default_factory=dict)


class ExecutionPlan(ContractMeta):
    """EXECUTE worker scheduling plan.

    ``context_version`` / ``provenance`` are inherited from ``ContractMeta``.
    PARSE/SELECT contracts are referenced lazily as ``Any`` to avoid circular
    imports (parse_contracts / selection_contracts import this package).
    """

    plan_id: str = ""
    worker_tasks: list[WorkerTask] = Field(default_factory=list)
    dependencies: list[dict] = Field(default_factory=list)
    provenance: "Provenance | None" = None

    # Lazy references to PARSE/SELECT contracts (embed or None).
    intent: Any = None
    site_selection: Any = None
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
    "ExecutionResult",
    "TypedActionResult",
    "ExecutionPlan",
    "ZoneAssignmentEntry",
    "ParcelAllocationProblem",
    "ZoneAllocationSolution",
    "WorkerResult",
    "RoadPlanResult",
]
