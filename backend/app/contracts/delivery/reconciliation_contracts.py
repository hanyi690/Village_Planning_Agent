from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.provenance import Provenance
from app.contracts.workflow.recovery_pointer import RecoveryPointer


class CoverageMatrixRow(BaseModel):
    target_id: str = ""
    target_type: str = ""
    expected_output_kind: Literal["parcel", "polygon", "point", "line", "multipatch", "action"] = "polygon"
    execution_task_id: str = ""
    output_artifacts: list[str] = Field(default_factory=list)
    intervention_id: str = ""
    spec_index: int | None = None
    candidate_site_id: str = ""
    selected_bsm: str = ""
    change_bsm: str = ""
    planned_parcel_bsm: str = ""
    status: Literal["covered", "partial", "missing", "deferred", "failed"] = "missing"


class CoverageMatrix(BaseModel):
    rows: list[CoverageMatrixRow] = Field(default_factory=list)


class ReconciliationInconsistency(BaseModel):
    intervention_id: str = ""
    field: str = ""
    expected: str = ""
    actual: str = ""
    severity: str = "warning"
    responsible_stage: Literal["L3", "GROUND", "SELECT", "EXECUTE", "VALIDATE"] = "EXECUTE"


class ReconcileGapRecord(BaseModel):
    gap_ref: str = ""
    reason_code: str
    status: Literal[
        "resolved",
        "accepted",
        "retry_required",
        "human_required",
    ]
    blocking: bool = True
    responsible_stage: str
    target_ref: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    recovery_pointer: RecoveryPointer | None = None

    @model_validator(mode="after")
    def derive_ref(self) -> "ReconcileGapRecord":
        if not self.gap_ref:
            payload = self.model_dump(mode="json", exclude={"gap_ref"})
            digest = hashlib.sha256(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.gap_ref = f"reconcile-gap:{digest[:24]}"
        return self


class FinalManifest(ContractMeta):
    """Authoritative RECONCILE manifest for the closed planning chain."""

    coverage_matrix: CoverageMatrix = Field(default_factory=CoverageMatrix)
    inconsistencies: list[ReconciliationInconsistency] = Field(default_factory=list)
    remaining_gaps: list[ReconcileGapRecord] = Field(default_factory=list)
    status: Literal["reconciled", "retry_required", "human_required"] = "reconciled"
    provenance: "Provenance | None" = None

    @property
    def can_deliver(self) -> bool:
        return self.status == "reconciled" and not any(
            item.blocking and item.status not in {"resolved", "accepted"}
            for item in self.remaining_gaps
        )

    @model_validator(mode="after")
    def canonicalize(self) -> "FinalManifest":
        self.remaining_gaps = sorted(
            self.remaining_gaps,
            key=lambda item: item.gap_ref,
        )
        if any(item.status == "human_required" for item in self.remaining_gaps):
            self.status = "human_required"
        elif any(item.status == "retry_required" for item in self.remaining_gaps):
            self.status = "retry_required"
        elif any(item.severity == "error" for item in self.inconsistencies):
            self.status = "human_required"
        else:
            self.status = "reconciled"
        return self


# The payload remains a reconciliation-shaped report internally, but the
# cross-stage artifact name is FinalManifest as defined by the target design.
ReconciliationReport = FinalManifest


__all__ = [
    "CoverageMatrixRow",
    "CoverageMatrix",
    "ReconciliationInconsistency",
    "ReconcileGapRecord",
    "FinalManifest",
    "ReconciliationReport",
]
