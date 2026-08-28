"""Typed preflight evidence for the SELECT solver boundary."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta


ReadinessStatus = Literal[
    "ready",
    "pending",
    "blocked",
    "human_required",
    "not_groundable",
]
ReadinessSeverity = Literal["hard", "advisory"]


def _sorted_strings(values: list[str] | tuple[str, ...]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class ReadinessReason(BaseModel):
    """One explicit readiness reason with stable refs."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: ReadinessSeverity
    ref: str = ""
    source_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize(self) -> "ReadinessReason":
        self.code = self.code.strip()
        self.message = self.message.strip()
        self.ref = self.ref.strip()
        self.source_refs = _sorted_strings(self.source_refs)
        return self


class ReadinessDimension(BaseModel):
    """Typed readiness state for one solver prerequisite dimension."""

    model_config = ConfigDict(extra="forbid")

    status: ReadinessStatus
    blocker_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    reasons: list[ReadinessReason] = Field(default_factory=list)
    fingerprint: str = ""

    @model_validator(mode="after")
    def canonicalize_and_fingerprint(self) -> "ReadinessDimension":
        self.blocker_refs = _sorted_strings(self.blocker_refs)
        self.source_refs = _sorted_strings(self.source_refs)
        self.reasons = sorted(
            self.reasons,
            key=lambda item: (item.severity, item.code, item.ref, item.message),
        )
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        derived = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        if self.fingerprint and self.fingerprint != derived:
            raise ValueError("readiness dimension fingerprint does not match content")
        self.fingerprint = derived
        return self


class TargetReadiness(ReadinessDimension):
    target_ids: tuple[str, ...] = Field(default_factory=tuple)


class RelationReadiness(ReadinessDimension):
    relation_refs: tuple[str, ...] = Field(default_factory=tuple)


class DemandReadiness(ReadinessDimension):
    demand_refs: tuple[str, ...] = Field(default_factory=tuple)


class NetworkReadiness(ReadinessDimension):
    network_refs: tuple[str, ...] = Field(default_factory=tuple)


class CandidateReadiness(ReadinessDimension):
    candidate_refs: tuple[str, ...] = Field(default_factory=tuple)


class BackendReadiness(ReadinessDimension):
    backend_id: str = ""
    backend_version: str = ""
    problem_kind: str = ""


class SnapshotReadiness(ReadinessDimension):
    snapshot_refs: tuple[str, ...] = Field(default_factory=tuple)


class TaskGraphReadiness(ReadinessDimension):
    task_refs: tuple[str, ...] = Field(default_factory=tuple)


class SolverReadiness(ContractMeta):
    """Complete, replayable preflight result consumed by SELECT and gates."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    problem_fingerprint: str = ""
    status: ReadinessStatus
    target: TargetReadiness
    relation: RelationReadiness
    demand: DemandReadiness
    network: NetworkReadiness
    candidate: CandidateReadiness
    backend: BackendReadiness
    snapshot: SnapshotReadiness
    task_graph: TaskGraphReadiness
    blocker_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    advisories: list[ReadinessReason] = Field(default_factory=list)
    fingerprint: str = ""

    @model_validator(mode="after")
    def canonicalize_and_fingerprint(self) -> "SolverReadiness":
        self.blocker_refs = _sorted_strings(self.blocker_refs)
        self.source_refs = _sorted_strings(self.source_refs)
        self.advisories = sorted(
            self.advisories,
            key=lambda item: (item.code, item.ref, item.message),
        )
        payload = self.model_dump(mode="json", exclude={"fingerprint", "created_at"})
        derived = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        if self.fingerprint and self.fingerprint != derived:
            raise ValueError("solver readiness fingerprint does not match content")
        self.fingerprint = derived
        return self

    @property
    def ready(self) -> bool:
        return self.status == "ready" and not self.blocker_refs


SolverReadinessReport = SolverReadiness


__all__ = [
    "ReadinessStatus",
    "ReadinessSeverity",
    "ReadinessReason",
    "ReadinessDimension",
    "TargetReadiness",
    "RelationReadiness",
    "DemandReadiness",
    "NetworkReadiness",
    "CandidateReadiness",
    "BackendReadiness",
    "SnapshotReadiness",
    "TaskGraphReadiness",
    "SolverReadiness",
    "SolverReadinessReport",
]
