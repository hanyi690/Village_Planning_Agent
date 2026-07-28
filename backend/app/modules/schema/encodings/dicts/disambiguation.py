"""L2 disambiguation interface models — Pydantic schemas for LLM-based code disambiguation.

These models define the contract between the CandidateEngine (L1) and
the LLM disambiguation step (L2). The LLM is not called here — these
models are the data structures that an LLM would consume and produce
via ``with_structured_output()``.

See REFACTOR_V4_PYDANTIC_DU_PIPELINE.md §3.3 for design rationale.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, field_validator


class Candidate(BaseModel):
    """A single candidate target code + its triggering condition.

    Represents one entry in the closed set that L2 LLM must choose from.
    """

    code: str
    when: dict | None = None
    surviving_evidence: list[str] = []

    @field_validator("code")
    @classmethod
    def _code_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("code must not be empty")
        return v


class DisambiguationContext(BaseModel):
    """Disambiguation context — consumed by flash LLM + instructor.

    Designed as the input schema for ``with_structured_output(DisambiguationDecision)``.
    The ``candidates`` field is the closed set; the LLM must choose from it.
    """

    source_system: str
    source_code: str
    parcel_attrs: dict[str, Any] = {}
    neighbors: list[dict[str, Any]] = []
    poi_hits: list[dict[str, Any]] = []
    zone_membership: list[str] = []
    village_profile: str = ""
    candidates: list[Candidate]

    @field_validator("candidates")
    @classmethod
    def _candidates_not_empty(cls, v: list[Candidate]) -> list[Candidate]:
        if not v:
            raise ValueError("candidates must not be empty — closed set required")
        return v


class DisambiguationDecision(BaseModel):
    """Disambiguation decision — closed-set choice + evidence + provenance.

    The ``chosen_code`` must be one of the candidates in ``DisambiguationContext``.
    Validation is enforced at the consumer side (``info.context`` carries the context).
    """

    chosen_code: str
    confidence: Literal["high", "medium", "low"]
    rationale: str
    evidence: list[str] = []
    decided_by: Literal["rule", "llm", "human", "default"] = "llm"
    model: str = ""
    reviewed: bool = False


__all__ = [
    "Candidate",
    "DisambiguationContext",
    "DisambiguationDecision",
]