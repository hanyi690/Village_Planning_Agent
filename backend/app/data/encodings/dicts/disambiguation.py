"""L2 disambiguation interface models — Pydantic schemas for LLM-based code disambiguation.

These models define the contract between the CandidateEngine (L1) and
the LLM disambiguation step (L2). The LLM is not called here — these
models are the data structures that an LLM would consume and produce
via ``with_structured_output()``.

See REFACTOR_V4_PYDANTIC_DU_PIPELINE.md §3.3 for design rationale.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.validation.closed_set import (
    CandidateDecision,
    CandidateDescriptor,
    candidate_set_digest,
    select_closed_set_candidate,
)


class Candidate(BaseModel):
    """A single candidate target code + its triggering condition.

    Represents one entry in the closed set that L2 LLM must choose from.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    when: dict | None = None
    surviving_evidence: list[str] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def _code_not_empty(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("code must not be empty")
        return value


class DisambiguationContext(BaseModel):
    """Disambiguation context — consumed by flash LLM + instructor.

    Designed as the input schema for ``with_structured_output(DisambiguationDecision)``.
    The ``candidates`` field is the closed set; the LLM must choose from it.
    """

    model_config = ConfigDict(extra="forbid")

    source_system: str = Field(min_length=1)
    source_code: str = Field(min_length=1)
    parcel_attrs: dict[str, Any] = Field(default_factory=dict)
    neighbors: list[dict[str, Any]] = Field(default_factory=list)
    poi_hits: list[dict[str, Any]] = Field(default_factory=list)
    zone_membership: list[str] = Field(default_factory=list)
    village_profile: str = ""
    candidates: list[Candidate]
    candidate_set_digest: str = ""

    @field_validator("candidates")
    @classmethod
    def _candidates_not_empty(cls, v: list[Candidate]) -> list[Candidate]:
        if not v:
            raise ValueError("candidates must not be empty — closed set required")
        return v

    @model_validator(mode="after")
    def bind_candidate_set_digest(self) -> "DisambiguationContext":
        descriptors = [
            CandidateDescriptor(
                candidate_id=item.code,
                kind="classification_code",
                label=item.code,
                metadata={"when": item.when},
            )
            for item in self.candidates
        ]
        expected = candidate_set_digest(descriptors)
        if self.candidate_set_digest and self.candidate_set_digest != expected:
            raise ValueError("candidate_set_digest does not match candidates")
        self.candidate_set_digest = expected
        return self


class DisambiguationDecision(BaseModel):
    """Disambiguation decision — closed-set choice + evidence + provenance.

    The ``chosen_code`` must be one of the candidates in ``DisambiguationContext``.
    Validation is enforced at the consumer side (``info.context`` carries the context).
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["selected", "abstain", "ambiguous"]
    chosen_code: str | None = None
    confidence: Literal["high", "medium", "low"]
    rationale: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    candidate_set_digest: str = Field(min_length=1)
    decided_by: Literal["rule", "llm", "human"]
    model: str = ""
    reviewed: bool = False

    @model_validator(mode="after")
    def validate_status_shape(self) -> "DisambiguationDecision":
        if self.status == "selected" and not str(self.chosen_code or "").strip():
            raise ValueError("selected decision must contain chosen_code")
        if self.status != "selected" and self.chosen_code is not None:
            raise ValueError("abstain/ambiguous decision cannot contain chosen_code")
        self.evidence = [
            value for value in dict.fromkeys(str(item).strip() for item in self.evidence)
            if value
        ]
        return self


def validate_disambiguation_decision(
    context: DisambiguationContext,
    decision: DisambiguationDecision,
) -> CandidateDecision:
    """Apply exact runtime closed-set validation to one provider decision."""

    descriptors = [
        CandidateDescriptor(
            candidate_id=item.code,
            kind="classification_code",
            label=item.code,
            metadata={"when": item.when},
        )
        for item in context.candidates
    ]
    expected_digest = candidate_set_digest(descriptors)
    if decision.candidate_set_digest != expected_digest:
        return CandidateDecision(
            decision_id=f"disambiguation:{context.source_system}:{context.source_code}",
            status="ambiguous",
            candidate_set_digest=expected_digest,
            reason="candidate_set_digest_mismatch",
        )
    return select_closed_set_candidate(
        decision_id=f"disambiguation:{context.source_system}:{context.source_code}",
        candidates=descriptors,
        proposed_candidate_id=decision.chosen_code if decision.status == "selected" else None,
        abstain_allowed=decision.status in {"abstain", "ambiguous"},
    )


__all__ = [
    "Candidate",
    "DisambiguationContext",
    "DisambiguationDecision",
    "validate_disambiguation_decision",
]
