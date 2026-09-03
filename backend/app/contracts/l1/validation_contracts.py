"""Deterministic validation products for L1 observation rows."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SourceSpanValidationStatus = Literal[
    "valid",
    "source_missing",
    "segment_missing",
    "literal_mismatch",
    "offset_mismatch",
    "cross_source_reference",
    "role_not_admitted",
]


class SourceSpanValidationReport(BaseModel):
    """Auditable result for one observation's source locator validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validation_ref: str = Field(min_length=1)
    fact_ref: str = Field(min_length=1)
    source_ref: str = ""
    source_snapshot_ref: str = ""
    span_ref: str = ""
    quote_digest: str = ""
    status: SourceSpanValidationStatus
    validation_errors: tuple[str, ...] = ()


class L1QuarantineRecord(BaseModel):
    """Rejected observation row retained for deterministic audit/replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quarantine_ref: str = Field(min_length=1)
    raw_row_digest: str = Field(min_length=1)
    dimension: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    validation_errors: tuple[str, ...] = ()
    model_call_ref: str = ""
    page_ref: str = ""
    source_ref: str = ""


__all__ = [
    "L1QuarantineRecord",
    "SourceSpanValidationReport",
    "SourceSpanValidationStatus",
]
