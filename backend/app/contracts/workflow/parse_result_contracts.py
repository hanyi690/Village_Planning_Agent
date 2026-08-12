from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.program import PlanningClaim


class CompilationStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    NEEDS_REVIEW = "needs_review"
    COMMITTED = "committed"
    REJECTED = "rejected"


class ParseDiagnostic(BaseModel):
    diagnostic_id: str = ""
    severity: Literal["info", "warning", "error"] = "warning"
    code: str = ""  # e.g. "AMBIGUOUS_REFERENCE" | "TABLE_CORRUPT" | "SCHEMA_MISMATCH"
    message: str = ""
    field_path: str = ""
    source_text_loc: str = ""
    target_id: str = ""
    spec_id: str = ""


class IntentCompilationResult(ContractMeta):
    schema_version: Literal["2.0"] = "2.0"
    # 正式字段（不再用 Any intent 承载）
    program_ref: str = ""
    claims: list[PlanningClaim] = Field(default_factory=list)
    typed_intent: Any = None  # SpatialPlanningIntent (lazy ref, keep Any to avoid circular)
    spatial_reference_specs: list[Any] = Field(default_factory=list)  # SpatialReferenceSpec[]
    diagnostics: list[ParseDiagnostic] = Field(default_factory=list)
    compilation_status: CompilationStatus = CompilationStatus.DRAFT
    provenance: Any = None  # Provenance


__all__ = [
    "CompilationStatus",
    "ParseDiagnostic",
    "IntentCompilationResult",
]
