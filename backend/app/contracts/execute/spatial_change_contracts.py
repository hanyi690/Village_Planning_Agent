"""Generic spatial execution output contracts.

The planning pipeline operates on arbitrary DATA/KG representations.  A
``SpatialChangeSet`` therefore carries immutable ``ScenarioFeature`` rows and
operation lineage without requiring a cadastral BSM.  ParcelChangeSet remains
the compatibility contract for explicit land-use/BSM workflows.
"""

from __future__ import annotations

from typing import Any, Literal

import hashlib

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.select.scenario import ScenarioFeature


class SpatialChangeOperation(BaseModel):
    """One approval-bound geometry result with complete DATA lineage."""

    model_config = ConfigDict(extra="forbid")

    change_ref: str = Field(min_length=1)
    feature_id: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    candidate_ref: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    input_operation: str = Field(min_length=1)
    operation_parameters: dict[str, Any] = Field(default_factory=dict)
    input_resource_refs: list[str] = Field(min_length=1)
    input_representation_refs: list[str] = Field(min_length=1)
    input_geometry_refs: list[str] = Field(min_length=1)
    source_snapshot_refs: list[str] = Field(min_length=1)
    resource_digests: list[str] = Field(min_length=1)
    capability_refs: list[str] = Field(min_length=1)
    selection_refs: list[str] = Field(min_length=1)
    approval_ref: str = Field(min_length=1)
    world_model_digest: str = Field(min_length=1)
    input_crs: str = Field(min_length=1)
    output_crs: str = Field(min_length=1)
    geometry_kind: str = Field(min_length=1)
    geometry_digest: str = Field(min_length=1)

    @model_validator(mode="after")
    def canonicalize(self) -> "SpatialChangeOperation":
        for name in (
            "input_resource_refs",
            "input_representation_refs",
            "input_geometry_refs",
            "source_snapshot_refs",
            "resource_digests",
            "capability_refs",
            "selection_refs",
        ):
            values = sorted({str(item) for item in getattr(self, name) if str(item).strip()})
            if not values:
                raise ValueError(f"{name} must contain complete execution lineage")
            if name in {"input_resource_refs", "input_representation_refs", "input_geometry_refs"} and any(
                item.startswith("external-observation:") for item in values
            ):
                raise ValueError("external observations cannot be execution inputs")
            setattr(self, name, values)
        return self


