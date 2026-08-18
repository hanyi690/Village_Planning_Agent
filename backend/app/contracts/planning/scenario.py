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
    relation_ids: list[str] = Field(min_length=1)

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


class ScenarioFinding(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"] = "warning"
    message: str
    relation_id: str = ""
    target_id: str = ""


class PlanningScenario(ContractMeta):
    schema_version: Literal["1.0"] = "1.0"
    scenario_id: str
    parent_scenario_id: str = ""
    baseline_ref: str
    problem_fingerprint: str
    selected_candidate_ids: dict[str, str] = Field(default_factory=dict)
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
        self.selected_candidate_ids = dict(sorted(self.selected_candidate_ids.items()))
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


__all__ = ["ScenarioFeature", "ScenarioFinding", "PlanningScenario"]
