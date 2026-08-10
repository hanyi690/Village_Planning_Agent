from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contract_meta import ContractMeta


class HumanDeferralDecision(BaseModel):
    """Immutable human decision metadata attached to a target deferral."""

    model_config = ConfigDict(frozen=True)

    decision_id: str
    decided_by: str = ""
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    rationale: str = ""
    action: Literal["defer"] = "defer"


class TargetDeferral(BaseModel):
    """One explicit, source-backed non-blocking target deferral."""

    model_config = ConfigDict(frozen=True)

    target_id: str
    reason: str
    source_refs: tuple[str, ...] = ()
    decision: HumanDeferralDecision

    @field_validator("target_id")
    @classmethod
    def target_id_must_be_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("target_id is required for a deferral")
        return value


class DeferralLedger(ContractMeta):
    """Immutable v2 root artifact for auditable target-level deferrals."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["2.0"] = "2.0"
    entries: tuple[TargetDeferral, ...] = ()


__all__ = ["HumanDeferralDecision", "TargetDeferral", "DeferralLedger"]
