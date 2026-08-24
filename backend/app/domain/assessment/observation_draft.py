"""Provider-facing L1 projection drafts (normalized into L1 contracts).

Production L1 requests observations/register material first and synthesizes
``report_body`` in a later, report-only pass.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class L1ObservationDraft(BaseModel):
    """Provider-facing L1 现状 observation before domain normalization.

    The L1 observe pass returns these rows without a report body; they are
    compiled into ``L1LocationFact`` (with a typed role) by the observation
    profile, replacing the legacy markdown-table parsing.
    """

    entity_type: str = ""  # 现状设施 / 现状项目 / 现状分区 / 道路 / 水系 / 地物
    name: str = ""
    location: str = ""
    relation: str = ""  # 与其他地点的空间关系（位于X村中部/沿石窟河/汇入石窟河/通往X村）
    description: str = ""
    scale: str = ""
    observation_kind: Literal[
        "place",
        "current_asset",
        "demand",
        "metric",
        "constraint",
        "relation",
        "risk",
        "opportunity",
        "document_observation",
    ] = "place"
    semantic_type: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    value: str | int | float | None = None
    unit: str = ""
    counting_basis: str = ""
    related_observation_ids: list[str] = Field(default_factory=list)
    constraint_refs: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    source_segment_ids: list[str] = Field(default_factory=list)
    source_quote: str = ""
    source_refs: list[str] = Field(default_factory=list)
    confidence: float | None = None
    status: Literal["confirmed", "uncertain", "conflict", "source_exhausted"] = "confirmed"


class L1RegisterRowDraft(BaseModel):
    """Provider-facing draft of one L1-owned input registration.

    The model may reference an already materialized row by ``row_id`` or
    describe a newly recognized registration by citing source segments.  The
    worker materializes canonical source locators from the L1 source index
    after validation.
    """

    row_id: str = ""
    ledger_kind: Literal["current_asset", "demand"] | None = None
    status: Literal[
        "confirmed",
        "not_applicable",
        "uncertain",
        "source_exhausted",
        "conflict",
    ] = "confirmed"
    evidence_note: str = ""
    source_quote: str = ""
    category: str = ""
    name: str = ""
    quantity_text: str = ""
    quantity_value: float | None = None
    quantity_unit: str = ""
    location_text: str = ""
    service_scope: str = ""
    coverage: str = ""
    notes: str = ""
    source_segment_ids: list[str] = Field(default_factory=list)


class L1CoverageDecision(BaseModel):
    """Explicit status for a source row considered by one dimension."""

    row_id: str = Field(min_length=1)
    status: Literal[
        "confirmed",
        "not_applicable",
        "uncertain",
        "source_exhausted",
        "conflict",
    ]
    reason: str = ""


class L1ObservationPassOutput(BaseModel):
    """L1 semantic extraction pass without a human report projection."""

    observations: list[L1ObservationDraft] = Field(default_factory=list)
    register_rows: list[L1RegisterRowDraft] = Field(default_factory=list)
    coverage: list[L1CoverageDecision] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class L1ReportOutput(BaseModel):
    """L1 human report synthesized from validated observations and evidence."""

    report_body: str = Field(min_length=1)


class L1RegisterPassOutput(BaseModel):
    """Small follow-up response used to confirm or repair selected rows."""

    register_rows: list[L1RegisterRowDraft] = Field(default_factory=list)
    coverage: list[L1CoverageDecision] = Field(default_factory=list)


__all__ = [
    "L1CoverageDecision",
    "L1ObservationPassOutput",
    "L1ReportOutput",
    "L1ObservationDraft",
    "L1RegisterPassOutput",
    "L1RegisterRowDraft",
]
