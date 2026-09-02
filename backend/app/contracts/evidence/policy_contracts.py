"""Versioned, deterministic policies for Evidence requirement evaluation."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PolicyConflict = Literal["resolve", "defer", "human", "reject"]
PolicyAbsence = Literal[
    "never",
    "only_complete_authoritative_routes",
    "complete_provider_exhaustion",
]
PolicyCompletion = Literal[
    "required_routes_complete",
    "provider_exhausted",
    "declared_limit_allowed",
]


class EvidencePolicy(BaseModel):
    """Immutable policy used to evaluate one family of requirements."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_ref: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    allowed_source_families: tuple[str, ...] = ()
    required_source_authority: str = "advisory"
    geometry_authority: str = "none"
    legal_authority: str = "none"
    min_independent_sources: int = Field(default=1, ge=0)
    max_age_days: int | None = Field(default=None, ge=0)
    legal_effective_time: str = ""
    allowed_inference: tuple[str, ...] = ("exact",)
    conflict_policy: PolicyConflict = "defer"
    absence_policy: PolicyAbsence = "never"
    completion_requirement: PolicyCompletion = "required_routes_complete"
    budget_class: str = "local"
    contract_version: Literal["1.0"] = "1.0"

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_POLICIES: dict[str, EvidencePolicy] = {
    "location_identity_support.v1": EvidencePolicy(
        policy_ref="location_identity_support",
        policy_version="1",
        allowed_source_families=("data", "gis", "kg", "artifact", "cache"),
        required_source_authority="authoritative",
        conflict_policy="human",
    ),
    "facility_existence.v1": EvidencePolicy(
        policy_ref="facility_existence",
        policy_version="1",
        allowed_source_families=("data", "gis", "kg", "report"),
        required_source_authority="authoritative",
        conflict_policy="defer",
    ),
    "road_identity.v1": EvidencePolicy(
        policy_ref="road_identity",
        policy_version="1",
        allowed_source_families=("data", "gis", "kg", "artifact", "cache"),
        required_source_authority="authoritative",
        conflict_policy="human",
    ),
    "relation_support.v1": EvidencePolicy(
        policy_ref="relation_support",
        policy_version="1",
        allowed_source_families=("kg", "report", "rag", "data"),
        allowed_inference=("exact", "derived"),
    ),
    "source_semantic_support.v1": EvidencePolicy(
        policy_ref="source_semantic_support",
        policy_version="1",
        allowed_source_families=("data", "source_record", "report", "rag", "external"),
        allowed_inference=("exact", "text_only"),
    ),
    "execution_geometry_support.v1": EvidencePolicy(
        policy_ref="execution_geometry_support",
        policy_version="1",
        allowed_source_families=("data", "gis"),
        required_source_authority="authoritative",
        geometry_authority="data_resource_catalog",
        conflict_policy="human",
    ),
    "legal_extent_support.v1": EvidencePolicy(
        policy_ref="legal_extent_support",
        policy_version="1",
        allowed_source_families=("data", "gis", "kg"),
        required_source_authority="authoritative",
        legal_authority="local_legal_source",
        conflict_policy="human",
    ),
    "absence_claim.v1": EvidencePolicy(
        policy_ref="absence_claim",
        policy_version="1",
        allowed_source_families=("data", "gis", "kg", "report"),
        required_source_authority="authoritative",
        min_independent_sources=2,
        conflict_policy="human",
        absence_policy="only_complete_authoritative_routes",
        completion_requirement="provider_exhausted",
    ),
}


class EvidencePolicyRegistry:
    """Read-only registry for versioned policy resolution."""

    @classmethod
    def resolve(cls, policy_ref: str, policy_version: str | None = None) -> EvidencePolicy:
        key = str(policy_ref or "").strip()
        if policy_version and ".v" not in key:
            key = f"{key}.v{policy_version}"
        elif ".v" not in key:
            key = f"{key}.v1"
        policy = _POLICIES.get(key)
        if policy is None:
            raise ValueError(f"unknown Evidence policy: {policy_ref!r}")
        return policy

    @classmethod
    def all(cls) -> tuple[EvidencePolicy, ...]:
        return tuple(_POLICIES[key] for key in sorted(_POLICIES))


def resolve_policy(policy_ref: str, policy_version: str | None = None) -> EvidencePolicy:
    """Resolve a policy through the single deterministic registry."""

    return EvidencePolicyRegistry.resolve(policy_ref, policy_version)


__all__ = [
    "EvidencePolicy",
    "EvidencePolicyRegistry",
    "PolicyAbsence",
    "PolicyCompletion",
    "PolicyConflict",
    "resolve_policy",
]
