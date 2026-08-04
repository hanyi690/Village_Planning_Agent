from __future__ import annotations

from enum import Enum

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


class ExecutionPlan(ContractMeta):
    plan_id: str = ""
    worker_tasks: list[WorkerTask] = Field(default_factory=list)
    dependencies: list[dict] = Field(default_factory=list)
    provenance: "Provenance | None" = None