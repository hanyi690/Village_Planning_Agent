"""Evidence-complete contracts for executable road planning inputs.

These models deliberately separate operations on authoritative current-road
segments from generation of a new corridor.  They contain no text parsing and
no geometry fallback policy.  A candidate is executable only after the
preparation boundary has attached auditable source artifacts.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, Field, model_validator


RoadPlanningKind: TypeAlias = Literal[
    "existing_road_intervention",
    "new_corridor",
]
ExistingRoadAction: TypeAlias = Literal["upgrade", "widen", "harden", "repair"]


class RoadArtifactEvidence(BaseModel):
    """Reference to an immutable spatial artifact used by road planning."""

    role: Literal[
        "current_road_network",
        "dem",
        "land_friction",
        "hazard",
        "spatial_constraints",
    ]
    artifact_ref: str = Field(min_length=1)
    checksum: str = Field(min_length=1)


class RoadEndpointEvidence(BaseModel):
    """A resolved endpoint with geometry lineage.

    Plain place names, a village-wide bbox, or a direction-derived proxy point
    do not satisfy this contract.  A resolved endpoint must identify both the
    source artifact and the entity/feature that supplied its coordinate.
    """

    role: Literal["start", "end"]
    resolution_status: Literal["resolved", "ambiguous", "unresolved"]
    entity_ref: str | None = None
    coordinate: tuple[float, float] | None = None
    coordinate_crs: str = ""
    source_artifact_ref: str = ""
    source_feature_id: str = ""
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_resolved_endpoint(self) -> "RoadEndpointEvidence":
        self.evidence_refs = list(dict.fromkeys(self.evidence_refs))
        if self.resolution_status != "resolved":
            return self
        if self.coordinate is None:
            raise ValueError("resolved road endpoint requires a coordinate")
        if not self.coordinate_crs.strip():
            raise ValueError("resolved road endpoint requires coordinate_crs")
        if not self.source_artifact_ref.strip():
            raise ValueError("resolved road endpoint requires source_artifact_ref")
        if not (str(self.entity_ref or "").strip() or self.source_feature_id.strip()):
            raise ValueError("resolved road endpoint requires entity_ref or source_feature_id")
        if not self.evidence_refs:
            raise ValueError("resolved road endpoint requires evidence_refs")
        return self


class RoadRoutingEvidence(BaseModel):
    """Spatial evidence available to deterministic route generation."""

    current_network: RoadArtifactEvidence | None = None
    dem: RoadArtifactEvidence | None = None
    land_friction: RoadArtifactEvidence | None = None
    hazard: RoadArtifactEvidence | None = None
    spatial_constraints: RoadArtifactEvidence | None = None

    @model_validator(mode="after")
    def validate_artifact_roles(self) -> "RoadRoutingEvidence":
        expected_roles = {
            "current_network": "current_road_network",
            "dem": "dem",
            "land_friction": "land_friction",
            "hazard": "hazard",
            "spatial_constraints": "spatial_constraints",
        }
        for field_name, expected_role in expected_roles.items():
            evidence = getattr(self, field_name)
            if evidence is not None and evidence.role != expected_role:
                raise ValueError(
                    f"{field_name} requires artifact role {expected_role!r}, "
                    f"got {evidence.role!r}"
                )
        return self

    @property
    def has_routing_basis(self) -> bool:
        return any((self.current_network, self.dem, self.land_friction))


class ExistingRoadPlanningInput(BaseModel):
    """Operation constrained to verified features/segments of the current road."""

    planning_kind: Literal["existing_road_intervention"] = "existing_road_intervention"
    target_id: str = Field(min_length=1)
    source_project_id: str = ""
    action: ExistingRoadAction
    road_level: str = ""
    length_m: float | None = Field(default=None, gt=0)
    roadbed_width_m: float | None = Field(default=None, gt=0)
    pavement_width_m: float | None = Field(default=None, gt=0)
    existing_road_feature_ids: list[str] = Field(default_factory=list)
    existing_road_segment_ids: list[str] = Field(default_factory=list)
    road_evidence_refs: list[str] = Field(default_factory=list)
    routing_evidence: RoadRoutingEvidence

    @model_validator(mode="after")
    def validate_existing_binding(self) -> "ExistingRoadPlanningInput":
        self.existing_road_feature_ids = sorted(set(self.existing_road_feature_ids))
        self.existing_road_segment_ids = sorted(set(self.existing_road_segment_ids))
        self.road_evidence_refs = list(dict.fromkeys(self.road_evidence_refs))
        if not (self.existing_road_feature_ids or self.existing_road_segment_ids):
            raise ValueError("existing-road intervention requires a feature or segment id")
        if self.routing_evidence.current_network is None:
            raise ValueError("existing-road intervention requires current-network evidence")
        return self


class NewCorridorPlanningInput(BaseModel):
    """New road corridor between two distinct, auditable endpoints."""

    planning_kind: Literal["new_corridor"] = "new_corridor"
    target_id: str = Field(min_length=1)
    source_project_id: str = ""
    action: Literal["new"] = "new"
    road_level: str = ""
    length_m: float | None = Field(default=None, gt=0)
    roadbed_width_m: float | None = Field(default=None, gt=0)
    pavement_width_m: float | None = Field(default=None, gt=0)
    start_endpoint: RoadEndpointEvidence
    end_endpoint: RoadEndpointEvidence
    routing_evidence: RoadRoutingEvidence

    @model_validator(mode="after")
    def validate_corridor(self) -> "NewCorridorPlanningInput":
        if self.start_endpoint.role != "start" or self.end_endpoint.role != "end":
            raise ValueError("new-corridor endpoints have incorrect roles")
        if (
            self.start_endpoint.resolution_status != "resolved"
            or self.end_endpoint.resolution_status != "resolved"
        ):
            raise ValueError("new-corridor endpoints must both be resolved")
        same_entity = (
            self.start_endpoint.entity_ref
            and self.start_endpoint.entity_ref == self.end_endpoint.entity_ref
        )
        same_coordinate = self.start_endpoint.coordinate == self.end_endpoint.coordinate
        if same_entity or same_coordinate:
            raise ValueError("new-corridor endpoints must be distinct")
        if not self.routing_evidence.has_routing_basis:
            raise ValueError("new corridor requires network, DEM, or land-friction evidence")
        return self


RoadPlanningInput: TypeAlias = Annotated[
    ExistingRoadPlanningInput | NewCorridorPlanningInput,
    Field(discriminator="planning_kind"),
]


class RoadPreparationDiagnostic(BaseModel):
    code: str
    severity: Literal["error", "warning", "info"] = "error"
    message: str
    field_path: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class RoadCandidatePreparationResult(BaseModel):
    target_id: str
    planning_kind: RoadPlanningKind | None = None
    status: Literal["ready", "unresolved"]
    planning_input: RoadPlanningInput | None = None
    diagnostics: list[RoadPreparationDiagnostic] = Field(default_factory=list)


class RoadCandidatePreparationBatch(BaseModel):
    results: list[RoadCandidatePreparationResult] = Field(default_factory=list)
    ready_inputs: list[RoadPlanningInput] = Field(default_factory=list)
    unresolved_target_ids: list[str] = Field(default_factory=list)


class RoadEvidenceCatalog(BaseModel):
    """Authoritative ids and entity endpoints visible at preparation time."""

    current_network: RoadArtifactEvidence | None = None
    routing_evidence: RoadRoutingEvidence = Field(default_factory=RoadRoutingEvidence)
    current_road_feature_ids: set[str] = Field(default_factory=set)
    current_road_segment_ids: set[str] = Field(default_factory=set)
    endpoint_entities: dict[str, RoadEndpointEvidence] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_current_network_role(self) -> "RoadEvidenceCatalog":
        if (
            self.current_network is not None
            and self.current_network.role != "current_road_network"
        ):
            raise ValueError("catalog current_network must use current_road_network role")
        return self


__all__ = [
    "ExistingRoadAction",
    "ExistingRoadPlanningInput",
    "NewCorridorPlanningInput",
    "RoadArtifactEvidence",
    "RoadCandidatePreparationBatch",
    "RoadCandidatePreparationResult",
    "RoadEndpointEvidence",
    "RoadEvidenceCatalog",
    "RoadPlanningInput",
    "RoadPlanningKind",
    "RoadPreparationDiagnostic",
    "RoadRoutingEvidence",
]
