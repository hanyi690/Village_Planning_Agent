"""Provider-facing closed-set contracts and deterministic membership kernel.

This is the single owner for candidate identities used by LLM proposals. A
domain module may define its own candidate payload, but it must adapt that
payload to these descriptors before it enters a prompt or a decision
certificate. The digest is order-independent and final membership is
deterministic.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field


class CandidateDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    kind: str
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    selected_candidate_id: str | None = None
    status: Literal["selected", "abstain", "ambiguous"]
    candidate_set_digest: str
    reason: str = ""


class ExactBatchMembershipResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    expected_ids: tuple[str, ...] = ()
    actual_ids: tuple[str, ...] = ()
    missing_ids: tuple[str, ...] = ()
    extra_ids: tuple[str, ...] = ()
    duplicate_ids: tuple[str, ...] = ()


def _digest_payload(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def candidate_set_digest(candidates: Iterable[CandidateDescriptor]) -> str:
    """Return one stable digest for the complete closed candidate set."""

    payload = [item.model_dump(mode="json") for item in candidates]
    payload.sort(key=lambda item: (item["candidate_id"], item["kind"], item["label"]))
    return _digest_payload(payload)


def select_closed_set_candidate(
    *,
    decision_id: str,
    candidates: list[CandidateDescriptor],
    proposed_candidate_id: str | None,
    abstain_allowed: bool,
) -> CandidateDecision:
    """Validate one stable-ID proposal against the supplied candidate set."""

    digest = candidate_set_digest(candidates)
    normalized = [str(item.candidate_id).strip() for item in candidates]
    duplicates = tuple(
        sorted({item for item in normalized if normalized.count(item) > 1 and item})
    )
    proposed = str(proposed_candidate_id or "").strip()
    if duplicates:
        return CandidateDecision(
            decision_id=decision_id,
            status="ambiguous",
            candidate_set_digest=digest,
            reason="candidate set contains duplicate stable IDs",
        )
    if not proposed:
        return CandidateDecision(
            decision_id=decision_id,
            status="abstain" if abstain_allowed else "ambiguous",
            candidate_set_digest=digest,
            reason="no candidate ID was proposed",
        )
    if proposed not in normalized:
        return CandidateDecision(
            decision_id=decision_id,
            status="abstain" if abstain_allowed else "ambiguous",
            candidate_set_digest=digest,
            reason="proposed candidate ID is outside the supplied closed set",
        )
    return CandidateDecision(
        decision_id=decision_id,
        selected_candidate_id=proposed,
        status="selected",
        candidate_set_digest=digest,
    )


def validate_exact_batch_membership(
    expected_ids: Iterable[str],
    actual_ids: Iterable[str],
) -> ExactBatchMembershipResult:
    """Require exact, unique coverage of caller-provided stable IDs."""

    expected = tuple(
        dict.fromkeys(str(item).strip() for item in expected_ids if str(item).strip())
    )
    actual_values = tuple(str(item).strip() for item in actual_ids if str(item).strip())
    actual = tuple(dict.fromkeys(actual_values))
    duplicates = tuple(
        sorted({item for item in actual_values if actual_values.count(item) > 1})
    )
    expected_set = set(expected)
    actual_set = set(actual)
    missing = tuple(sorted(expected_set - actual_set))
    extra = tuple(sorted(actual_set - expected_set))
    return ExactBatchMembershipResult(
        accepted=not missing and not extra and not duplicates and set(expected) == set(actual),
        expected_ids=expected,
        actual_ids=actual,
        missing_ids=missing,
        extra_ids=extra,
        duplicate_ids=duplicates,
    )


__all__ = [
    "CandidateDescriptor",
    "CandidateDecision",
    "ExactBatchMembershipResult",
    "candidate_set_digest",
    "select_closed_set_candidate",
    "validate_exact_batch_membership",
]
