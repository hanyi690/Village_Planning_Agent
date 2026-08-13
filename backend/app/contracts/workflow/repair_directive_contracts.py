"""Typed VALIDATE repair directives and artifact-impact decisions.

These contracts are the narrow bridge between deterministic validation and
stage workers.  They are not a second validation-report hierarchy: each
directive points back to one or more source violations and to the immutable
artifact checksum that contained those violations.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RepairDirectiveType(StrEnum):
    EXCLUDE_BSMS = "exclude_bsms"
    REALLOCATE = "reallocate"
    REBUILD_GEOMETRY = "rebuild_geometry"
    REQUIRE_SOURCE_EVIDENCE = "require_source_evidence"


class RepairEvidenceScope(StrEnum):
    TARGET_CONTRACT = "target_contract"
    GROUNDING = "grounding"


RepairStage = Literal[
    "L3",
    "TARGET_PROJECTION",
    "GROUND",
    "SELECT",
    "EXECUTE",
    "VALIDATE",
    "RECONCILE",
    "DELIVER",
]


def _require_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must be non-empty")
    return value


def _require_sha256(value: str) -> str:
    value = value.strip()
    if not value.startswith("sha256:") or len(value) != 71:
        raise ValueError("value must be a sha256:<64 hex chars> digest")
    int(value[7:], 16)
    return value


class RepairDirective(BaseModel):
    """One executable, target-bound adjustment request.

    Payload fields are deliberately closed.  There is no generic
    ``adjustment_type`` or ``relax`` metadata escape hatch.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    directive_id: str
    directive_type: RepairDirectiveType
    target_id: str
    source_violation_ids: list[str] = Field(min_length=1)
    source_artifact_key: str
    source_artifact_digest: str
    affected_bsms: list[str] = Field(default_factory=list)
    exclude_bsms: list[str] = Field(default_factory=list)
    evidence_scope: RepairEvidenceScope | None = None
    required_evidence: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    rebuild_strategy: Literal[
        "repair_invalid_geometry",
        "rebuild_from_authoritative_assignments",
        "reroute_avoiding_bsms",
    ] | None = None
    reason_code: str = ""
    issue_fingerprint: str

    @field_validator(
        "directive_id",
        "target_id",
        "source_artifact_key",
        "reason_code",
    )
    @classmethod
    def require_identity(cls, value: str) -> str:
        return _require_text(value)

    @field_validator("source_artifact_digest", "issue_fingerprint")
    @classmethod
    def require_digest(cls, value: str) -> str:
        return _require_sha256(value)

    @field_validator(
        "source_violation_ids",
        "affected_bsms",
        "exclude_bsms",
        "required_evidence",
        "evidence_refs",
    )
    @classmethod
    def normalize_unique_values(cls, values: list[str]) -> list[str]:
        normalized = sorted({_require_text(str(value)) for value in values})
        return normalized

    @model_validator(mode="after")
    def validate_typed_payload(self) -> "RepairDirective":
        if self.directive_type == RepairDirectiveType.EXCLUDE_BSMS:
            if not self.exclude_bsms:
                raise ValueError("exclude_bsms directive requires explicit BSMs")
            if self.evidence_scope is not None or self.required_evidence:
                raise ValueError("exclude_bsms cannot carry an evidence request")
        elif self.directive_type == RepairDirectiveType.REALLOCATE:
            if not self.affected_bsms:
                raise ValueError("reallocate directive requires conflict BSMs")
            if self.exclude_bsms or self.evidence_scope is not None or self.required_evidence:
                raise ValueError("reallocate carries only target/conflict lineage")
        elif self.directive_type == RepairDirectiveType.REBUILD_GEOMETRY:
            if not self.affected_bsms and not self.evidence_refs:
                raise ValueError("rebuild_geometry requires BSM or geometry evidence lineage")
            if self.rebuild_strategy is None:
                raise ValueError("rebuild_geometry requires an explicit rebuild strategy")
            if self.exclude_bsms or self.evidence_scope is not None or self.required_evidence:
                raise ValueError("rebuild_geometry cannot carry another directive payload")
        elif self.directive_type == RepairDirectiveType.REQUIRE_SOURCE_EVIDENCE:
            if self.evidence_scope is None or not self.required_evidence:
                raise ValueError("require_source_evidence requires a typed scope and requirements")
            if self.exclude_bsms:
                raise ValueError("missing evidence cannot be represented as a parcel exclusion")
            if self.rebuild_strategy is not None:
                raise ValueError("source evidence request cannot carry rebuild parameters")
        elif self.rebuild_strategy is not None:
            raise ValueError("only rebuild_geometry may carry rebuild parameters")
        return self


