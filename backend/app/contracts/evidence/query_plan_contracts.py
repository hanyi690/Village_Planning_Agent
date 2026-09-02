"""Immutable Evidence acquisition query-plan contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PageMode = Literal["single_page", "cursor", "offset"]
CompletionCondition = Literal[
    "required_routes_complete",
    "provider_exhausted",
    "declared_limit_allowed",
]


class EvidenceProviderRoute(BaseModel):
    """One deterministic route from a plan into an acquisition authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    route_ref: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    retriever: str = Field(min_length=1)
    source_family: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    query: str = ""
    entity_scope: tuple[str, ...] = ()
    required_facts: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    required_for_acquisition: bool = True


class EvidencePageStrategy(BaseModel):
    """Bounded acquisition pagination semantics owned by Evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: PageMode = "single_page"
    page_size: int = Field(default=64, ge=1, le=1000)
    hard_page_limit: int = Field(default=1, ge=1, le=10000)


class EvidenceRetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=10)
    retryable_statuses: tuple[str, ...] = ("FAILED_RETRYABLE", "TIMEOUT")


class EvidenceTimeoutPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: float = Field(default=30.0, gt=0.0, le=3600.0)


class EvidenceBudget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    budget_class: str = Field(default="local", min_length=1)
    max_routes: int = Field(default=16, ge=1, le=100)
    max_items: int = Field(default=1000, ge=1, le=100000)


class EvidenceQueryPlanV1(BaseModel):
    """The immutable, replayable semantic plan for Evidence acquisition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query_plan_ref: str = ""
    requirement_refs: tuple[str, ...] = ()
    normalized_query: str = ""
    subject_refs: tuple[str, ...] = ()
    scope: tuple[str, ...] = ()
    provider_routes: tuple[EvidenceProviderRoute, ...] = ()
    page_strategy: EvidencePageStrategy = Field(default_factory=EvidencePageStrategy)
    dedupe_key: str = ""
    cache_policy: str = "session_scoped_write_once"
    retry_policy: EvidenceRetryPolicy = Field(default_factory=EvidenceRetryPolicy)
    timeout_policy: EvidenceTimeoutPolicy = Field(default_factory=EvidenceTimeoutPolicy)
    budget: EvidenceBudget = Field(default_factory=EvidenceBudget)
    completion_condition: CompletionCondition = "required_routes_complete"
    policy_ref: str = "source_semantic_support.v1"
    policy_version: str = "1"
    policy_refs: tuple[str, ...] = ()
    plan_fingerprint: str = ""
    contract_version: Literal["1.0"] = "1.0"

    @model_validator(mode="after")
    def _freeze_identity(self) -> "EvidenceQueryPlanV1":
        payload = self.model_dump(
            mode="json",
            exclude={"query_plan_ref", "plan_fingerprint"},
        )
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if self.plan_fingerprint and self.plan_fingerprint != digest:
            raise ValueError("query plan fingerprint does not match plan content")
        if self.query_plan_ref and not self.query_plan_ref.startswith("evidence.query-plan."):
            raise ValueError("query plan ref must use the evidence.query-plan namespace")
        object.__setattr__(self, "plan_fingerprint", digest)
        object.__setattr__(self, "query_plan_ref", f"evidence.query-plan.{digest[:24]}")
        return self


__all__ = [
    "EvidenceBudget",
    "EvidencePageStrategy",
    "EvidenceProviderRoute",
    "EvidenceQueryPlanV1",
    "EvidenceRetryPolicy",
    "EvidenceTimeoutPolicy",
]
