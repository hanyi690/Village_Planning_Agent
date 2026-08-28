from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.contracts.artifacts import ArtifactRef

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.provenance import Provenance
from app.contracts.execute.materialization_contracts import TargetAssignment
from app.contracts.select.scenario import ScenarioFeature


class WorkerType(str, Enum):
    SITE_AREA_FOOTPRINT = "site_area_footprint"
    PARCEL_TRANSFORMATION = "parcel_transformation"
    FACILITY_PLACEMENT = "facility_placement"
    ROAD_CONSTRUCTION = "road_construction"
    UTILITY_NETWORK = "utility_network"
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
    required_capability: str = ""
    defer_reason: str = ""
    scenario_id: str = ""
    candidate_id: str = ""
    candidate_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    feature_ids: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    relation_refs: list[str] = Field(default_factory=list)
    target_binding: dict[str, Any] = Field(default_factory=dict)
    feature_bsms: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""
    source_binding_ref: str = ""
    availability_status: Literal[
        "fully_available",
        "partially_available",
        "fully_unavailable",
        "unknown",
    ] = "unknown"
    eligible_area_ha: float | None = Field(default=None, ge=0)
    excluded_area_ha: float | None = Field(default=None, ge=0)
    adjacent_parcel_bsms: list[str] = Field(default_factory=list)
    adjacency_evidence_refs: list[str] = Field(default_factory=list)


class TaskExecutionResult(BaseModel):
    """Result for one scheduled execution task."""

    task_id: str
    target_id: str = ""
    status: Literal["pending", "running", "succeeded", "deferred", "failed"] = "pending"
    expected_output_kind: Literal["parcel", "polygon", "point", "line", "action"] = "parcel"
    output_artifacts: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    diagnostics: list[dict] = Field(default_factory=list)
    scenario_id: str = ""
    candidate_id: str = ""
    candidate_ids: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    feature_ids: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    relation_refs: list[str] = Field(default_factory=list)
    execution_trace_refs: list[str] = Field(default_factory=list)
    feature_bsms: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""
    source_binding_ref: str = ""
    availability_status: Literal[
        "fully_available",
        "partially_available",
        "fully_unavailable",
        "unknown",
    ] = "unknown"
    eligible_area_ha: float | None = Field(default=None, ge=0)
    excluded_area_ha: float | None = Field(default=None, ge=0)
    adjacent_parcel_bsms: list[str] = Field(default_factory=list)
    adjacency_evidence_refs: list[str] = Field(default_factory=list)


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
    # A failed pre-commit is still a typed EXECUTE result, but it must not
    # manufacture a formal PlannedState.  Formal child refs are therefore
    # optional at the abort boundary and required for a committed result.
    parcel_changeset_ref: ArtifactRef | None = None
    planned_state_ref: ArtifactRef | None = None
    deferral_ledger_ref: ArtifactRef | None = Field(default=None)
    layout_configs_ref: ArtifactRef | None = None
    task_results: list[TaskExecutionResult] = Field(default_factory=list)
    action_results: list[TypedActionResult] = Field(default_factory=list)
    diagnostics: list[dict] = Field(default_factory=list)
    scenario_id: str = ""
    scenario_ref: str = ""
    execution_trace_refs: list[str] = Field(default_factory=list)
    bundle_snapshot_digest: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    approved_input_ref: ArtifactRef | None = Field(default=None)
    atomic_commit_id: str = ""
    atomic_commit_status: Literal["committed", "aborted"] = "aborted"

    @field_validator("execution_plan_ref", mode="before")
    @classmethod
    def empty_ref_means_omitted(cls, value: object) -> object:
        if value == {}:
            return None
        return value

    @model_validator(mode="after")
    def validate_atomic_contract(self) -> "ExecutionResult":
        formal_refs = {
            "parcel_changeset_ref": self.parcel_changeset_ref,
            "planned_state_ref": self.planned_state_ref,
            "layout_configs_ref": self.layout_configs_ref,
        }
        if self.atomic_commit_status == "committed":
            if self.approved_input_ref is None:
                raise ValueError("committed execution result requires approved_input_ref")
            if not self.atomic_commit_id:
                raise ValueError("committed execution result requires atomic_commit_id")
            if self.execution_plan_ref is None:
                raise ValueError("committed execution result requires execution_plan_ref")
            missing = [name for name, ref in formal_refs.items() if ref is None]
            if missing:
                raise ValueError(
                    "committed execution result requires promoted formal refs: "
                    + ", ".join(missing)
                )
        else:
            if self.atomic_commit_id:
                raise ValueError("aborted execution result cannot expose atomic_commit_id")
            promoted = [name for name, ref in formal_refs.items() if ref is not None]
            if promoted:
                raise ValueError(
                    "aborted execution result cannot expose promoted formal refs: "
                    + ", ".join(promoted)
                )
        return self


class ExecutionPlan(ContractMeta):
    """EXECUTE worker scheduling plan.

    ``context_version`` / ``provenance`` are inherited from ``ContractMeta``.
    PARSE/SELECT contracts are referenced lazily as ``Any`` to avoid circular
    imports (parse_contracts import this package).
    """

    schema_version: Literal["2.0"] = "2.0"
    plan_id: str = ""
    approved_input_fingerprint: str = ""
    scenario_id: str = ""
    scenario_fingerprint: str = ""
    problem_fingerprint: str = ""
    candidate_ids: list[str] = Field(default_factory=list)
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
    scenario_features: list[ScenarioFeature] = Field(default_factory=list)
    execution_events: list[dict[str, Any]] = Field(default_factory=list)
    task_id: str = ""


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
