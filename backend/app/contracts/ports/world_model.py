"""Ports for querying and committing the cognitive world-model projection."""

from __future__ import annotations

from typing import Any, Protocol

from app.contracts.cognition.identity_projection import (
    IdentityBindingCommitEnvelope,
    IdentityBindingCommitResult,
)
from app.contracts.cognition.proposals import (
    AssertionCommitRequest,
    AssertionDecisionArtifact,
    AssertionProposal,
    WorldModelCommitReceipt,
)


class CurrentWorldQueryPort(Protocol):
    """Bounded read-only view of the current DATA-backed world snapshot.

    Implementations must read source records from the source graph and world
    entities/parts/representations from the world graph. This protocol does
    not expose assertion, intent, planned, identity, RDF, or network APIs.
    """

    def find_source_records(
        self,
        *,
        source_record_ref: str = "",
        source_feature_ref: str = "",
        dataset_ref: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    def find_entities(
        self,
        *,
        identity: str = "",
        entity_ref: str = "",
        source_feature_ref: str = "",
        name: str = "",
        entity_type: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    def representations_for(
        self,
        entity_ref: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...


class WorldModelCommitPort(Protocol):
    """Write boundary for intent and planned-world changes.

    Business modules receive this port from Context Runtime for intent,
    planned-state, and the still-active L1 projection transition. Current
    assertion writes use the separate CognitionCommitPort.
    """

    def ensure_intent(self, intent: Any) -> dict[str, Any]: ...

    def commit_planned_state(self, planned_state: Any) -> dict[str, Any]: ...

    def commit_identity_bindings(
        self,
        envelope: IdentityBindingCommitEnvelope,
    ) -> IdentityBindingCommitResult:
        """Atomically project one L1 observation/binding snapshot pair."""
        ...


class CognitionCommitPort(Protocol):
    """Exclusive current-world assertion writer owned by Cognition."""

    def commit_assertion_transaction(
        self,
        request: AssertionCommitRequest,
        proposals: tuple[AssertionProposal, ...],
        decisions: tuple[AssertionDecisionArtifact, ...],
    ) -> WorldModelCommitReceipt:
        """Commit one Cognition-validated current-world assertion group."""
        ...


__all__ = [
    "CognitionCommitPort",
    "CurrentWorldQueryPort",
    "WorldModelCommitPort",
]
