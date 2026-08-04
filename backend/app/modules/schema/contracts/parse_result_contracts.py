from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .contract_meta import ContractMeta


class CompilationError(BaseModel):
    field: str = ""
    error: str = ""
    source_text: str = ""
    suggestion: str = ""


class ProjectRequirement(BaseModel):
    project_ref: str
    area_range: tuple[float, float] | None = None
    functions: list[str] = Field(default_factory=list)
    spatial_requirements: dict = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)


class IntentCompilationResult(ContractMeta):
    intent: Any = None  # SpatialPlanningIntent (lazy ref, avoid circular import)
    project_requirements: list[ProjectRequirement] = Field(default_factory=list)
    compilation_errors: list[CompilationError] = Field(default_factory=list)


__all__ = ["CompilationError", "ProjectRequirement", "IntentCompilationResult"]
