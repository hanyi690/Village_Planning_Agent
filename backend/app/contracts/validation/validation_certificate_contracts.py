"""Execution-to-validation certificate binding immutable outputs."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class ValidationCertificate(ContractMeta):
    """Proof that VALIDATE inspected one exact EXECUTE result."""

    schema_version: Literal["1.0"] = "1.0"
    certificate_id: str = Field(min_length=1)
    approved_input_ref: str = ""
    execution_result_ref: str = Field(min_length=1)
    planned_state_ref: str = ""
    parcel_changeset_ref: str = ""
    scenario_id: str = ""
    scenario_fingerprint: str = ""
    scenario_set_fingerprint: str = ""
    baseline_ref: str = ""
    planned_state_fingerprint: str = ""
    context_version: str = ""
    bundle_snapshot_digest: str = ""
    status: Literal["passed", "partial", "failed", "blocked"] = "blocked"
    check_ids: list[str] = Field(default_factory=list)
    passed_check_ids: list[str] = Field(default_factory=list)
    blocking_issue_codes: list[str] = Field(default_factory=list)
    issue_count: int = Field(default=0, ge=0)
    atomic_execution: bool = False
    hard_constraint_violation_count: int = Field(default=0, ge=0)
    unresolved_hard_constraint_count: int = Field(default=0, ge=0)
    selected_target_count: int = Field(default=0, ge=0)
    materialized_target_count: int = Field(default=0, ge=0)
    selected_target_ids: list[str] = Field(default_factory=list)
    materialized_target_ids: list[str] = Field(default_factory=list)
    lineage_complete: bool = True
    diagnostics: list[str] = Field(default_factory=list)
    fingerprint: str = ""

    @property
    def can_reconcile(self) -> bool:
        return self.status == "passed" and self.atomic_execution

    @model_validator(mode="after")
    def canonicalize_and_fingerprint(self) -> "ValidationCertificate":
        self.check_ids = sorted({item for item in self.check_ids if item})
        self.passed_check_ids = sorted({item for item in self.passed_check_ids if item})
        self.blocking_issue_codes = sorted({item for item in self.blocking_issue_codes if item})
        self.selected_target_ids = sorted({item for item in self.selected_target_ids if item})
        self.materialized_target_ids = sorted({item for item in self.materialized_target_ids if item})
        self.diagnostics = sorted({item for item in self.diagnostics if item})
        missing_target_ids = sorted(
            set(self.selected_target_ids) - set(self.materialized_target_ids)
        )
        if self.status == "passed" and (
            self.hard_constraint_violation_count
            or self.unresolved_hard_constraint_count
            or not self.lineage_complete
            or (
                self.selected_target_count
                and self.materialized_target_count != self.selected_target_count
            )
            or missing_target_ids
        ):
            raise ValueError("passed validation certificate contains blocking findings")
        if not self.fingerprint:
            payload = self.model_dump(mode="json", exclude={"fingerprint", "created_at"})
            self.fingerprint = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return self


__all__ = ["ValidationCertificate"]