class SpatialChangeSet(ContractMeta):
    """Authoritative generic geometry output from EXECUTE."""

    schema_version: Literal["1.0"] = "1.0"
    features: list[ScenarioFeature] = Field(default_factory=list)
    operations: list[SpatialChangeOperation] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    scenario_id: str = ""
    scenario_ref: str = ""

    @model_validator(mode="after")
    def canonicalize(self) -> "SpatialChangeSet":
        seen: set[str] = set()
        unique: list[ScenarioFeature] = []
        for feature in self.features:
            if feature.feature_id in seen:
                raise ValueError(
                    f"duplicate generic spatial feature_id: {feature.feature_id}"
                )
            seen.add(feature.feature_id)
            unique.append(feature)
        for operation in self.operations:
            feature_id = str(operation.feature_id or "").strip()
            if not feature_id:
                raise ValueError("generic spatial operation requires feature_id")
            if feature_id not in seen:
                raise ValueError(
                    f"generic spatial operation references unknown feature: {feature_id}"
                )
        if self.features and len(self.operations) != len(self.features):
            raise ValueError(
                "generic spatial changes require exactly one operation per feature"
            )
        operation_feature_ids = [item.feature_id for item in self.operations]
        if len(operation_feature_ids) != len(set(operation_feature_ids)):
            raise ValueError("generic spatial feature has multiple change operations")
        operation_by_feature = {item.feature_id: item for item in self.operations}
        scenario_ids = {str(item.scenario_id or "") for item in self.features}
        if "" in scenario_ids or len(scenario_ids) > 1:
            raise ValueError("generic spatial changes require one non-empty scenario_id")
        for feature in self.features:
            operation = operation_by_feature.get(feature.feature_id)
            if operation is None:
                raise ValueError(
                    f"generic spatial feature lacks operation lineage: {feature.feature_id}"
                )
            required_feature_fields = {
                "change_ref": feature.change_ref,
                "approval_ref": feature.approval_ref,
                "world_model_digest": feature.world_model_digest,
                "input_operation": feature.input_operation,
                "input_crs": feature.input_crs,
                "output_crs": feature.output_crs,
                "geometry_digest": feature.geometry_digest,
                "part_ref": feature.part_ref,
            }
            missing = [name for name, value in required_feature_fields.items() if not str(value or "").strip()]
            for name in (
                "resource_refs",
                "representation_refs",
                "input_geometry_refs",
                "source_snapshot_refs",
                "resource_digests",
                "capability_refs",
                "selection_refs",
            ):
                if not list(getattr(feature, name, None) or []):
                    missing.append(name)
            if missing:
                raise ValueError(
                    f"generic spatial feature lineage incomplete ({feature.feature_id}): "
                    + ", ".join(sorted(set(missing)))
                )
            try:
                from shapely import wkt

                geometry = wkt.loads(feature.geometry_wkt)
            except Exception as exc:
                raise ValueError(
                    f"generic spatial feature WKT is not loadable: {feature.feature_id}"
                ) from exc
            if geometry.is_empty or not geometry.is_valid:
                raise ValueError(
                    f"generic spatial feature geometry is empty or invalid: {feature.feature_id}"
                )
            actual_kind = {
                "point": "point",
                "multipoint": "point",
                "linestring": "line",
                "multilinestring": "line",
                "polygon": "polygon",
                "multipolygon": "polygon",
            }.get(str(geometry.geom_type or "").casefold(), "unknown")
            if actual_kind != feature.geometry_kind:
                raise ValueError(
                    f"generic spatial feature kind mismatch: {feature.feature_id}"
                )
            actual_digest = "sha256:" + hashlib.sha256(
                feature.geometry_wkt.encode("utf-8")
            ).hexdigest()
            if feature.geometry_digest != actual_digest:
                raise ValueError(
                    f"generic spatial feature digest mismatch: {feature.feature_id}"
                )
            exact_pairs = {
                "change_ref": (feature.change_ref, operation.change_ref),
                "target_ref": (feature.target_id, operation.target_ref),
                "candidate_ref": (feature.candidate_id, operation.candidate_ref),
                "input_operation": (feature.input_operation, operation.input_operation),
                "approval_ref": (feature.approval_ref, operation.approval_ref),
                "world_model_digest": (feature.world_model_digest, operation.world_model_digest),
                "input_crs": (feature.input_crs, operation.input_crs),
                "output_crs": (feature.output_crs, operation.output_crs),
                "geometry_kind": (feature.geometry_kind, operation.geometry_kind),
                "geometry_digest": (feature.geometry_digest, operation.geometry_digest),
            }
            drift = [name for name, pair in exact_pairs.items() if pair[0] != pair[1]]
            if drift:
                raise ValueError(
                    f"generic spatial operation drift ({feature.feature_id}): "
                    + ", ".join(drift)
                )
        self.scenario_id = self.scenario_id or next(iter(scenario_ids), "")
        if self.scenario_id and self.scenario_id not in scenario_ids:
            raise ValueError("SpatialChangeSet scenario_id does not match features")
        self.features = unique
        self.operations = sorted(self.operations, key=lambda item: item.change_ref)
        self.source_refs = sorted({str(item) for item in self.source_refs if str(item).strip()})
        self.evidence_refs = sorted({str(item) for item in self.evidence_refs if str(item).strip()})
        return self


class PlannedEntity(BaseModel):
    """One planned world object, distinct from its geometry representation."""

    model_config = ConfigDict(extra="forbid")

    planned_entity_ref: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    candidate_ref: str = Field(min_length=1)
    source_entity_ref: str = Field(min_length=1)
    part_ref: str = Field(min_length=1)
    representation_refs: list[str] = Field(min_length=1)
    status: Literal["planned"] = "planned"

    @model_validator(mode="after")
    def canonicalize(self) -> "PlannedEntity":
        self.representation_refs = sorted({
            str(item) for item in self.representation_refs if str(item).strip()
        })
        if not self.representation_refs:
            raise ValueError("planned entity requires a planned representation")
        return self


