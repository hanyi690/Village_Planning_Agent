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
    AssetKind,
    AxisPlanningParameters,
    FacilityPlanningParameters,
    InterventionAction,
    LinearAssetPlanningParameters,
    MaterializationRole,
    PolygonPlanningParameters,
    SiteAreaPlanningParameters,
    RoadPlanningParameters,
    LINEAR_ASSET_KINDS,
)
ClaimCategory = Literal[
    "site_area",
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
    asset_kind: AssetKind = "none"
    suggested_interventions: list[str] = Field(default_factory=list)
    quantity: float | None = None
    quantity_unit: str = ""
    area_range_ha: tuple[float, float] | None = None
    intervention_action: InterventionAction = "new"
    materialization_role: MaterializationRole | None = None
    road_parameters: RoadPlanningParameters | None = None
    linear_parameters: LinearAssetPlanningParameters | None = None
    facility_parameters: FacilityPlanningParameters | None = None
    axis_parameters: AxisPlanningParameters | None = None
    polygon_parameters: PolygonPlanningParameters | None = None
    site_area_parameters: SiteAreaPlanningParameters | None = None
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
            "site_area": {"parcel", "polygon"},
            "action": {"action"},
        }
        if self.suggested_output_kind not in allowed[self.suggested_category]:
            raise ValueError(
                f"claim category={self.suggested_category} cannot suggest "
                f"{self.suggested_output_kind}"
            )
        allowed_assets = {
            "facility": {"none", "facility"},
            "site_area": {"none"},
            "road": set(LINEAR_ASSET_KINDS),
            "axis": {"none", "axis"},
            "restoration": {"none"},
            "protection": {"none"},
            "zone": {"none", "land_use"},
            "action": {"none"},
        }
        if self.asset_kind not in allowed_assets[self.suggested_category]:
            raise ValueError(
                f"asset_kind={self.asset_kind} is incompatible with "
                f"category={self.suggested_category}"
            )
        if self.road_parameters is not None and self.suggested_category != "road":
            raise ValueError("road_parameters may only appear on road claims")
        if self.suggested_category == "road":
            if self.asset_kind == "none":
                raise ValueError("line claims require an explicit asset_kind")
            if self.asset_kind == "road":
                if self.road_parameters is None or self.linear_parameters is not None:
                    raise ValueError("road asset_kind requires only road_parameters")
            elif self.linear_parameters is None or self.road_parameters is not None:
                raise ValueError("non-road linear assets require only linear_parameters")
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
                "site_footprint",
            },
            "site_area": {"site_footprint"},
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


__all__ = [
    "PlanningClaim",
    "PlanningClaimSet",
    "ClaimCategory",
    "ClaimOutputKind",
]