class UnresolvedRepairViolation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    violation_id: str
    code: str
    target_ids: list[str] = Field(default_factory=list)
    affected_bsms: list[str] = Field(default_factory=list)
    reason_code: Literal[
        "invalid_source_artifact",
        "missing_target_lineage",
        "missing_bsm_lineage",
        "unsupported_violation",
        "invalid_violation",
    ]
    message: str


class RepairDirectiveCompilation(BaseModel):
    """All-or-nothing compilation result for one validation snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready", "blocked", "noop"]
    directives: list[RepairDirective] = Field(default_factory=list)
    unresolved: list[UnresolvedRepairViolation] = Field(default_factory=list)
    source_checksums: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_status(self) -> "RepairDirectiveCompilation":
        if self.status == "ready" and (not self.directives or self.unresolved):
            raise ValueError("ready compilation requires directives and no unresolved violations")
        if self.status == "blocked" and (self.directives or not self.unresolved):
            raise ValueError("blocked compilation must fail closed without executable directives")
        if self.status == "noop" and (self.directives or self.unresolved):
            raise ValueError("noop compilation cannot contain repair work")
        return self


class ArtifactIntegrityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_key: str
    artifact_stage: str
    code: Literal[
        "invalid_artifact_ref",
        "missing_parent_artifact",
        "parent_checksum_mismatch",
        "missing_parent_lineage",
        "missing_upstream_anchor",
        "source_violation_checksum_changed",
    ]
    parent_key: str | None = None
    expected_checksum: str = ""
    actual_checksum: str = ""
    message: str


class RepairImpactPlan(BaseModel):
    """Conservative replay boundary derived from directives and CAS lineage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready", "blocked", "noop"]
    earliest_invalid_stage: RepairStage | None = None
    rerun_stages: list[RepairStage] = Field(default_factory=list)
    reusable_artifact_keys: list[str] = Field(default_factory=list)
    invalidated_artifact_keys: list[str] = Field(default_factory=list)
    affected_target_ids: list[str] = Field(default_factory=list)
    directive_ids: list[str] = Field(default_factory=list)
    artifact_checksums: dict[str, str] = Field(default_factory=dict)
    integrity_issues: list[ArtifactIntegrityIssue] = Field(default_factory=list)
    reason: str

    @model_validator(mode="after")
    def validate_status(self) -> "RepairImpactPlan":
        if self.status == "ready" and (
            self.earliest_invalid_stage is None or not self.rerun_stages or not self.directive_ids
        ):
            raise ValueError("ready impact requires a replay boundary and directives")
        if self.status == "blocked" and (self.earliest_invalid_stage is not None or self.rerun_stages):
            raise ValueError("blocked impact cannot advertise an executable replay")
        if self.status == "noop" and (self.earliest_invalid_stage is not None or self.rerun_stages):
            raise ValueError("noop impact cannot advertise an executable replay")
        return self


__all__ = [
    "ArtifactIntegrityIssue",
    "RepairDirective",
    "RepairDirectiveCompilation",
    "RepairDirectiveType",
    "RepairEvidenceScope",
    "RepairImpactPlan",
    "RepairStage",
    "UnresolvedRepairViolation",
]
