"""L3 stage contracts — interventions, dependencies, and the planning program."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .contract_meta import ContractMeta


class PlanningIntervention(BaseModel):
    intervention_id: str
    name: str
    category: Literal["project", "facility", "road", "restoration", "protection"] = "project"
    problem_addressed: str = ""
    scale: str = ""
    area_range_ha: tuple[float, float] | None = None
    functions: list[str] = []
    service_population: str | None = None
    implementation_phase: Literal["short", "medium", "long"] = "short"
    spatial_requirements: dict = {}
    constraints: list[str] = []
    evidence_refs: list[str] = []


class InterventionDependency(BaseModel):
    from_intervention_id: str
    to_intervention_id: str
    dependency_type: str = ""


class PlanningProgram(ContractMeta):
    interventions: list[PlanningIntervention] = []
    dependencies: list[InterventionDependency] = []
    omissions: list[str] = []


__all__ = [
    "PlanningIntervention",
    "InterventionDependency",
    "PlanningProgram",
]
