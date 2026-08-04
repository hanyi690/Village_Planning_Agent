"""PlanningContext - versioned, session-scoped fact authority.

Pure data container (no imports from agent/services/api). Holds the
single authoritative view of a planning session: the VillageBundle, the
session KG reference, the gazetteer, the constraint index and the report
summaries that the downstream EXPLORE/PARSE/GROUND/SELECT pipeline reads.

The context MAY additionally hold injected port implementations
(``artifact_store``, ``ports``) so downstream modules can consume services
without importing ``app.agent`` / ``app.services``, but it stays free of
those imports itself.

Versioning: ``version`` is bumped on every factory rebuild. Consumers that
cache derived geometry / query results must key on this version so a stale
context can never be mistaken for a fresh one.

Dependency rule: this module MUST NOT import ``app.agent``, ``app.services``
or ``app.api``. The async factory that *builds* a context lives in
``app.services.context``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.modules.ports.planning_ports import PlanningPorts


@dataclass
class PlanningContext:
    """Single versioned source of spatial/planning facts for one session.

    Attributes:
        session_id: Planning session identifier.
        village_name: Resolved village name (never the ``"jintian"`` fallback).
        version: Monotonic build version. Bumped on every rebuild.
        bundle: Session-scoped ``VillageBundle`` (may be None when not resolvable).
        kg: Live session ``PlanningKG`` instance (may be None).
        kg_session_ref: KG session key used by ``KGManager``.
        kg_version: KG mutation version (invalidates cached SPARQL results).
        gazetteer: Village gazetteer (may be None when not resolvable).
        constraint_index: ``ConstraintIndex`` built from the bundle (may be None).
        village_anchors: Pre-computed ``get_village_anchors`` rows.
        reports: Layer report content, ``{dim_key: {content, instruction, ...}}``.
        report_summary_index: ``{dim_key: {summary, metrics, key_points, ...}}``.
        kg_query_fn: Callable ``(template_name, **params) -> list[dict]`` bound
            to the live session KG. Used by ``spatial_ops`` without importing KG.
        ports: Typed ``PlanningPorts`` bundle of injected dependency-inversion
            port implementations (artifact_store, semantic_query, spatial_query,
            gazetteer, nomenclature_registry, context_provider). May be empty.
    """

    session_id: str = ""
    village_name: str = ""
    version: int = 1
    bundle: Any = None
    kg: Any = None
    kg_session_ref: str = ""
    kg_version: int = 0
    gazetteer: Any = None
    constraint_index: Any = None
    village_anchors: List[Dict[str, Any]] = field(default_factory=list)
    reports: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    report_summary_index: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    kg_query_fn: Optional[Callable[..., List[Dict[str, Any]]]] = None
    ports: PlanningPorts = field(default_factory=PlanningPorts)

    @property
    def has_bundle(self) -> bool:
        return self.bundle is not None

    @property
    def has_kg(self) -> bool:
        return self.kg is not None and self.kg_session_ref != ""

    @property
    def artifact_store(self) -> Any:
        """Back-compat accessor for the injected artifact store (or None)."""
        return self.ports.artifact_store if self.ports else None

    @property
    def has_bundle(self) -> bool:
        return self.bundle is not None

    @property
    def has_kg(self) -> bool:
        return self.kg is not None and self.kg_session_ref != ""

    def bundle_parcels(self) -> List[Any]:
        """Land-use parcels of the context bundle (typed objects)."""
        if self.bundle is None:
            return []
        return list(self.bundle.polygons.get("landuse_current") or [])

    def snapshot_meta(self) -> Dict[str, Any]:
        """Serializable metadata for logs / step reports (no geometry)."""
        return {
            "session_id": self.session_id,
            "village_name": self.village_name,
            "version": self.version,
            "kg_session_ref": self.kg_session_ref,
            "kg_version": self.kg_version,
            "has_bundle": self.has_bundle,
            "has_kg": self.has_kg,
            "has_gazetteer": self.gazetteer is not None,
            "has_constraint_index": self.constraint_index is not None,
            "report_count": len(self.reports),
        }


__all__ = ["PlanningContext"]