"""Typed, flat contracts for DATA temporal-role admission decisions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.contracts.base import StrictContractModel


TemporalRole = Literal[
    "current_evidence",
    "planning_control",
    "planned_output",
    "reference_plan",
    "ambiguous",
]


class TemporalRoleInputRow(StrictContractModel):
    """One bounded source profile rendered as a flat table row for the LLM."""

    profile_ref: str
    source_ref: str
    declared_channel: str
    resource_kind: str
    filename: str = ""
    record_count: int = Field(default=0, ge=0)
    geometry_kinds: str = ""
    field_names: str = ""
    sample_values: str = ""
    content_excerpt: str = ""
    profile_complete: bool = True


class TemporalRoleProposal(StrictContractModel):
    """One provider row; every choice comes from the fixed role vocabulary."""

    profile_ref: str
    selected_role: TemporalRole
    reason_code: Literal[
        "observed_current_state",
        "requested_future_action",
        "hard_constraint",
        "produced_plan",
        "reference_plan",
        "insufficient_evidence",
    ]
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class TemporalRoleProposalBatch(StrictContractModel):
    """A bounded provider page containing flat, non-nested decision rows."""

    proposals: tuple[TemporalRoleProposal, ...] = Field(
        default=(),
        max_length=16,
    )


class SourceTemporalRoleDecision(StrictContractModel):
    """Auditable consensus decision consumed by source admission."""

    decision_ref: str
    source_ref: str
    profile_ref: str
    declared_channel: str
    selected_role: TemporalRole = "ambiguous"
    reason_code: str = "insufficient_evidence"
    status: Literal[
        "accepted",
        "ambiguous",
        "provider_failed",
        "protocol_failed",
    ] = "ambiguous"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    profile_complete: bool = True
    input_digest: str
    raw_output_digest: str
    prompt_version: str
    model_id: str
    provider_pass_count: int = Field(default=0, ge=0, le=2)
    pass_diagnostics: tuple[dict[str, object], ...] = ()


__all__ = [
    "SourceTemporalRoleDecision",
    "TemporalRole",
    "TemporalRoleInputRow",
    "TemporalRoleProposal",
    "TemporalRoleProposalBatch",
]
