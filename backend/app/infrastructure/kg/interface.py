"""Stable integration boundary for the planning knowledge graph.

External callers should import these functions from ``app.infrastructure.kg`` instead
of reaching into ``manager.py`` or calling private builder methods.

Stage-0 surface (kept minimal to avoid pulling in L3/L4 semantics that depend
on PlanningKG methods not yet present on this branch):

    - ``KGSessionSnapshot``: serializable metadata returned from mutations.
    - ``require_session_kg(session_id)``: isolated PlanningKG accessor.
    - ``open_kg_session(...)``: build or clone Layer 1, then register a session.
    - ``query_session_sparql(session_id, sparql)``: explicit SPARQL.
    - ``query_session_template(session_id, template_name, **params)``: cached
      named-template queries (the path ExploreFlashAgent uses).
    - ``close_kg_session(session_id)``: release a session.

Dropped from handoff branch (need PlanningKG methods that this branch lacks):
    - ``replace_session_intent`` (requires ``kg.replace_intent_layer``)
    - ``apply_session_planned_state`` (requires ``kg.apply_planned_state``)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .manager import compute_layer1_cache_key, get_kg_manager


@dataclass(frozen=True)
class KGSessionSnapshot:
    """Serializable metadata returned after a KG session mutation."""

    session_id: str
    village_name: str
    version: int
    triple_count: int
    cache_hit: bool = False
    layer1_cache_key: str = ""


def _snapshot(
    session_id: str,
    *,
    cache_hit: bool = False,
    layer1_cache_key: str = "",
) -> KGSessionSnapshot:
    manager = get_kg_manager()
    kg = manager.require_session_kg(session_id)
    return KGSessionSnapshot(
        session_id=session_id,
        village_name=str(getattr(kg, "village_name", "") or ""),
        version=manager.get_session_version(session_id),
        triple_count=kg.get_triple_count(),
        cache_hit=cache_hit,
        layer1_cache_key=layer1_cache_key,
    )


def open_kg_session(
    *,
    session_id: str,
    village_name: str,
    bundle: Any,
    parcel_relations: Any = None,
) -> KGSessionSnapshot:
    """Build or clone Layer 1, then register an isolated runtime session."""
    if not session_id:
        raise ValueError("session_id is required for KG integration")
    if not village_name:
        raise ValueError("village_name is required when opening a KG session")
    if bundle is None:
        raise ValueError("bundle is required when opening a KG session")
    bundle_village_name = str(getattr(bundle, "village_name", "") or "")
    if bundle_village_name and bundle_village_name != village_name:
        raise ValueError(
            "bundle.village_name must match village_name "
            f"({bundle_village_name!r} != {village_name!r})"
        )

    manager = get_kg_manager()
    kg, cache_hit = manager.get_or_build_layer1(
        village_name=village_name,
        bundle=bundle,
        parcel_relations=parcel_relations,
    )
    key = compute_layer1_cache_key(
        village_name,
        (getattr(bundle, "polygons", None) or {}).get("landuse_current"),
        bundle=bundle,
    )
    manager.register_session(
        session_id,
        kg,
        layer1_cache_key=str(key) if key else "",
    )
    return _snapshot(
        session_id,
        cache_hit=cache_hit,
        layer1_cache_key=str(key) if key else "",
    )


def require_session_kg(session_id: str) -> Any:
    """Return the isolated PlanningKG object for advanced in-process callers."""
    if not session_id:
        raise ValueError("session_id is required for KG queries")
    return get_kg_manager().require_session_kg(session_id)


def query_session_sparql(session_id: str, sparql: str) -> List[Dict[str, Any]]:
    """Run an explicit SPARQL query against one isolated session."""
    if not sparql or not sparql.strip():
        raise ValueError("sparql is required")
    return require_session_kg(session_id).query(sparql)


def query_session_template(
    session_id: str,
    template_name: str,
    **params: Any,
) -> List[Dict[str, Any]]:
    """Run a named query template with session/version-aware caching."""
    if not template_name:
        raise ValueError("template_name is required")
    manager = get_kg_manager()
    kg = manager.require_session_kg(session_id)
    return manager.query_with_cache(
        session_id=session_id,
        kg=kg,
        template_name=template_name,
        **params,
    )


def close_kg_session(session_id: str) -> None:
    """Release the session-scoped graph and its cached query results."""
    if not session_id:
        raise ValueError("session_id is required when closing a KG session")
    get_kg_manager().remove_session(session_id)


__all__ = [
    "KGSessionSnapshot",
    "open_kg_session",
    "require_session_kg",
    "query_session_sparql",
    "query_session_template",
    "close_kg_session",
]