class PlannedEntitySet(ContractMeta):
    schema_version: Literal["1.0"] = "1.0"
    scenario_id: str = Field(min_length=1)
    entities: list[PlannedEntity] = Field(min_length=1)

    @model_validator(mode="after")
    def canonicalize(self) -> "PlannedEntitySet":
        refs = [item.planned_entity_ref for item in self.entities]
        if len(refs) != len(set(refs)):
            raise ValueError("planned entity refs must be unique")
        if any(item.scenario_id != self.scenario_id for item in self.entities):
            raise ValueError("planned entity scenario mismatch")
        self.entities = sorted(self.entities, key=lambda item: item.planned_entity_ref)
        return self


class PlannedRepresentation(BaseModel):
    """The exact executable geometry view owned by one planned entity."""

    model_config = ConfigDict(extra="forbid")

    planned_representation_ref: str = Field(min_length=1)
    planned_entity_ref: str = Field(min_length=1)
    feature_id: str = Field(min_length=1)
    change_ref: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    candidate_ref: str = Field(min_length=1)
    part_ref: str = Field(min_length=1)
    geometry_kind: Literal["point", "line", "polygon", "multipatch"]
    geometry_wkt: str = Field(min_length=1)
    input_crs: str = Field(min_length=1)
    output_crs: str = Field(min_length=1)
    geometry_digest: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    operation_parameters: dict[str, Any] = Field(default_factory=dict)
    input_resource_refs: list[str] = Field(min_length=1)
    input_representation_refs: list[str] = Field(min_length=1)
    input_geometry_refs: list[str] = Field(min_length=1)
    source_snapshot_refs: list[str] = Field(min_length=1)
    resource_digests: list[str] = Field(min_length=1)
    capability_refs: list[str] = Field(min_length=1)
    selection_refs: list[str] = Field(min_length=1)
    approval_ref: str = Field(min_length=1)
    world_model_digest: str = Field(min_length=1)


class PlannedRepresentationSet(ContractMeta):
    schema_version: Literal["1.0"] = "1.0"
    scenario_id: str = Field(min_length=1)
    representations: list[PlannedRepresentation] = Field(min_length=1)

    @model_validator(mode="after")
    def canonicalize(self) -> "PlannedRepresentationSet":
        refs = [item.planned_representation_ref for item in self.representations]
        features = [item.feature_id for item in self.representations]
        if len(refs) != len(set(refs)) or len(features) != len(set(features)):
            raise ValueError("planned representation identity must be one-to-one")
        self.representations = sorted(
            self.representations,
            key=lambda item: item.planned_representation_ref,
        )
        return self


class ExecutionTrace(ContractMeta):
    """Replayable operation trace projected from the committed change set."""

    schema_version: Literal["1.0"] = "1.0"
    trace_ref: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    operations: list[SpatialChangeOperation] = Field(min_length=1)
    planned_entity_refs: list[str] = Field(min_length=1)
    planned_representation_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def canonicalize(self) -> "ExecutionTrace":
        self.operations = sorted(self.operations, key=lambda item: item.change_ref)
        self.planned_entity_refs = sorted({
            str(item) for item in self.planned_entity_refs if str(item).strip()
        })
        self.planned_representation_refs = sorted({
            str(item)
            for item in self.planned_representation_refs
            if str(item).strip()
        })
        if (
            len(self.operations) != len(self.planned_representation_refs)
            or not self.planned_entity_refs
        ):
            raise ValueError("execution trace does not cover planned spatial outputs")
        return self


__all__ = [
    "SpatialChangeOperation",
    "SpatialChangeSet",
    "PlannedEntity",
    "PlannedEntitySet",
    "PlannedRepresentation",
    "PlannedRepresentationSet",
    "ExecutionTrace",
]
