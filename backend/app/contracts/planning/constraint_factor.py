"""Closed-set constraint and relation evaluation contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.planning.relation_parameters import RelationParameters


ConstraintFactorKind = Literal[
    "within_allowed_area",
    "avoid_constraint",
    "near",
    "serve",
    "provide_access",
    "connect_network",
    "follow_alignment",
    "preserve_existing",
    "upgrade_existing",
    "part_of",
    "co_locate",
    "mutually_exclusive",
    "precedes",
    "contains",
    "located_in",
    "adjacent_to",
    "intersects",
    "overlaps",
]
ConstraintStatus = Literal[
    "pending",
    "satisfied",
    "partially_satisfied",
    "violated",
    "not_evaluable",
    "deferred",
    "unknown",
]

MeasurementScalar = float | int | bool | str | None
MeasurementOperator = Literal[
    "lt", "lte", "eq", "gte", "gt", "contains", "connected"
]


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sorted_strings(values: list[str]) -> list[str]:
    return sorted({item for item in values if item})


def _parameter_network_ref(parameters: RelationParameters | None) -> str:
    if parameters is None:
        return ""
    return str(getattr(parameters, "network_ref", "") or "")


def _factor_payload(model: "ConstraintFactor") -> dict[str, object]:
    return {
        "kind": model.kind,
        "subject_ref": model.subject_ref,
        "object_ref": model.object_ref,
        "object_ref_kind": model.object_ref_kind,
        "hard": model.hard,
        "evaluator_key": model.evaluator_key,
        "parameters": (
            model.parameters.model_dump(mode="json")
            if model.parameters is not None
            else None
        ),
        "subject_candidate_domain_refs": model.subject_candidate_domain_refs,
        "object_candidate_domain_refs": model.object_candidate_domain_refs,
        "subject_candidate_refs": model.subject_candidate_refs,
        "object_candidate_refs": model.object_candidate_refs,
        "network_refs": model.network_refs,
        "geometry_scope": model.geometry_scope,
        "weight": model.weight,
    }


class RelationMeasurement(BaseModel):
    value: MeasurementScalar = None
    unit: str = ""
    threshold: MeasurementScalar = None
    operator: MeasurementOperator
    method: str = Field(min_length=1)
    crs: str = ""
    network_ref: str = ""


class ConstraintFactor(BaseModel):
    """One executable planning relation backed by source evidence."""

    schema_version: Literal["2.0"] = "2.0"
    factor_id: str = ""
    kind: ConstraintFactorKind
    subject_ref: str = ""
    object_ref: str = ""
    object_ref_kind: Literal["target", "entity", "place_hint", "constraint"] = "target"
    hard: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)
    status: ConstraintStatus = "unknown"
    detail: str = ""
    evaluator_key: str = ""
    evaluator_version: str = ""
    required_refs: list[str] = Field(default_factory=list)
    source_snapshot_refs: list[str] = Field(default_factory=list)
    semantic_status: Literal["valid", "pending", "invalid"] = "valid"
    input_status: Literal["ready", "pending", "missing", "not_evaluable"] = "ready"
    solver_supported: bool | None = None
    parameters: RelationParameters | None = None
    subject_candidate_domain_refs: list[str] = Field(default_factory=list)
    object_candidate_domain_refs: list[str] = Field(default_factory=list)
    subject_candidate_refs: list[str] = Field(default_factory=list)
    object_candidate_refs: list[str] = Field(default_factory=list)
    network_refs: list[str] = Field(default_factory=list)
    weight: float = Field(default=1.0, ge=0)
    geometry_scope: Literal["subject", "object", "pair", "network", "global"] = "pair"

    @model_validator(mode="after")
    def canonicalize_and_derive_id(self) -> "ConstraintFactor":
        self.evidence_refs = _sorted_strings(self.evidence_refs)
        self.claim_refs = _sorted_strings(self.claim_refs)
        self.subject_candidate_domain_refs = _sorted_strings(
            self.subject_candidate_domain_refs
        )
        self.object_candidate_domain_refs = _sorted_strings(
            self.object_candidate_domain_refs
        )
        self.subject_candidate_refs = _sorted_strings(self.subject_candidate_refs)
        self.object_candidate_refs = _sorted_strings(self.object_candidate_refs)
        self.required_refs = _sorted_strings(self.required_refs)
        self.source_snapshot_refs = _sorted_strings(self.source_snapshot_refs)

        if not self.subject_candidate_domain_refs and self.subject_candidate_refs:
            self.subject_candidate_domain_refs = list(self.subject_candidate_refs)
        if not self.object_candidate_domain_refs and self.object_candidate_refs:
            self.object_candidate_domain_refs = list(self.object_candidate_refs)

        network_refs = set(self.network_refs)
        parameter_network_ref = _parameter_network_ref(self.parameters)
        if parameter_network_ref:
            network_refs.add(parameter_network_ref)
        self.network_refs = sorted(network_refs)

        if not self.factor_id:
            digest = hashlib.sha256(
                _canonical_json(_factor_payload(self)).encode("utf-8")
            ).hexdigest()
            self.factor_id = f"factor:{digest[:24]}"
        return self


class RelationSatisfaction(BaseModel):
    """Evaluation row kept separate from the relation declaration."""

    schema_version: Literal["2.0"] = "2.0"
    relation_id: str
    scenario_id: str = ""
    subject_ref: str
    object_ref: str = ""
    status: ConstraintStatus = "unknown"
    evidence_refs: list[str] = Field(default_factory=list)
    factor_ids: list[str] = Field(default_factory=list)
    detail: str = ""
    score: float = 0.0
    criticality: Literal["hard", "soft", "informational"] = "soft"
    subject_feature_refs: list[str] = Field(default_factory=list)
    object_feature_refs: list[str] = Field(default_factory=list)
    measurement: RelationMeasurement | None = None
    evaluation_trace: list[str] = Field(default_factory=list)
    evaluator_version: str = ""
    evaluator_key: str = ""
    source_snapshot_refs: list[str] = Field(default_factory=list)
    input_status: Literal["ready", "pending", "missing", "not_evaluable"] = "ready"

    @model_validator(mode="after")
    def canonicalize_collections(self) -> "RelationSatisfaction":
        self.evidence_refs = _sorted_strings(self.evidence_refs)
        self.factor_ids = _sorted_strings(self.factor_ids)
        self.subject_feature_refs = _sorted_strings(self.subject_feature_refs)
        self.object_feature_refs = _sorted_strings(self.object_feature_refs)
        self.evaluation_trace = sorted(
            [item for item in self.evaluation_trace if item],
            key=lambda item: item,
        )
        self.source_snapshot_refs = _sorted_strings(self.source_snapshot_refs)
        return self


__all__ = [
    "ConstraintFactorKind",
    "ConstraintStatus",
    "ConstraintFactor",
    "RelationMeasurement",
    "RelationSatisfaction",
]
