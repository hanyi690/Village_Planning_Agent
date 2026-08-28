from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.provenance import Provenance


class CoverageMatrixRow(BaseModel):
    target_id: str = ""
    target_type: str = ""
    expected_output_kind: Literal["parcel", "polygon", "point", "line", "action"] = "parcel"
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


class FinalManifest(ContractMeta):
    """Authoritative RECONCILE manifest for the closed planning chain."""

    coverage_matrix: CoverageMatrix = Field(default_factory=CoverageMatrix)
    inconsistencies: list[ReconciliationInconsistency] = Field(default_factory=list)
    provenance: "Provenance | None" = None


# The payload remains a reconciliation-shaped report internally, but the
# cross-stage artifact name is FinalManifest as defined by the target design.
ReconciliationReport = FinalManifest


__all__ = [
    "CoverageMatrixRow",
    "CoverageMatrix",
    "ReconciliationInconsistency",
    "FinalManifest",
    "ReconciliationReport",
]
