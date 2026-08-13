"""Non-authoritative planning synthesis contracts.

These objects are deliberately not ``PlanningProgram``.  They may be
created from LLM output or report compilation, but they cannot be sent to
EXECUTE.  A deterministic program assembler is the only producer of the
authoritative program contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.domain.planning_semantics import (
    AxisPlanningParameters,
    FacilityPlanningParameters,
    InterventionAction,
    MaterializationRole,
    PolygonPlanningParameters,
    ProjectPlanningParameters,
    RoadPlanningParameters,
)


ProposalCategory = Literal[
    "project",
    "facility",
    "road",
    "axis",
    "restoration",
    "protection",
    "zone",
]
ProposalOutputKind = Literal["parcel", "polygon", "point", "line", "action"]
ProposalExecutionMode = Literal["spatial", "non_spatial"]
ClaimCategory = Literal[
    "project",
    "facility",
    "road",
    "axis",
    "restoration",
    "protection",
    "zone",
    "action",
]
ClaimOutputKind = Literal["parcel", "polygon", "point", "line", "action"]


class PlanningClaim(BaseModel):
    """Evidence-bearing statement that explains why a proposal exists."""

    claim_id: str
    dimension_key: str = ""
    statement: str
    affected_population: float | None = None
    affected_parcel_refs: list[str] = Field(default_factory=list)
    suggested_category: ClaimCategory = "action"
    suggested_output_kind: ClaimOutputKind = "action"
    suggested_interventions: list[str] = Field(default_factory=list)
    quantity: float | None = None
    quantity_unit: str = ""
    area_range_ha: tuple[float, float] | None = None
    intervention_action: InterventionAction = "new"
    materialization_role: MaterializationRole | None = None
    road_parameters: RoadPlanningParameters | None = None
    facility_parameters: FacilityPlanningParameters | None = None
    axis_parameters: AxisPlanningParameters | None = None
    polygon_parameters: PolygonPlanningParameters | None = None
    project_parameters: ProjectPlanningParameters | None = None
    implementation_phase: Literal["short", "medium", "long"] = "short"
    location_hints: list[str] = Field(default_factory=list)
    constraint_refs: list[str] = Field(default_factory=list)
    objective_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    confidence: float | None = None
    uncertainty: str = ""

    @model_validator(mode="after")
    def validate_suggestion(self) -> "PlanningClaim":
        allowed = {
            "facility": {"point"},
            "road": {"line"},
            "axis": {"line"},
            "restoration": {"polygon"},
            "protection": {"polygon"},
            "zone": {"polygon"},
            "project": {"parcel", "polygon", "point", "action"},
            "action": {"action"},
        }
        if self.suggested_output_kind not in allowed[self.suggested_category]:
            raise ValueError(
                f"claim category={self.suggested_category} cannot suggest "
                f"{self.suggested_output_kind}"
            )
        if self.road_parameters is not None and self.suggested_category != "road":
            raise ValueError("road_parameters may only appear on road claims")
        if self.facility_parameters is not None and self.suggested_category != "facility":
            raise ValueError("facility_parameters may only appear on facility claims")
        if self.axis_parameters is not None and self.suggested_category != "axis":
            raise ValueError("axis_parameters may only appear on axis claims")
        allowed_roles = {
            "protection": {"protection_overlay"},
            "restoration": {"restoration_overlay"},
            "zone": {
                "land_use_assignment",
                "functional_overlay",
                "protection_overlay",
                "restoration_overlay",
                "project_footprint",
            },
            "project": {"project_footprint"},
        }
        if (
            self.materialization_role is not None
            and self.materialization_role
            not in allowed_roles.get(self.suggested_category, set())
        ):
            raise ValueError(
                "materialization_role is incompatible with suggested_category"
            )
        return self


class PlanningClaimSet(BaseModel):
    """Non-executable, evidence-bearing output of one L3 dimension."""

    schema_version: Literal["1.0", "2.0"] = "2.0"
    dimension_key: str = ""
    claims: list[PlanningClaim] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class ProgramProposal(BaseModel):
    """Candidate intervention; never an executable planning program item."""

    proposal_id: str
    name: str
    category: ProposalCategory
    execution_mode: ProposalExecutionMode
    expected_output_kind: ProposalOutputKind
    problem_addressed: str = ""
    scale: str = ""
    area_range_ha: tuple[float, float] | None = None
    intervention_action: InterventionAction = "new"
    materialization_role: MaterializationRole | None = None
    road_parameters: RoadPlanningParameters | None = None
    facility_parameters: FacilityPlanningParameters | None = None
    axis_parameters: AxisPlanningParameters | None = None
    polygon_parameters: PolygonPlanningParameters | None = None
    project_parameters: ProjectPlanningParameters | None = None
    functions: list[str] = Field(default_factory=list)
    service_population: str | None = None
    implementation_phase: Literal["short", "medium", "long"] = "short"
    spatial_requirements: dict = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_ref: str = ""

    @model_validator(mode="after")
    def validate_output(self) -> "ProgramProposal":
        if self.execution_mode == "non_spatial" and self.expected_output_kind != "action":
            raise ValueError("non-spatial proposals must use action output")
        if self.execution_mode == "spatial" and self.expected_output_kind == "action":
            raise ValueError("spatial proposals cannot use action output")
        allowed = {
            "facility": {"point"},
            "road": {"line"},
            "axis": {"line"},
            "restoration": {"polygon"},
            "protection": {"polygon"},
            "zone": {"polygon"},
            "project": {"parcel", "polygon", "point", "action"},
        }
        if self.expected_output_kind not in allowed[self.category]:
            raise ValueError(
                f"category={self.category} cannot produce {self.expected_output_kind}"
            )
        if self.road_parameters is not None and self.category != "road":
            raise ValueError("road_parameters may only appear on road proposals")
        if self.facility_parameters is not None and self.category != "facility":
            raise ValueError("facility_parameters may only appear on facility proposals")
        if self.axis_parameters is not None and self.category != "axis":
            raise ValueError("axis_parameters may only appear on axis proposals")
        return self


__all__ = [
    "PlanningClaim",
    "PlanningClaimSet",
    "ProgramProposal",
    "ProposalCategory",
    "ProposalOutputKind",
    "ProposalExecutionMode",
    "ClaimCategory",
    "ClaimOutputKind",
]
