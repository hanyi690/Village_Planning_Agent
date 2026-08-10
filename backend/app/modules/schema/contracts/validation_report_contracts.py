from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .contract_meta import ContractMeta, StageIssue
from .provenance import Provenance


class ConstraintAdjustment(BaseModel):
    constraint_id: str = ""
    adjustment_type: str = ""
    original_value: float | str | None = None
    adjusted_value: float | str | None = None
    reason: str = ""
    source_check: str = ""


class ValidationCheck(BaseModel):
    check_id: str
    check_name: str = ""
    passed: bool = False
    actual_value: str = ""
    expected_value: str = ""
    responsible_stage: Literal["L3", "PARSE", "GROUND", "SELECT", "EXECUTE"] = "EXECUTE"
    affected_parcels: list[str] = Field(default_factory=list)
    affected_target_ids: list[str] = Field(default_factory=list)
    fix_suggestion: str = ""


class ValidationIssue(StageIssue):
    check_id: str = ""
    deviation_pct: float = 0.0
    constraint_source: str = ""


class ValidationReport(ContractMeta):
    checks: list[ValidationCheck] = Field(default_factory=list)
    overall_passed: bool = False
    issues_by_stage: dict[str, list[ValidationIssue]] = Field(default_factory=dict)
    adjustments: list[ConstraintAdjustment] = Field(default_factory=list)
    provenance: "Provenance | None" = None
