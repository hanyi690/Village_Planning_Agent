"""PlanningContext - versioned, session-scoped fact authority.

Pure data container (no imports from agent/services/api). Holds the
single authoritative view of a planning session: the VillageBundle, the
session KG reference, the gazetteer, the constraint index and the report
summaries that the downstream EXPLORE/PARSE/GROUND/SELECT pipeline reads.

The context may hold typed data/evidence ports, but artifact descriptors are
owned by workflow checkpoints and the CAS infrastructure; they are not
injected into this data context.

Versioning: ``version`` is bumped on every factory rebuild. Consumers that
cache derived geometry / query results must key on this version so a stale
context can never be mistaken for a fresh one.

Dependency rule: this module MUST NOT import ``app.agent``, ``app.services``
or ``app.api``. Lives in ``app.infrastructure.context`` (folded out of the
legacy ``app.modules`` context package in Phase 5). The async factory that
*builds* a context lives in ``app.infrastructure.context.planning_context_factory``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.data.model.snapshot import SessionDataSnapshot
from app.contracts.ports.planning_ports import PlanningPorts
from app.spatial.model.workspace import SpatialWorkspace


@dataclass
class PlanningContext:
    """Single versioned source of spatial/planning facts for one session.

    Attributes:
        session_id: Planning session identifier.
        village_name: Resolved village name (never the ``"jintian"`` fallback).
        version: Monotonic build version. Bumped on every rebuild.
        workspace: data-owned ``SpatialWorkspace`` (may be None when unavailable).
        kg: Live session ``PlanningKG`` instance (may be None).
        kg_session_ref: KG session key used by ``KGManager``.
        kg_version: KG mutation version (invalidates cached SPARQL results).
        gazetteer: Village gazetteer (may be None when not resolvable).
        constraint_index: ``ConstraintIndex`` built from the bundle (may be None).
        village_anchors: Pre-computed ``get_village_anchors`` rows.
        reports: Layer report content, ``{dim_key: {content, instruction, ...}}``.
        report_summary_index: ``{dim_key: {summary, metrics, key_points, ...}}``.
        location_facts: Typed L1 place mentions used by PlaceEvidenceIndex/
            GROUND; these are not final candidate selections.
        evidence_index: Pre-built ``PlaceEvidenceIndex`` snapshot (may be None
            when the evidence module or its inputs are unavailable).
        ports: Typed ``PlanningPorts`` bundle of injected dependency-inversion
        port implementations (semantic_query, spatial_query, gazetteer,
            nomenclature_registry, context_provider). May be empty.
    """

    session_id: str = ""
    village_name: str = ""
    version: int = 1
    workspace: SpatialWorkspace | None = None
    data_snapshot: SessionDataSnapshot | None = None
    kg: Any = None
    kg_session_ref: str = ""
    kg_version: int = 0
    gazetteer: Any = None
    constraint_index: Any = None
    village_anchors: List[Dict[str, Any]] = field(default_factory=list)
    reports: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    report_summary_index: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    l1_snapshot_ref: str = ""
    location_facts: List[Any] = field(default_factory=list)
    evidence_index: Any = None
    ports: PlanningPorts = field(default_factory=PlanningPorts)
    content_hash: str = ""
    capabilities: Dict[str, bool] = field(default_factory=dict)
    required_capabilities_missing: List[str] = field(default_factory=list)
    _content_inputs: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.capabilities:
            self._record_capabilities()
        if not self.content_hash:
            self._recompute_hash()

    @property
    def has_workspace(self) -> bool:
        return self.workspace is not None

    @property
    def has_kg(self) -> bool:
        return self.kg is not None and self.kg_session_ref != ""

    def current_parcels(self) -> List[Any]:
        """Current land-use parcels from the data-owned workspace."""
        if self.workspace is None:
            return []
        return self.workspace.current_parcels()

    def input_text(self, source: str, default: str = "") -> str:
        """Read one planning input from the data-owned workspace."""
        if self.workspace is None:
            return default
        for item in self.workspace.input_documents:
            if str(item.get("source", "")) == source:
                return str(item.get("content", "") or "")
        return default

    def input_texts(self) -> Dict[str, str]:
        """Return a source-keyed view of planning inputs without mutating state."""
        if self.workspace is None:
            return {}
        result: Dict[str, str] = {}
        for item in self.workspace.input_documents:
            source = str(item.get("source", "") or "")
            if source and source not in result:
                result[source] = str(item.get("content", "") or "")
        return result

    def snapshot_meta(self) -> Dict[str, Any]:
        """Serializable metadata for logs / step reports (no geometry)."""
        return {
            "session_id": self.session_id,
            "village_name": self.village_name,
            "version": self.version,
            "kg_session_ref": self.kg_session_ref,
            "kg_version": self.kg_version,
            "has_workspace": self.has_workspace,
            "has_kg": self.has_kg,
            "has_gazetteer": self.gazetteer is not None,
            "has_constraint_index": self.constraint_index is not None,
            "has_evidence_index": self.evidence_index is not None,
            "report_count": len(self.reports),
            "location_fact_count": len(self.location_facts),
            "l1_snapshot_ref": self.l1_snapshot_ref,
            "content_hash": self.content_hash,
            "capabilities": dict(self.capabilities),
            "required_capabilities_missing": list(self.required_capabilities_missing),
        }

    def _recompute_hash(self) -> None:
        payload = json.dumps(self._content_inputs, sort_keys=True, default=str)
        self.content_hash = hashlib.sha256(payload.encode()).hexdigest()

    def _record_capabilities(self) -> None:
        self.capabilities = {
            "data_snapshot": self.data_snapshot is not None,
            "workspace": self.workspace is not None,
            "kg": self.kg is not None,
            "gazetteer": self.gazetteer is not None,
            "constraint_index": self.constraint_index is not None,
            "reports": bool(self.reports),
        }


__all__ = ["PlanningContext"]
