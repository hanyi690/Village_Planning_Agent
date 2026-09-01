"""Generic resource selection contract owned by SELECT.

The scenario solver may still expose parcel-compatible candidate ids, but the
execution boundary consumes this resource decision instead of a BSM-shaped
allocation row.  All geometry/resource refs are lineage only; EXECUTE resolves
the actual payload through the DATA catalog.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SelectionDecision(BaseModel):
    """One approved or rejected resource operation for a planning target."""

    model_config = ConfigDict(extra="forbid")

    selection_ref: str = Field(min_length=1)
    candidate_ref: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    entity_ref: str = ""
    part_ref: str = ""
    representation_ref: str = ""
    resource_ref: str = ""
    geometry_ref: str = ""
    input_geometry_kind: str = ""
    geometry_kind: Literal["point", "line", "polygon", "multipatch"] | str = ""
    operation: str = "select"
    operation_parameters: dict[str, Any] = Field(default_factory=dict)
    input_crs: str = ""
    output_crs: str = ""
    source_snapshot_ref: str = ""
    resource_digest: str = ""
    capability_ref: str = ""
    constraint_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    hard_constraint_status: Literal["passed", "failed", "pending", "deferred", "unknown"] = "unknown"
    availability_status: Literal[
        "fully_available",
        "partially_available",
        "fully_unavailable",
        "unknown",
    ] = "unknown"
    status: Literal["selected", "rejected", "deferred", "ambiguous"] = "selected"
    rejection_reason: str = ""
    required_capability: str = "read"
    decision_digest: str = ""

    @model_validator(mode="after")
    def canonicalize(self) -> "SelectionDecision":
        self.operation = str(self.operation or "select").strip() or "select"
        self.required_capability = str(self.required_capability or "read").strip() or "read"
        self.input_geometry_kind = str(self.input_geometry_kind or self.geometry_kind or "").strip().casefold()
        self.geometry_kind = str(self.geometry_kind or "").strip().casefold()
        self.output_crs = str(self.output_crs or self.input_crs or "").strip()
        self.constraint_refs = sorted({str(item) for item in self.constraint_refs if str(item).strip()})
        self.evidence_refs = sorted({str(item) for item in self.evidence_refs if str(item).strip()})
        spatial_refs = {
            field_name: str(getattr(self, field_name) or "").strip()
            for field_name in ("resource_ref", "representation_ref", "geometry_ref")
        }
        observation_refs = [
            f"{field_name}={value}"
            for field_name, value in spatial_refs.items()
            if value.startswith("external-observation:")
            or ":external-observation:" in value
        ]
        if observation_refs:
            raise ValueError(
                "external observations are evidence-only and cannot be selected as "
                + ", ".join(observation_refs)
            )
        if self.status == "selected":
            required = {
                "entity_ref": self.entity_ref,
                "part_ref": self.part_ref,
                "representation_ref": self.representation_ref,
                "resource_ref": self.resource_ref,
                "geometry_ref": self.geometry_ref,
                "input_geometry_kind": self.input_geometry_kind,
                "geometry_kind": self.geometry_kind,
                "input_crs": self.input_crs,
                "output_crs": self.output_crs,
                "source_snapshot_ref": self.source_snapshot_ref,
                "resource_digest": self.resource_digest,
                "capability_ref": self.capability_ref,
            }
            missing = [name for name, value in required.items() if not str(value).strip()]
            if not self.evidence_refs:
                missing.append("evidence_refs")
            if missing:
                raise ValueError(
                    "selected decision requires a complete DATA/KG binding: "
                    + ", ".join(missing)
                )
            if self.geometry_kind not in {"point", "line", "polygon", "multipatch"}:
                raise ValueError("selected decision requires a supported geometry_kind")
            if self.hard_constraint_status != "passed":
                raise ValueError("selected decision requires passed hard constraints")
            if self.availability_status not in {"fully_available", "partially_available"}:
                raise ValueError("selected decision requires resolved availability")
        if not self.decision_digest:
            payload = self.model_dump(mode="json", exclude={"decision_digest"})
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            self.decision_digest = "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self


class SelectionDecisionSet(BaseModel):
    """Frozen SELECT output consumed and revalidated by EXECUTE."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    decision_set_ref: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    scenario_fingerprint: str = Field(min_length=1)
    data_snapshot_ref: str = Field(min_length=1)
    data_catalog_digest: str = Field(min_length=1)
    decisions: list[SelectionDecision] = Field(min_length=1)
    decision_set_digest: str = ""

    @model_validator(mode="after")
    def canonicalize(self) -> "SelectionDecisionSet":
        self.decisions = sorted(
            self.decisions,
            key=lambda item: (item.target_ref, item.candidate_ref, item.selection_ref),
        )
        refs = [item.selection_ref for item in self.decisions]
        if len(refs) != len(set(refs)):
            raise ValueError("selection decision refs must be unique")
        if any(item.status != "selected" for item in self.decisions):
            raise ValueError("SelectionDecisionSet only contains executable selected rows")
        payload = self.model_dump(mode="json", exclude={"decision_set_digest"})
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if self.decision_set_digest and self.decision_set_digest != digest:
            raise ValueError("selection decision set digest does not match content")
        self.decision_set_digest = digest
        return self


__all__ = ["SelectionDecision", "SelectionDecisionSet"]
