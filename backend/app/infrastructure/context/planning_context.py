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

Dependency rule: this module MUST NOT import ``app.agent``
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
        input_documents: Runtime text working set resolved from bundle document
            refs; bodies are not persisted in the bundle snapshot.
        reports: Bundle-owned report manifest, ``{dim_key: {summary,
            instruction, report_id, layers: {L1/L2/L3: {...}}}}``. Report
            bodies are opened through the evidence/report retrieval boundary.
        report_summary_index: Layered report summaries keyed by dimension.
        l1_fact_records: Authoritative typed L1 facts; string reports are only
            a display projection and must not be the spatial source of truth.
        networks: Canonical typed network snapshots keyed by explicit relation
            refs; the current-road snapshot is built when the layer is present.
        demands: Typed demand snapshots keyed by explicit demand refs. An empty
            mapping is intentional until a producer supplies real demand points.
        location_facts: Typed L1 place mentions used by EvidenceGraph; these
            are not final candidate selections.
        evidence_graph: Session-scoped join boundary for L1, KG and bundle
            identity (may be None while context hydration is incomplete).
        external_search_port: Lifecycle-owned optional text evidence provider;
            it is never a geometry, BSM, or KG authority.
        ports: Typed ``PlanningPorts`` bundle of injected dependency-inversion
        port implementations (semantic_query, spatial_query, gazetteer,
            nomenclature_registry, context_provider). May be empty.
    """

    session_id: str = ""
    village_name: str = ""
    version: int = 1
    workspace: SpatialWorkspace | None = None
    data_snapshot: SessionDataSnapshot | None = None
    # Typed relation inputs.  These are immutable-by-convention snapshots
    # built from the authoritative workspace; prose counts never enter here.
    networks: Dict[str, Any] = field(default_factory=dict)
    demands: Dict[str, Any] = field(default_factory=dict)
    kg: Any = None
    kg_session_ref: str = ""
    kg_version: int = 0
    gazetteer: Any = None
    constraint_index: Any = None
    village_anchors: List[Dict[str, Any]] = field(default_factory=list)
    input_documents: List[Dict[str, Any]] = field(default_factory=list)
    reports: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    reports_loaded: bool = False
    report_summary_index: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    l1_snapshot_ref: str = ""
    l1_fact_records: List[Any] = field(default_factory=list)
    location_facts: List[Any] = field(default_factory=list)
    source_semantic_decisions: Dict[str, Any] = field(default_factory=dict)
    source_semantic_fingerprint: str = ""
    source_semantic_diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    evidence_graph: Any = None
    evidence_graph_key: str = ""
    external_search_port: Any = None
    grounded_anchors: List[Any] = field(default_factory=list)
    grounded_bindings: List[Any] = field(default_factory=list)
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
        for item in self.input_documents:
            if str(item.get("source", "")) == source:
                return str(item.get("content", "") or "")
        return default

    def input_texts(self) -> Dict[str, str]:
        """Return deduplicated planning inputs keyed by source and document type."""
        if self.workspace is None:
            return {}
        buckets: Dict[str, List[str]] = {}
        for item in self.input_documents:
            source = str(item.get("source", "") or "")
            content = str(item.get("content", "") or "").strip()
            if not content:
                continue
            keys = [source]
            for key in keys:
                if not key:
                    continue
                values = buckets.setdefault(key, [])
                if content not in values:
                    values.append(content)
        return {
            key: "\n\n".join(values)
            for key, values in buckets.items()
            if values
        }

    def snapshot_meta(self) -> Dict[str, Any]:
        """Serializable metadata for logs / step reports (no geometry)."""
        snapshot = self.data_snapshot
        source_manifest = []
        if snapshot is not None:
            source_manifest = [
                {
                    "key": item.key,
                    "feature_count": item.feature_count,
                    "source_uris": list(item.source_uris),
                    "source_feature_ids": list(item.source_feature_ids),
                    "source_feature_count": item.source_feature_count,
                    "source_feature_digest": item.source_feature_digest,
                }
                for item in snapshot.collections
                if item.source_feature_count or item.source_feature_digest
            ]
        return {
            "session_id": self.session_id,
            "village_name": self.village_name,
            "version": self.version,
            "kg_session_ref": self.kg_session_ref,
            "kg_version": self.kg_version,
            "has_workspace": self.has_workspace,
            "network_refs": sorted(str(key) for key in self.networks),
            "network_fingerprints": {
                str(key): str(getattr(value, "fingerprint", "") or "")
                for key, value in self.networks.items()
            },
            "demand_refs": sorted(str(key) for key in self.demands),
            "demand_fingerprints": {
                str(key): str(getattr(value, "fingerprint", "") or "")
                for key, value in self.demands.items()
            },
            "has_kg": self.has_kg,
            "has_gazetteer": self.gazetteer is not None,
            "has_constraint_index": self.constraint_index is not None,
            "has_evidence_graph": self.evidence_graph is not None,
            "evidence_graph_key": self.evidence_graph_key,
            "report_count": len(self.reports),
            "reports_loaded": self.reports_loaded,
            "location_fact_count": len(self.location_facts),
            "l1_fact_record_count": len(self.l1_fact_records),
            "source_semantic_decision_count": len(self.source_semantic_decisions),
            "source_semantic_fingerprint": self.source_semantic_fingerprint,
            "source_semantic_diagnostics": list(self.source_semantic_diagnostics),
            "grounded_binding_count": len(self.grounded_bindings),
            "l1_snapshot_ref": self.l1_snapshot_ref,
            "data_snapshot_id": snapshot.snapshot_id if snapshot is not None else "",
            "data_snapshot_digest": snapshot.digest if snapshot is not None else "",
            "source_feature_manifest": source_manifest,
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
