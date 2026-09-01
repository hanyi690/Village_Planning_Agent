"""Compatibility implementation of the world-model write port.

The application layer talks to this adapter through ``WorldModelCommitPort``.
Keeping the legacy RDF builders here lets the world-model store migrate without
leaking KGManager, ontology, or builder imports into GROUND/EXECUTE modules.
"""

from __future__ import annotations

from typing import Any


class KGWorldModelCommitAdapter:
    """Commit intent/planned artifacts to the active session KG atomically."""

    def __init__(self, kg: Any, *, session_id: str = "") -> None:
        if kg is None or getattr(kg, "g", None) is None:
            raise ValueError("world-model commit adapter requires an RDF graph")
        self._kg = kg
        self._session_id = str(session_id or "")

    def ensure_intent(self, intent: Any) -> dict[str, Any]:
        """Materialize the compatibility intent projection and report counts."""

        from app.infrastructure.kg.builder.layer3 import build_intent_layer

        before = len(self._kg.g)
        build_intent_layer(self._kg, intent)
        return {
            "status": "committed",
            "triple_delta": max(0, len(self._kg.g) - before),
        }

    def commit_planned_state(self, planned_state: Any) -> dict[str, Any]:
        """Apply one planned state with rollback on a partial write."""

        from app.infrastructure.kg.builder.layer4 import apply_planned_state

        graph_snapshot = list(self._kg.g)
        try:
            apply_planned_state(self._kg, planned_state)
        except Exception as exc:  # pragma: no cover - exercised by runtime failures
            self._kg.g.remove((None, None, None))
            for triple in graph_snapshot:
                self._kg.g.add(triple)
            return {
                "status": "aborted",
                "committed": False,
                "error_type": type(exc).__name__,
            }

        written = sum(
            len(getattr(planned_state, field, None) or [])
            for field in ("features", "parcels", "zones", "facilities", "roads", "axes")
        )
        if self._session_id:
            try:
                from app.infrastructure.kg.manager import get_kg_manager

                get_kg_manager().bump_version(self._session_id)
            except Exception:
                # A graph commit remains valid even when the process cache
                # version hook is unavailable; the caller records diagnostics.
                pass
        return {
            "status": "committed",
            "committed": True,
            "written": written,
        }

    def commit_identity_bindings(self, envelope: Any) -> Any:
        """Reject identity projection on the legacy non-versioned KG.

        A compatibility graph cannot publish the immutable child World Model
        snapshot required by the L1 transition contract.  Returning a typed
        unsupported result lets V2 fail closed instead of partially writing
        assertions or raising an incidental AttributeError.
        """

        from app.contracts.cognition.identity_projection import (
            IdentityBindingCommitResult,
        )

        return IdentityBindingCommitResult(
            status="unsupported",
            committed=False,
            error_type="legacy_kg_has_no_identity_projection_plane",
        )


__all__ = ["KGWorldModelCommitAdapter"]
