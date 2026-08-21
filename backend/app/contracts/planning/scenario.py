"""Immutable, auditable planning-scenario contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.planning.constraint_factor import RelationSatisfaction


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sorted_strings(values: list[str]) -> list[str]:
    return sorted({item for item in values if item})


class ScenarioFeature(BaseModel):
    feature_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    geometry_kind: Literal["point", "line", "polygon", "multipatch"]
    geometry_wkt: str = Field(min_length=1)
    crs: str = Field(min_length=1)
    generation_operation: str = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    source_bsms: list[str] = Field(default_factory=list)
    feature_bsms: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    l1_fact_refs: list[str] = Field(default_factory=list)
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""
    source_binding_ref: str = ""
    subgeometry_operation: str = "bundle_extent"
    subgeometry_diagnostics: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)

    @field_validator("source_refs")
    @classmethod
    def require_non_empty_source_refs(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("source_refs must contain non-empty references")
        return _sorted_strings(value)

    @field_validator("relation_ids")
    @classmethod
    def require_non_empty_relation_ids(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("relation_ids must contain non-empty references")
        return _sorted_strings(value)

    @field_validator(
        "source_bsms",
        "feature_bsms",
        "source_feature_ids",
        "entity_refs",
        "evidence_refs",
        "l1_fact_refs",
    )
    @classmethod
    def normalize_lineage_refs(cls, value: list[str]) -> list[str]:
        return _sorted_strings(value)

    @model_validator(mode="after")
    def migrate_legacy_relation_ids(self) -> "ScenarioFeature":
        """Give pre-lineage fixtures a deterministic auditable relation ref."""
        self.subgeometry_diagnostics = _sorted_strings(self.subgeometry_diagnostics)
        if not self.relation_ids:
            self.relation_ids = [f"feature:{self.feature_id}"]
        return self


class ScenarioFinding(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"] = "warning"
    message: str
    relation_id: str = ""
    target_id: str = ""


class ScenarioTargetSelection(BaseModel):
    """Authoritative selected members for one planning target."""

    target_id: str = Field(min_length=1)
    selection_mode: Literal["all_members", "choose_one", "choose_subset"]
    candidate_ids: list[str] = Field(min_length=1)
    binding_ref: str = ""

    @model_validator(mode="after")
    def canonicalize(self) -> "ScenarioTargetSelection":
        self.candidate_ids = sorted(set(item for item in self.candidate_ids if item))
        if not self.candidate_ids:
            raise ValueError("candidate_ids must contain at least one member")
        if self.selection_mode == "choose_one" and len(self.candidate_ids) != 1:
            raise ValueError("choose_one selection must contain exactly one candidate")
        return self


class PlanningScenario(ContractMeta):
    schema_version: Literal["1.0"] = "1.0"
    scenario_id: str
    parent_scenario_id: str = ""
    baseline_ref: str
    problem_fingerprint: str
    target_selections: list[ScenarioTargetSelection] = Field(default_factory=list)
    feature_intents: list[ScenarioFeature] = Field(default_factory=list)
    relation_satisfactions: list[RelationSatisfaction] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    findings: list[ScenarioFinding] = Field(default_factory=list)
    status: Literal["draft", "partial", "complete", "failed"] = "draft"
    fingerprint: str = ""

    @model_validator(mode="after")
    def validate_and_fingerprint(self) -> "PlanningScenario":
        if self.status == "complete":
            blocking = [
                item.relation_id
                for item in self.relation_satisfactions
                if item.criticality == "hard" and item.status != "satisfied"
            ]
            if blocking:
                raise ValueError(
                    "complete scenario has unsatisfied hard relations: "
                    + ", ".join(sorted(blocking))
                )
        invalid_features = [
            item.feature_id
            for item in self.feature_intents
            if item.scenario_id != self.scenario_id
        ]
        if invalid_features:
            raise ValueError(
                "scenario feature belongs to a different scenario: "
                + ", ".join(sorted(invalid_features))
            )
        self.target_selections = sorted(
            self.target_selections,
            key=lambda item: item.target_id,
        )
        selection_targets = [item.target_id for item in self.target_selections]
        if len(selection_targets) != len(set(selection_targets)):
            raise ValueError("target_selections must contain one row per target")
        self.feature_intents = sorted(self.feature_intents, key=lambda item: item.feature_id)
        self.relation_satisfactions = sorted(
            self.relation_satisfactions,
            key=lambda item: item.relation_id,
        )
        self.metrics = {
            str(key): float(value)
            for key, value in sorted(self.metrics.items(), key=lambda item: str(item[0]))
        }
        self.findings = sorted(
            self.findings,
            key=lambda item: (
                item.severity,
                item.code,
                item.relation_id,
                item.target_id,
                item.message,
            ),
        )
        if not self.fingerprint:
            payload = self.model_dump(mode="json", exclude={"fingerprint", "created_at"})
            raw = _canonical_json(payload).encode("utf-8")
            self.fingerprint = hashlib.sha256(raw).hexdigest()
        return self


__all__ = [
    "ScenarioFeature",
    "ScenarioFinding",
    "ScenarioTargetSelection",
    "PlanningScenario",
]
