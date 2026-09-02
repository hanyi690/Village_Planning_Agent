"""PlanningContext - versioned, session-scoped fact authority.

Pure data container (no imports from agent/services/api). Holds the
single authoritative view of a planning session: the DATA workspace/catalog,
the session KG reference, the gazetteer, the constraint index and the report
summaries that the downstream EXPLORE/PARSE/GROUND/SELECT pipeline reads.

The context may hold typed data/evidence ports, but artifact descriptors are
owned by workflow checkpoints and the CAS infrastructure; they are not
injected into this data context.

Versioning: ``version`` is bumped on every factory rebuild. Consumers that
cache derived geometry / query results must key on this version so a stale
context can never be mistaken for a fresh one.

Dependency rule: this module MUST NOT import ``app.agent``
or ``app.api``. Lives in ``app.infrastructure.context_runtime``. The async factory that
*builds* a context lives in ``app.infrastructure.context_runtime.manager``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.data.model.snapshot import SessionDataSnapshot
from app.contracts.ports.planning_ports import PlanningPorts
from app.contracts.cognition_round import CognitionRound
from app.spatial.model.workspace import SpatialWorkspace


@dataclass
class PlanningContext:
    """Single versioned source of spatial/planning facts for one session.

    Attributes:
        session_id: Planning session identifier.
        village_name: Resolved village name (never the ``"jintian"`` fallback).
        version: Monotonic build version. Bumped on every rebuild.
        workspace: data-owned ``SpatialWorkspace`` (may be None when unavailable).
        data_resource_catalog: Generic Data source/representation/capability
            index. The legacy Bundle remains private to the workspace.
        kg: Live session ``PlanningKG`` instance (may be None).
        world_model: DATA-backed ``WorldModelKGStore`` when a normalized
            catalog is available.  This is the cognition authority in V2;
            ``kg`` remains only the legacy compatibility projection in
            ``off``/``shadow`` migration modes.
        kg_session_ref: KG session key used by ``KGManager``.
        kg_version: KG mutation version (invalidates cached SPARQL results).
        gazetteer: Village gazetteer (may be None when not resolvable).
        constraint_index: Optional derived constraint index (may be None).
        input_documents: Runtime text working set resolved from admitted
        document artifacts; bodies are not copied into context metadata.
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
        location_mentions: Typed L1 place mentions used as Evidence inputs;
            these are not final candidate selections.
        external_search_port: Lifecycle-owned optional text evidence provider;
            it is never a geometry, BSM, or KG authority.
        external_observation_snapshot: Read-only normalized map observations
            loaded from local provider caches; these support names and
            location binding but never replace workspace geometry.
        ports: Typed ``PlanningPorts`` bundle of injected dependency-inversion
        port implementations (semantic_query, spatial_query, gazetteer,
            nomenclature_registry, context_provider). May be empty.
    """

    session_id: str = ""
    village_name: str = ""
    administrative_scope: Dict[str, str] = field(default_factory=dict)
    project_scope_bbox_wgs84: tuple[float, float, float, float] | None = None
    version: int = 1
    workspace: SpatialWorkspace | None = None
    data_resource_catalog: Any = None
    data_snapshot: SessionDataSnapshot | None = None
    boundary_scope_artifact: Any = None
    # Typed relation inputs.  These are immutable-by-convention snapshots
    # built from the authoritative workspace; prose counts never enter here.
    networks: Dict[str, Any] = field(default_factory=dict)
    demands: Dict[str, Any] = field(default_factory=dict)
    kg: Any = None
    world_model: Any = None
    cognition_round: CognitionRound | None = None
    kg_session_ref: str = ""
    kg_version: int = 0
    # Migration mode remains explicit for World Model rollout diagnostics.
    world_model_mode: str = "v2_only"
    # In shadow mode the V2 graph is built and written for comparison, while
    # the legacy KG remains the read authority until an explicit cutover.
    world_model_shadow: Any = None
    world_model_shadow_diff: Any = None
    world_model_shadow_diff_ref: str = ""
    gazetteer: Any = None
    constraint_index: Any = None
    input_documents: List[Dict[str, Any]] = field(default_factory=list)
    reports: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    reports_loaded: bool = False
    report_summary_index: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    l1_snapshot_ref: str = ""
    l1_world_projection_ref: str = ""
    l1_fact_records: List[Any] = field(default_factory=list)
    location_mentions: List[Any] = field(default_factory=list)
    # Read compatibility for persisted callers created before the contract
    # rename. New code should use location_mentions.
    location_facts: List[Any] = field(default_factory=list)
    source_semantic_decisions: Dict[str, Any] = field(default_factory=dict)
    source_semantic_fingerprint: str = ""
    source_semantic_diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    # Closed-set DATA schema understanding produced by Cognition.  This is a
    # bounded candidate/decision snapshot, never a raw nested prompt payload.
    schema_mapping_snapshot: Any = None
    external_search_port: Any = None
    external_observation_snapshot: Any = None
    grounding_unresolved: List[Dict[str, Any]] = field(default_factory=list)
    grounded_bindings: List[Any] = field(default_factory=list)
    ports: PlanningPorts = field(default_factory=PlanningPorts)
    content_hash: str = ""
    capabilities: Dict[str, bool] = field(default_factory=dict)
    required_capabilities_missing: List[str] = field(default_factory=list)
    _content_inputs: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.location_mentions:
            self.location_facts = self.location_mentions
        elif self.location_facts:
            self.location_mentions = self.location_facts
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
            "world_model_mode": self.world_model_mode,
            "world_model_snapshot_ref": str(
                getattr(self.world_model, "snapshot_ref", "")
                or getattr(self.kg, "snapshot_ref", "")
                or ""
            ),
            "world_model_snapshot_digest": str(
                getattr(self.world_model, "snapshot_digest", "")
                or getattr(self.kg, "snapshot_digest", "")
                or ""
            ),
            "world_model_shadow_snapshot_ref": str(
                getattr(self.world_model_shadow, "snapshot_ref", "") or ""
            ),
            "world_model_shadow_snapshot_digest": str(
                getattr(self.world_model_shadow, "snapshot_digest", "") or ""
            ),
            "world_model_shadow_diff_digest": str(
                getattr(self.world_model_shadow_diff, "digest", "") or ""
            ),
            "world_model_shadow_diff_ref": self.world_model_shadow_diff_ref,
            "has_workspace": self.has_workspace,
            "has_data_resource_catalog": self.data_resource_catalog is not None,
            "data_resource_catalog_digest": str(
                getattr(self.data_resource_catalog, "snapshot", None)
                and getattr(getattr(self.data_resource_catalog, "snapshot", None), "digest", "")
                or ""
            ),
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
            "has_world_model": self.world_model is not None,
            "has_gazetteer": self.gazetteer is not None,
            "has_constraint_index": self.constraint_index is not None,
            "has_external_observations": self.external_observation_snapshot is not None,
            "external_observation_digest": str(
                getattr(self.external_observation_snapshot, "digest", "") or ""
            ),
            "external_observation_count": len(
                getattr(self.external_observation_snapshot, "observations", []) or []
            ),
            "external_observation_providers": sorted({
                str(getattr(item, "provider", "") or "")
                for item in (getattr(self.external_observation_snapshot, "observations", []) or [])
                if str(getattr(item, "provider", "") or "")
            }),
            "report_count": len(self.reports),
            "reports_loaded": self.reports_loaded,
            "location_mention_count": len(self.location_mentions),
            "l1_fact_record_count": len(self.l1_fact_records),
            "source_semantic_decision_count": len(self.source_semantic_decisions),
            "source_semantic_fingerprint": self.source_semantic_fingerprint,
            "source_semantic_diagnostics": list(self.source_semantic_diagnostics),
            "grounded_binding_count": len(self.grounded_bindings),
            "l1_snapshot_ref": self.l1_snapshot_ref,
            "data_snapshot_id": snapshot.snapshot_id if snapshot is not None else "",
            "data_snapshot_digest": snapshot.digest if snapshot is not None else "",
            "boundary_scope_ref": str(
                getattr(self.boundary_scope_artifact, "scope_ref", "") or ""
            ),
            "boundary_digest": str(
                getattr(self.boundary_scope_artifact, "boundary_digest", "") or ""
            ),
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
            "data_resource_catalog": self.data_resource_catalog is not None,
            "kg": self.kg is not None,
            "world_model": self.world_model is not None,
            "world_model_shadow": self.world_model_shadow is not None,
            "current_world": getattr(self.ports, "current_world", None) is not None,
            "network_retry": getattr(self.ports, "network_retry", None) is not None,
            "world_model_commit": getattr(self.ports, "world_model_commit", None) is not None,
            "cognition_commit": getattr(self.ports, "cognition_commit", None) is not None,
            "gazetteer": self.gazetteer is not None,
            "constraint_index": self.constraint_index is not None,
            "reports": bool(self.reports),
            "external_observations": self.external_observation_snapshot is not None,
        }


__all__ = ["PlanningContext"]
