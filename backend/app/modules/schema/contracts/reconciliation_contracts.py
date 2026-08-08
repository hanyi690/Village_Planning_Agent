from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .contract_meta import ContractMeta
from .provenance import Provenance


class CoverageMatrixRow(BaseModel):
    intervention_id: str = ""
    spec_index: int | None = None
    candidate_site_id: str = ""
    selected_bsm: str = ""
    change_bsm: str = ""
    planned_parcel_bsm: str = ""
    status: Literal["covered", "partial", "missing", "deferred"] = "missing"


class CoverageMatrix(BaseModel):
    rows: list[CoverageMatrixRow] = Field(default_factory=list)


class ReconciliationInconsistency(BaseModel):
    intervention_id: str = ""
    field: str = ""
    expected: str = ""
    actual: str = ""
    severity: str = "warning"
    responsible_stage: Literal["L3", "PARSE", "GROUND", "SELECT", "EXECUTE"] = "EXECUTE"


class ReconciliationReport(ContractMeta):
    coverage_matrix: CoverageMatrix = Field(default_factory=CoverageMatrix)
    inconsistencies: list[ReconciliationInconsistency] = Field(default_factory=list)
    provenance: "Provenance | None" = None


__all__ = [
    "CoverageMatrixRow",
    "CoverageMatrix",
    "ReconciliationInconsistency",
    "ReconciliationReport",
]
