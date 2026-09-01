"""Auditable semantic assertion contract."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.contracts.base import StrictContractModel


class SemanticAssertion(StrictContractModel):
    assertion_ref: str
    subject_ref: str
    predicate: str
    object_ref: str = ""
    value: str = ""
    assertion_kind: str = "semantic"
    valid_time: str = ""
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    proposal_ref: str = ""
    decision_ref: str = ""
    status: Literal["candidate", "accepted", "ambiguous", "rejected", "superseded"] = "candidate"
    confidence: float = 0.0
    confidence_components: dict[str, float] = Field(default_factory=dict)
    authority: dict[str, str] = Field(default_factory=dict)
    parent_world_model_snapshot_ref: str = ""
    parent_world_model_snapshot_digest: str = ""
    supersedes: tuple[str, ...] = ()


__all__ = ["SemanticAssertion"]
