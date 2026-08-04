from __future__ import annotations

from pydantic import BaseModel, Field

from .contract_meta import ContractMeta


class CoverageMatrix(BaseModel):
    rows: list[dict] = Field(default_factory=list)  # intervention_id -> spec -> candidate -> decision -> change -> planned


class ReconciliationInconsistency(BaseModel):
    intervention_id: str = ""
    field: str = ""
    expected: str = ""
    actual: str = ""
    severity: str = "warning"


class ReconciliationReport(ContractMeta):
    coverage_matrix: CoverageMatrix = Field(default_factory=CoverageMatrix)
    inconsistencies: list[ReconciliationInconsistency] = Field(default_factory=list)
