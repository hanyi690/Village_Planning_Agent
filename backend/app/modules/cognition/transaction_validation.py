"""Deterministic Cognition validation for v0.5 assertion proposals."""

from __future__ import annotations

from hashlib import sha256

from app.contracts.cognition.proposals import (
    AssertionDecisionArtifact,
    AssertionProposal,
)


_VALIDATOR_REF = "cognition:assertion-validator-v0.5"
_POLICY_REF = "cognition:current-world-policy"
_POLICY_VERSION = "v0.5"
_AMBIGUOUS_KINDS = frozenset({
    "merge",
    "split",
    "identity_merge",
    "identity_split",
})


class CognitionAssertionValidator:
    """Create decisions without making any World Model mutation."""

    validator_ref = _VALIDATOR_REF
    policy_ref = _POLICY_REF
    policy_version = _POLICY_VERSION

    def evaluate(
        self,
        proposals: tuple[AssertionProposal, ...],
        *,
        current_world_digest: str,
    ) -> tuple[AssertionDecisionArtifact, ...]:
        decisions: list[AssertionDecisionArtifact] = []
        for proposal in proposals:
            if proposal.parent_current_world_digest != current_world_digest:
                decision = "REJECT"
                reason_code = "parent_current_world_digest_mismatch"
            elif proposal.proposal_kind.casefold() in _AMBIGUOUS_KINDS:
                decision = "AMBIGUOUS"
                reason_code = "identity_topology_requires_review"
            elif not proposal.authority:
                decision = "REJECT"
                reason_code = "missing_proposal_authority"
            else:
                decision = "ACCEPT"
                reason_code = "deterministic_v05_policy"
            decision_ref = "decision:" + sha256(
                f"{proposal.proposal_ref}:{current_world_digest}:{decision}".encode(
                    "utf-8"
                )
            ).hexdigest()[:32]
            decisions.append(
                AssertionDecisionArtifact(
                    decision_ref=decision_ref,
                    proposal_ref=proposal.proposal_ref,
                    decision=decision,
                    reason_code=reason_code,
                    validator_ref=self.validator_ref,
                    policy_ref=self.policy_ref,
                    policy_version=self.policy_version,
                    parent_current_world_digest=current_world_digest,
                )
            )
        return tuple(decisions)


__all__ = ["CognitionAssertionValidator"]
