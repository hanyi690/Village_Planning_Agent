"""Typed parameters for the closed planning-relation vocabulary.

Relation parameters are deliberately separate from relation declarations.  A
relation without parameters can be carried as a pending grounding item, but it
is not executable until a matching typed model is supplied.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RelationParameterBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parameter_version: Literal["1.0"] = "1.0"


class EmptyRelationParameters(RelationParameterBase):
    parameter_type: Literal["empty"] = "empty"


class AllowedAreaParameters(RelationParameterBase):
    parameter_type: Literal["allowed_area"] = "allowed_area"
    area_refs: list[str] = Field(min_length=1)


class AvoidConstraintParameters(RelationParameterBase):
    parameter_type: Literal["avoid_constraint"] = "avoid_constraint"
    constraint_refs: list[str] = Field(min_length=1)
    # Linear constraints such as roads, rivers and control lines are
    # evaluated as a metric exclusion corridor when a setback is declared.
    buffer_m: float = Field(default=0.0, ge=0)


class DistanceParameters(RelationParameterBase):
    parameter_type: Literal["distance"] = "distance"
    max_distance_m: float = Field(gt=0)
    metric: Literal["euclidean", "network"]
    network_ref: str = ""

    @model_validator(mode="after")
    def network_requires_reference(self) -> "DistanceParameters":
        if self.metric == "network" and not self.network_ref:
            raise ValueError("network distance requires network_ref")
        return self


class ServiceParameters(RelationParameterBase):
    parameter_type: Literal["service"] = "service"
    demand_ref: str = Field(min_length=1)
    facility_type: str = Field(min_length=1)
    max_travel_time_min: float = Field(gt=0)
    min_coverage_ratio: float = Field(ge=0, le=1)
    capacity: float = Field(gt=0)
    capacity_unit: str = Field(min_length=1)
    network_ref: str = Field(min_length=1)


class AccessParameters(RelationParameterBase):
    parameter_type: Literal["access"] = "access"
    max_travel_time_min: float = Field(gt=0)
    network_ref: str = Field(min_length=1)
    mode: Literal["walk", "road", "transit", "mixed"] = "road"


class ConnectParameters(RelationParameterBase):
    parameter_type: Literal["connect"] = "connect"
    network_kind: Literal["road", "water", "sewer", "drainage", "power", "generic"]
    endpoint_tolerance_m: float = Field(gt=0)
    network_ref: str = Field(min_length=1)


class FollowAlignmentParameters(RelationParameterBase):
    parameter_type: Literal["alignment"] = "alignment"
    alignment_ref: str = Field(min_length=1)
    max_deviation_m: float = Field(gt=0)


class ExistingAssetParameters(RelationParameterBase):
    parameter_type: Literal["existing_asset"] = "existing_asset"
    existing_ref: str = Field(min_length=1)


class PartOfParameters(RelationParameterBase):
    parameter_type: Literal["part_of"] = "part_of"
    parent_ref: str = Field(min_length=1)


class CoLocateParameters(RelationParameterBase):
    parameter_type: Literal["co_locate"] = "co_locate"
    max_distance_m: float = Field(gt=0)


class MutuallyExclusiveParameters(RelationParameterBase):
    parameter_type: Literal["mutually_exclusive"] = "mutually_exclusive"
    scope_ref: str = ""


class PrecedesParameters(RelationParameterBase):
    parameter_type: Literal["precedes"] = "precedes"
    required_event: Literal["start", "complete"] = "complete"


RelationParameters = Annotated[
    Union[
        EmptyRelationParameters,
        AllowedAreaParameters,
        AvoidConstraintParameters,
        DistanceParameters,
        ServiceParameters,
        AccessParameters,
        ConnectParameters,
        FollowAlignmentParameters,
        ExistingAssetParameters,
        PartOfParameters,
        CoLocateParameters,
        MutuallyExclusiveParameters,
        PrecedesParameters,
    ],
    Field(discriminator="parameter_type"),
]


_TEMPLATE_PARAMETER_TYPES: dict[str, frozenset[str]] = {
    "within_allowed_area": frozenset({"allowed_area"}),
    "avoid_constraint": frozenset({"avoid_constraint"}),
    "near": frozenset({"distance", "co_locate"}),
    "serve": frozenset({"service"}),
    "provide_access": frozenset({"access"}),
    "connect_network": frozenset({"connect"}),
    "follow_alignment": frozenset({"alignment"}),
    "preserve_existing": frozenset({"existing_asset"}),
    "upgrade_existing": frozenset({"existing_asset"}),
    "part_of": frozenset({"part_of"}),
    "co_locate": frozenset({"co_locate", "distance"}),
    "mutually_exclusive": frozenset({"mutually_exclusive"}),
    "precedes": frozenset({"precedes"}),
    "contains": frozenset({"empty"}),
    "located_in": frozenset({"empty"}),
    "adjacent_to": frozenset({"empty"}),
    "intersects": frozenset({"empty"}),
    "overlaps": frozenset({"empty"}),
}


def parameter_matches_template(relation_template: str, parameters: RelationParameters) -> bool:
    """Return whether typed parameters are valid for a relation template."""

    return parameters.parameter_type in _TEMPLATE_PARAMETER_TYPES.get(
        relation_template, frozenset()
    )


__all__ = [
    "RelationParameterBase",
    "EmptyRelationParameters",
    "AllowedAreaParameters",
    "AvoidConstraintParameters",
    "DistanceParameters",
    "ServiceParameters",
    "AccessParameters",
    "ConnectParameters",
    "FollowAlignmentParameters",
    "ExistingAssetParameters",
    "PartOfParameters",
    "CoLocateParameters",
    "MutuallyExclusiveParameters",
    "PrecedesParameters",
    "RelationParameters",
    "parameter_matches_template",
]
