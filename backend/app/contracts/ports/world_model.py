"""Ports for querying and committing the cognitive world-model projection."""

from __future__ import annotations

from typing import Any, Protocol

from app.contracts.cognition.identity_projection import (
    IdentityBindingCommitEnvelope,
    IdentityBindingCommitResult,
)
from app.contracts.cognition.proposals import (
    WorldModelCommitResult,
    WorldModelProposalBatch,
)
from app.contracts.cognition.query import (
    IdentityBindingProjectionPage,
    IdentityBindingProjectionRequest,
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


class WorldModelPort(Protocol):
    """Read-only KG identity/representation/relation surface.

    This is the cognition World Model contract; the name ``WorldModel`` does
    not introduce a store alongside KG.  A backend may use RDF, SQL, or a
    graph index, but callers receive the same bounded rows.
    """

    def find_entities(self, *, identity: str = "", entity_ref: str = "", source_feature_ref: str = "", name: str = "", entity_type: str = "", limit: int = 50, **filters: Any) -> list[dict[str, Any]]: ...

    def representations_for(self, entity_ref: str, *, limit: int = 50) -> list[dict[str, Any]]: ...

    def find_relations(
        self,
        *,
        subject_ref: str = "",
        object_ref: str = "",
        predicate: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]: ...

    def find_identity_bindings(
        self,
        *,
        mention_ref: str = "",
        entity_ref: str = "",
        status: str = "",
        work_item_ref: str = "",
        source_mention_ref: str = "",
        dimension_ref: str = "",
        scope_ref: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return a bounded L1 mention-to-entity projection.

        ``status`` filters the identity decision (resolved/ambiguous/
        unresolved/not_applicable), not the geometry-granularity status kept
        for migration compatibility in the binding contract.
        """
        ...

    def query_identity_binding_page(
        self,
        request: IdentityBindingProjectionRequest,
    ) -> IdentityBindingProjectionPage:
        """Return one authority-bound dependency projection page."""
        ...

    def build_network_retry_adapter(self) -> Any: ...


class WorldModelCommitPort(Protocol):
    """Write boundary for intent and planned-world changes.

    Business modules receive this port from Context Runtime.  They must not
    import KG managers, RDF builders, or ontology constants directly.  The
    implementation may be the DATA-backed ``WorldModelKGStore`` or the
    legacy KG adapter during migration; callers must not distinguish them.
    """

    def ensure_intent(self, intent: Any) -> dict[str, Any]: ...

    def commit_planned_state(self, planned_state: Any) -> dict[str, Any]: ...

    def commit_changeset(self, changeset: Any) -> dict[str, Any]: ...

    def commit_identity_bindings(
        self,
        envelope: IdentityBindingCommitEnvelope,
    ) -> IdentityBindingCommitResult:
        """Atomically project one L1 observation/binding snapshot pair."""
        ...

    def commit_proposal_batch(
        self,
        batch: WorldModelProposalBatch,
    ) -> WorldModelCommitResult:
        """Validate and atomically commit one current-world proposal batch."""
        ...


__all__ = ["CurrentWorldQueryPort", "WorldModelPort", "WorldModelCommitPort"]
