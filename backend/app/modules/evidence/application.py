"""Business-owned Evidence facade.

Stage modules declare requirements and scope here.  Retrieval planning,
provider routing, source access, fusion, caching and degradation stay inside
``infrastructure.evidence_runtime``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.evidence.stage_contracts import (
    EvidenceExternalObservationSnapshot,
    EvidenceGapLedger,
    EvidenceGapScheduleRecord,
    EvidenceStageSnapshot,
)
from app.contracts.evidence.evidence_contracts import (
    ExplorationRequest,
    ExplorationResult,
)
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.contracts.evidence.provider_attempt import (
    EvidenceAuthority,
    EvidenceConfidence,
    ProviderAttempt,
    provider_attempt_from_legacy,
)
from app.contracts.evidence.retrieval_artifact_contracts import (
    EvidenceRetrievalArtifact,
)
from app.contracts.evidence.retrieval_contracts import (
    EvidenceRetrievalAuthority,
    EvidenceRetrievalBootstrapRefs,
    EvidenceRetrievalOutcome,
)
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.infrastructure.artifacts.runtime import (
    ArtifactReplayError,
    load_artifact,
    load_embedded_artifact,
    store_artifact,
)
from app.infrastructure.paths import run_tmp_root
from app.workflow.stage_adapter import persist_gate_decision
from app.contracts.workflow.workflow_contracts import GateDecision, PendingRequest


def _external_cache_scope(
    state: Mapping[str, Any],
    context: Any = None,
) -> tuple[dict[str, str], tuple[float, float, float, float] | None]:
    """Resolve cache scope without inventing administrative defaults."""

    config = state.get("config") or {}
    inherited = dict(getattr(context, "administrative_scope", {}) or {})
    fields = {
        "province": str(config.get("province") or state.get("province") or "").strip(),
        "city": str(config.get("city") or state.get("city") or "").strip(),
        "county": str(config.get("county") or state.get("county") or "").strip(),
        "township": str(config.get("township") or state.get("township") or "").strip(),
        "village": str(
            config.get("village_name") or state.get("village_name") or ""
        ).strip(),
    }
    inherited.update({key: value for key, value in fields.items() if value})
    bbox_value = (
        getattr(context, "project_scope_bbox_wgs84", None)
        if context is not None
        else None
    ) or state.get("project_scope_bbox_wgs84")
    bbox = None
    if isinstance(bbox_value, (list, tuple)) and len(bbox_value) == 4:
        try:
            bbox = tuple(float(value) for value in bbox_value)
        except (TypeError, ValueError):
            bbox = None
    return inherited, bbox


def _frozen_external_snapshot(
    value: Any,
    *,
    project_name: str,
) -> Any:
    """Remove cache-local paths before freezing observations into Evidence CAS."""

    from app.contracts.evidence.external_observation_contracts import (
        ExternalObservationSnapshot,
    )

    if value is None:
        return ExternalObservationSnapshot(snapshot_id="", project_name=project_name)
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)
    provider_runs = []
    for row in payload.get("provider_runs") or []:
        item = dict(row) if isinstance(row, Mapping) else {}
        for key in ("path", "cache_directory", "raw_response_directory"):
            item.pop(key, None)
        provider_runs.append(item)
    payload["provider_runs"] = provider_runs
    from app.contracts.evidence.provider_attempt import provider_attempt_from_legacy

    typed_attempts = tuple(
        getattr(value, "model_dump", lambda **_: value)()
        if hasattr(value, "model_dump")
        else value
        for value in (payload.get("provider_attempts") or ())
    )
    if not typed_attempts:
        typed_attempts = tuple(
            provider_attempt_from_legacy(row).model_dump(mode="json")
            for row in provider_runs
        )
    payload["provider_attempts"] = typed_attempts
    payload["snapshot_id"] = ""
    payload["digest"] = ""
    # Cache collection time is not Evidence input semantics.  The cache
    # digest below preserves provider/observation business timestamps while a
    # fixed wrapper timestamp keeps this child CAS payload write-once.
    payload["created_at"] = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return ExternalObservationSnapshot.model_validate(payload)


_EVIDENCE_AUTHORITY_OUTPUT_KEYS = frozenset({
    "evidence_snapshot",
    "evidence_external_observations",
    "evidence_gap_ledger",
})
_EVIDENCE_FROZEN_UPSTREAM_KEYS = (
    ("data_catalog_artifact_ref", "data_catalog"),
    ("data_snapshot_artifact_ref", "data_snapshot"),
    ("world_model_artifact_ref", "world_model_snapshot"),
)


def _assert_ref_identity(
    frozen: ArtifactRef | None,
    active: Any,
    *,
    name: str,
) -> ArtifactRef:
    """Require a frozen and active descriptor to identify the same blob."""

    if frozen is None or active is None:
        raise ArtifactReplayError(
            f"Evidence authority is missing frozen/active ref: {name}"
        )
    try:
        active_ref = ArtifactRef.model_validate(active)
    except Exception as exc:
        raise ArtifactReplayError(
            f"Evidence authority has invalid active ref: {name}"
        ) from exc
    for field in ("descriptor_digest", "digest", "semantic_digest"):
        if getattr(frozen, field) != getattr(active_ref, field):
            raise ArtifactReplayError(
                f"Evidence authority ref identity mismatch: {name}.{field}"
            )
    return active_ref


def _validate_evidence_checkpoint_authority(
    state: Mapping[str, Any],
    snapshot: EvidenceStageSnapshot | None,
    snapshot_ref: ArtifactRef | None,
    artifact_refs: Mapping[str, Any],
) -> ArtifactRef:
    """Validate the complete Evidence bootstrap before any retrieval CAS use."""

    if snapshot is None or snapshot.status != "ready":
        raise ArtifactReplayError(
            "Evidence retrieval requires a ready EvidenceStageSnapshot"
        )
    if snapshot_ref is None:
        raise ArtifactReplayError("Evidence retrieval requires evidence_snapshot ref")
    active_snapshot = _assert_ref_identity(
        snapshot_ref,
        artifact_refs.get("evidence_snapshot"),
        name="evidence_snapshot",
    )
    for frozen_field, active_key in _EVIDENCE_FROZEN_UPSTREAM_KEYS:
        _assert_ref_identity(
            getattr(snapshot, frozen_field),
            artifact_refs.get(active_key),
            name=active_key,
        )
    from app.contracts.cognition.snapshot import SessionWorldModelSnapshot
    from app.data.model.snapshot import SessionDataSnapshot

    from app.modules.data.application import DataApplication

    catalog = DataApplication.load_catalog(dict(state))
    data = load_artifact(dict(state), "data_snapshot", SessionDataSnapshot)
    world = load_artifact(
        dict(state), "world_model_snapshot", SessionWorldModelSnapshot
    )
    if catalog is None or data is None or world is None:
        raise ArtifactReplayError(
            "Evidence retrieval upstream artifacts could not be reloaded"
        )
    business_checks = {
        "source_catalog_digest": (
            snapshot.source_catalog_digest,
            str(getattr(catalog, "digest", "") or ""),
        ),
        "data_snapshot_digest": (
            snapshot.data_snapshot_digest,
            str(getattr(data, "digest", "") or ""),
        ),
        "world_model_snapshot_digest": (
            snapshot.world_model_snapshot_digest,
            str(getattr(world, "graph_digest", "") or ""),
        ),
    }
    for name, (declared, actual) in business_checks.items():
        if not declared or declared != actual:
            raise ArtifactReplayError(
                f"Evidence authority business digest mismatch: {name}"
            )
    for frozen_field, active_key in (
        ("external_observations_ref", "evidence_external_observations"),
        ("gap_ledger_ref", "evidence_gap_ledger"),
    ):
        frozen = getattr(snapshot, frozen_field)
        _assert_ref_identity(frozen, artifact_refs.get(active_key), name=active_key)

    # load_root_gate performs blob/context validation and binds each gate
    # parent digest to the active checkpoint ref.  The stricter set check here
    # prevents an Evidence gate from being treated as authoritative when it
    # happens to bind only a subset of the three Evidence products.
    from app.workflow.state import load_root_gate

    try:
        gate = load_root_gate(dict(state), "evidence")
        gate_ref = ArtifactRef.model_validate(
            dict(artifact_refs).get("evidence_gate")
        )
    except Exception as exc:
        raise ArtifactReplayError(
            "Evidence retrieval requires a reloadable evidence gate"
        ) from exc
    if not gate.passed or gate.feedback_route not in (None, "", "PASS"):
        raise ArtifactReplayError(
            "Evidence gate is not PASS-authoritative for retrieval"
        )
    if list(gate.pending_requests or []):
        raise ArtifactReplayError(
            "Evidence gate has pending requests; retrieval authority is blocked"
        )
    if list(gate.evidence_requests or []):
        raise ArtifactReplayError(
            "Evidence gate has unresolved runtime evidence requests"
        )
    if set(gate_ref.parent_digests) != _EVIDENCE_AUTHORITY_OUTPUT_KEYS:
        raise ArtifactReplayError(
            "Evidence gate does not bind exactly the three Evidence artifacts"
        )
    for key in _EVIDENCE_AUTHORITY_OUTPUT_KEYS:
        active = ArtifactRef.model_validate(dict(artifact_refs).get(key))
        if gate_ref.parent_digests.get(key) != active.digest:
            raise ArtifactReplayError(
                f"Evidence gate parent binding mismatch: {key}"
            )
    return gate_ref


class EvidenceContext(BaseModel):
    """Minimal stage context accepted by the evidence business boundary."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    session_id: str = Field(min_length=1)
    village_name: str = ""
    # ``run_id`` is the request/correlation identity; workflow authority is
    # deliberately separate so request retries cannot impersonate a run.
    run_id: str = ""
    workflow_run_id: str = ""
    branch_id: str = "main"
    context_version: str = ""
    context_fingerprint: str = ""
    artifact_root: str = ""
    artifact_refs: dict[str, ArtifactRef] = Field(default_factory=dict)
    evidence_snapshot: EvidenceStageSnapshot | None = None
    evidence_snapshot_ref: ArtifactRef | None = None
    external_observations_ref: ArtifactRef | None = None
    gap_ledger_ref: ArtifactRef | None = None
    evidence_gate_ref: ArtifactRef | None = None
    evidence_gate_verified: bool = False
    replay_status: str = "unbound"
    external_cache_only: bool = True
    stage: str = ""
    dimension_key: str = ""
    purpose: str = ""
    request_type: str = "evidence_gap"
    project_wide: bool = False
    context_refs: tuple[str, ...] = ()
    available_capabilities: tuple[str, ...] = ()
    available_sources: tuple[str, ...] = ()
    world_model_mode: str = "off"
    data_catalog: Any = None
    external_observation_snapshot: Any = None
    world_model: Any = None
    world_model_shadow: Any = None
    kg: Any = None
    kg_version: str = ""
    l1_snapshot_ref: str = ""

    @classmethod
    def from_state(
        cls,
        state: Mapping[str, Any],
        *,
        stage: str = "",
        purpose: str = "",
        request_type: str = "evidence_gap",
    ) -> "EvidenceContext":
        config = state.get("config") or {}
        session_id = str(state.get("session_id") or "")
        workflow_run_id = str(state.get("run_id") or session_id)
        branch_id = str(state.get("branch_id") or "main")
        artifact_root = str(state.get("artifact_root") or "")
        try:
            artifact_refs = {
                str(key): ArtifactRef.model_validate(value)
                for key, value in dict(state.get("artifact_refs") or {}).items()
                if value
            }
        except Exception as exc:
            raise ArtifactReplayError("EvidenceContext received invalid artifact refs") from exc
        evidence_snapshot = load_artifact(
            dict(state),
            "evidence_snapshot",
            EvidenceStageSnapshot,
        )
        state_context_version = str(state.get("context_version") or "")
        state_context_fingerprint = str(state.get("context_fingerprint") or "")
        if (
            evidence_snapshot is not None
            and state_context_version
            and state_context_version != evidence_snapshot.context_version
        ):
            raise ArtifactReplayError("Evidence checkpoint context version mismatch")
        if (
            evidence_snapshot is not None
            and state_context_fingerprint
            and state_context_fingerprint != evidence_snapshot.context_fingerprint
        ):
            raise ArtifactReplayError("Evidence checkpoint context fingerprint mismatch")
        evidence_snapshot_ref = artifact_refs.get("evidence_snapshot")
        evidence_gate_ref = None
        evidence_gate_verified = False
        external_observations_ref = (
            evidence_snapshot.external_observations_ref
            if evidence_snapshot is not None
            else None
        )
        gap_ledger_ref = (
            evidence_snapshot.gap_ledger_ref
            if evidence_snapshot is not None
            else None
        )
        if evidence_snapshot is not None:
            evidence_gate_ref = _validate_evidence_checkpoint_authority(
                state,
                evidence_snapshot,
                evidence_snapshot_ref,
                artifact_refs,
            )
            evidence_gate_verified = True
        external_snapshot = None
        replay_status = "legacy_checkpoint"
        if evidence_snapshot is not None and (
            external_observations_ref is not None and gap_ledger_ref is not None
        ):
            frozen_external = load_embedded_artifact(
                dict(state),
                external_observations_ref.model_dump(mode="json"),
                EvidenceExternalObservationSnapshot,
            )
            gap_ledger = load_embedded_artifact(
                dict(state),
                gap_ledger_ref.model_dump(mode="json"),
                EvidenceGapLedger,
            )
            if frozen_external is None or gap_ledger is None:
                raise ArtifactReplayError("Evidence bootstrap child artifacts are unavailable")
            if (
                frozen_external.cache_digest != evidence_snapshot.external_cache_digest
                or frozen_external.snapshot.digest != frozen_external.cache_digest
                or tuple(frozen_external.provider_attempts)
                != tuple(evidence_snapshot.provider_attempts)
                or tuple(frozen_external.snapshot.provider_attempts)
                != tuple(frozen_external.provider_attempts)
            ):
                raise ArtifactReplayError(
                    "Evidence external observation digest authority mismatch"
                )
            if (
                gap_ledger.source_catalog_digest
                != evidence_snapshot.source_catalog_digest
                or gap_ledger.world_model_snapshot_digest
                != evidence_snapshot.world_model_snapshot_digest
                or tuple(gap_ledger.gap_rows) != tuple(evidence_snapshot.gap_rows)
            ):
                raise ArtifactReplayError("Evidence gap ledger authority mismatch")
            external_snapshot = frozen_external.snapshot
            context_version = str(
                state.get("context_version") or evidence_snapshot.context_version or ""
            )
            context_fingerprint = str(
                state.get("context_fingerprint")
                or evidence_snapshot.context_fingerprint
                or ""
            )
            replay_status = (
                "bound"
                if all((
                    workflow_run_id,
                    branch_id,
                    artifact_root,
                    context_version,
                    context_fingerprint,
                    evidence_snapshot_ref,
                    artifact_refs.get("data_catalog"),
                    artifact_refs.get("data_snapshot"),
                    artifact_refs.get("world_model_snapshot"),
                ))
                else "unbound_checkpoint"
            )
        else:
            context_version = str(state.get("context_version") or "")
            context_fingerprint = str(state.get("context_fingerprint") or "")
        data_catalog = state.get("data_catalog")
        cached_context = None
        if session_id:
            # Workflow checkpoints intentionally carry artifact refs rather
            # than live DATA objects.  Recover the immutable catalog from the
            # session Context Runtime so V2-authoritative stages cannot silently fall
            # back to the legacy retriever just because the checkpoint is
            # reference-only.
            try:
                from app.infrastructure.context_runtime.manager import get_cached_context

                cached_context = get_cached_context(session_id)
                if data_catalog is None:
                    data_catalog = getattr(cached_context, "data_resource_catalog", None)
            except Exception:
                cached_context = None
        if data_catalog is None:
            try:
                from app.data.resource_catalog import DataResourceCatalog
                from app.modules.data.application import DataApplication

                catalog_snapshot = DataApplication.load_catalog(dict(state))
                if catalog_snapshot is not None:
                    data_catalog = DataResourceCatalog(catalog_snapshot)
            except Exception:
                data_catalog = None
        world_model_mode = str(state.get("world_model_mode") or "").strip()
        if not world_model_mode and cached_context is not None:
            world_model_mode = str(
                getattr(cached_context, "world_model_mode", "off") or "off"
            )
        world_model_mode = world_model_mode or "off"
        capabilities = {
            str(item).strip()
            for item in state.get("available_capabilities") or ()
            if str(item).strip()
        }
        sources = {
            str(item).strip()
            for item in state.get("available_sources") or ()
            if str(item).strip()
        }
        catalog_snapshot = getattr(data_catalog, "snapshot", data_catalog)
        if catalog_snapshot is not None:
            from app.data.admission import (
                assert_current_world_catalog,
                build_admission_index,
                is_admitted_capability,
                is_admitted_representation,
            )

            try:
                assert_current_world_catalog(catalog_snapshot)
                admission_index = build_admission_index(catalog_snapshot)
            except (TypeError, ValueError):
                catalog_snapshot = None
                data_catalog = None
        if catalog_snapshot is not None:
            sources.update({"data", "gis", "artifact"})
            capabilities.add("source_evidence")
            for item in getattr(catalog_snapshot, "capabilities", ()) or ():
                if not is_admitted_capability(
                    catalog_snapshot, item, index=admission_index
                ):
                    continue
                operation = str(getattr(item, "operation", "") or "").strip()
                if operation:
                    capabilities.add(operation)
            if any(
                is_admitted_representation(
                    catalog_snapshot, item, index=admission_index
                )
                and
                str(getattr(item, "status", "") or "") == "available"
                and str(getattr(item, "geometry_kind", "") or "")
                in {"point", "line", "polygon", "multipatch"}
                for item in getattr(catalog_snapshot, "representations", ()) or ()
            ):
                capabilities.update({"local_spatial_evidence", "metric_source"})
        world_model = state.get("world_model")
        if world_model is None and cached_context is not None:
            world_model = (
                getattr(cached_context, "world_model", None)
                or getattr(cached_context, "world_model_shadow", None)
                or getattr(cached_context, "kg", None)
            )
        if data_catalog is not None and session_id:
            try:
                from app.contracts.cognition.snapshot import (
                    SessionWorldModelSnapshot,
                )
                from app.contracts.cognition.decision import (
                    SourceSemanticMappingSnapshot,
                )
                from app.infrastructure.cognition_runtime.world_model_store import (
                    get_world_model_store,
                )

                expected_world = load_artifact(
                    dict(state),
                    "world_model_snapshot",
                    SessionWorldModelSnapshot,
                )
                schema_mapping = load_artifact(
                    dict(state),
                    "schema_mapping_snapshot",
                    SourceSemanticMappingSnapshot,
                )
                mapping_ref_value = dict(
                    (state.get("artifact_refs") or {}).get(
                        "schema_mapping_snapshot"
                    )
                    or {}
                )
                expected_digest = str(
                    getattr(expected_world, "graph_digest", "") or ""
                )
                live_digest = str(
                    getattr(world_model, "snapshot_digest", "")
                    or getattr(world_model, "graph_digest", "")
                    or ""
                )
                if world_model is None or (
                    expected_digest and expected_digest != live_digest
                ):
                    candidate_world = get_world_model_store(
                        session_id,
                        str(
                            (state.get("config") or {}).get("village_name")
                            or state.get("village_name")
                            or ""
                        ),
                        data_catalog,
                        schema_mapping_snapshot=schema_mapping,
                        schema_mapping_artifact_ref=str(
                            mapping_ref_value.get("descriptor_digest") or ""
                        ),
                        artifact_root=str(state.get("artifact_root") or ""),
                        expected_snapshot_digest=expected_digest,
                    )
                    if (
                        expected_digest
                        and expected_digest
                        != str(
                            getattr(candidate_world, "snapshot_digest", "") or ""
                        )
                    ):
                        candidate_world = None
                    world_model = candidate_world
            except Exception:
                world_model = None
        if world_model is not None:
            sources.add("kg")
            capabilities.update({"identity_evidence", "source_evidence"})
        reports = state.get("reports")
        if reports is None and cached_context is not None:
            reports = getattr(cached_context, "reports", None)
        if reports:
            sources.update({"text", "report"})
            capabilities.add("source_evidence")
        if cached_context is not None and getattr(cached_context, "bundle", None) is not None:
            sources.add("bundle")
        # A persisted Evidence snapshot is historical authority.  Reload its
        # child ref above and never replace it with a newer cache scan after a
        # worker restart.  Only legacy checkpoints without that snapshot use
        # the compatibility cache path, and they remain explicitly unbound.
        if evidence_snapshot is None:
            external_snapshot = state.get("external_observation_snapshot")
        if evidence_snapshot is None and external_snapshot is None and cached_context is not None:
            external_snapshot = getattr(
                cached_context,
                "external_observation_snapshot",
                None,
            )
        if evidence_snapshot is None and external_snapshot is None:
            try:
                from app.data.catalog.external_observation_cache import (
                    load_cached_external_observation_snapshot,
                )

                administrative_scope, project_bbox = _external_cache_scope(
                    state,
                    cached_context,
                )
                external_snapshot = load_cached_external_observation_snapshot(
                    project_name=str(
                        (state.get("config") or {}).get("village_name")
                        or state.get("village_name")
                        or ""
                    ),
                    administrative_scope=administrative_scope,
                    project_bbox_wgs84=project_bbox,
                )
            except Exception:
                external_snapshot = None
        if external_snapshot is not None and (
            getattr(external_snapshot, "provider_runs", None)
            or getattr(external_snapshot, "observations", None)
        ):
            sources.update({"external", "external_map_cache"})
            capabilities.update({"identity_evidence", "source_evidence"})
        return cls(
            session_id=session_id,
            village_name=str(config.get("village_name") or state.get("village_name") or ""),
            run_id=str(
                state.get("evidence_request_run_id")
                or state.get("request_run_id")
                or workflow_run_id
            ),
            workflow_run_id=workflow_run_id,
            branch_id=branch_id,
            context_version=context_version,
            context_fingerprint=context_fingerprint,
            artifact_root=artifact_root,
            artifact_refs=artifact_refs,
            evidence_snapshot=evidence_snapshot,
            evidence_snapshot_ref=evidence_snapshot_ref,
            external_observations_ref=external_observations_ref,
            gap_ledger_ref=gap_ledger_ref,
            evidence_gate_ref=evidence_gate_ref,
            evidence_gate_verified=evidence_gate_verified,
            replay_status=replay_status,
            stage=stage or str(state.get("active_stage") or ""),
            dimension_key=str(state.get("dimension_key") or ""),
            purpose=purpose,
            request_type=request_type,
            project_wide=bool(state.get("project_wide_evidence")),
            context_refs=tuple(str(item) for item in state.get("context_refs") or () if str(item)),
            available_capabilities=tuple(sorted(capabilities)),
            available_sources=tuple(sorted(sources)),
            world_model_mode=world_model_mode,
            data_catalog=data_catalog,
            external_observation_snapshot=external_snapshot,
            world_model=world_model,
            world_model_shadow=(
                state.get("world_model_shadow")
                or (
                    getattr(cached_context, "world_model_shadow", None)
                    if cached_context is not None
                    else None
                )
            ),
            kg=(
                state.get("kg")
                or (
                    getattr(cached_context, "kg", None)
                    if cached_context is not None
                    else None
                )
            ),
            kg_version=str(
                state.get("kg_version")
                or (
                    getattr(cached_context, "kg_version", "")
                    if cached_context is not None
                    else ""
                )
                or ""
            ),
            l1_snapshot_ref=str(
                state.get("l1_snapshot_ref")
                or (
                    getattr(cached_context, "l1_snapshot_ref", "")
                    if cached_context is not None
                    else ""
                )
                or ""
            ),
        )

    @classmethod
    def from_runtime_context(
        cls,
        context: Any,
        *,
        session_id: str,
        stage: str,
        purpose: str,
        request_type: str = "evidence_gap",
        run_id: str = "",
        dimension_key: str = "",
        context_refs: Iterable[str] = (),
        state_authority: Mapping[str, Any] | None = None,
    ) -> "EvidenceContext":
        """Project one PlanningContext through the single Evidence boundary."""

        state = {
            **dict(state_authority or {}),
            "session_id": session_id,
            "run_id": str(
                (state_authority or {}).get("run_id") or session_id
            ),
            "active_stage": stage,
            "dimension_key": dimension_key,
            "context_refs": tuple(context_refs),
            "village_name": str(getattr(context, "village_name", "") or ""),
            "world_model_mode": str(
                getattr(context, "world_model_mode", "off") or "off"
            ),
            "data_catalog": getattr(context, "data_resource_catalog", None),
            "external_observation_snapshot": getattr(
                context,
                "external_observation_snapshot",
                None,
            ),
            "world_model": getattr(context, "world_model", None),
            "world_model_shadow": getattr(context, "world_model_shadow", None),
            "kg": getattr(context, "kg", None),
            "kg_version": str(getattr(context, "kg_version", "") or ""),
            "l1_snapshot_ref": str(
                getattr(context, "l1_snapshot_ref", "") or ""
            ),
            "reports": getattr(context, "reports", None),
        }
        result = cls.from_state(
            state,
            stage=stage,
            purpose=purpose,
            request_type=request_type,
        )
        return result.model_copy(
            update={
                "run_id": run_id or session_id,
                "dimension_key": dimension_key,
                "context_refs": tuple(str(item) for item in context_refs if str(item)),
                "replay_status": (
                    result.replay_status
                    if state_authority is not None
                    else "unbound_runtime_context"
                ),
            }
        )

    def retrieval_authority(self) -> EvidenceRetrievalAuthority:
        """Build the authority record required before a retrieval can replay."""

        if self.replay_status != "bound":
            raise ArtifactReplayError(
                "Evidence retrieval is unbound; provide checkpoint authority before CAS replay"
            )
        if not self.evidence_gate_verified or self.evidence_gate_ref is None:
            raise ArtifactReplayError(
                "Evidence retrieval gate authority was not verified"
            )
        snapshot = self.evidence_snapshot
        required_refs = {
            "data_catalog": self.artifact_refs.get("data_catalog"),
            "data_snapshot": self.artifact_refs.get("data_snapshot"),
            "world_model_snapshot": self.artifact_refs.get("world_model_snapshot"),
            "evidence_snapshot": self.evidence_snapshot_ref,
            "external_observations": self.external_observations_ref,
            "gap_ledger": self.gap_ledger_ref,
        }
        if snapshot is None or any(value is None for value in required_refs.values()):
            raise ArtifactReplayError("Evidence retrieval bootstrap refs are incomplete")
        for name, ref in required_refs.items():
            if ref.run_id != self.workflow_run_id or ref.branch_id != self.branch_id:
                raise ArtifactReplayError(
                    f"Evidence retrieval authority ref is outside the active branch: {name}"
                )
        return EvidenceRetrievalAuthority(
            session_id=self.session_id,
            workflow_run_id=self.workflow_run_id,
            branch_id=self.branch_id,
            context_version=self.context_version,
            context_fingerprint=self.context_fingerprint,
            data_catalog_ref=required_refs["data_catalog"],
            data_catalog_digest=snapshot.source_catalog_digest,
            data_snapshot_ref=required_refs["data_snapshot"],
            data_snapshot_digest=snapshot.data_snapshot_digest,
            world_model_artifact_ref=required_refs["world_model_snapshot"],
            world_model_snapshot_ref=snapshot.world_model_snapshot_ref,
            world_model_snapshot_digest=snapshot.world_model_snapshot_digest,
            evidence_snapshot_ref=required_refs["evidence_snapshot"],
            external_observations_ref=required_refs["external_observations"],
            external_cache_digest=snapshot.external_cache_digest,
            gap_ledger_ref=required_refs["gap_ledger"],
            world_model_mode=self.world_model_mode,
            cache_only_policy={"external": self.external_cache_only},
        )


class EvidenceRunResult(BaseModel):
    """Typed evidence readiness product after the DATA/KG bootstrap."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    snapshot: EvidenceStageSnapshot
    snapshot_ref: ArtifactRef
    external_observations_ref: ArtifactRef
    gap_ledger_ref: ArtifactRef
    gate_ref: ArtifactRef
    state_patch: dict[str, Any] = Field(default_factory=dict)

    def to_state_patch(self) -> dict[str, Any]:
        patch = dict(self.state_patch)
        patch["artifact_refs"] = {
            **dict(patch.get("artifact_refs") or {}),
            "evidence_snapshot": self.snapshot_ref.model_dump(mode="json"),
            "evidence_external_observations": self.external_observations_ref.model_dump(mode="json"),
            "evidence_gap_ledger": self.gap_ledger_ref.model_dump(mode="json"),
            "evidence_gate": self.gate_ref.model_dump(mode="json"),
        }
        return patch


def _as_requirements(
    requirement: EvidenceRequirement | Iterable[EvidenceRequirement],
) -> tuple[EvidenceRequirement, ...]:
    if isinstance(requirement, EvidenceRequirement):
        return (requirement,)
    return tuple(requirement)


def _request_for(
    requirements: tuple[EvidenceRequirement, ...],
    context: EvidenceContext,
    *,
    candidate_offset: int = 0,
    candidate_limit: int = 12,
) -> ExplorationRequest:
    if not requirements:
        raise ValueError("EvidenceFacade requires at least one EvidenceRequirement")
    spatial = any(item.kind == "spatial" or item.scope for item in requirements)
    request_type = context.request_type or ("spatial_lookup" if spatial else "evidence_gap")
    return ExplorationRequest(
        run_id=context.run_id or context.session_id,
        request_type=request_type,
        query="; ".join(item.statement for item in requirements),
        context_refs=list(context.context_refs),
        stage=context.stage,
        dimension_key=context.dimension_key,
        query_purpose=context.purpose,
        entity_scope=list(dict.fromkeys(
            scope for item in requirements for scope in item.scope
        )),
        project_wide=context.project_wide,
        candidate_offset=candidate_offset,
        candidate_limit=candidate_limit,
        requirements=list(requirements),
    )


def _scheduled_gap_result(
    requirements: tuple[EvidenceRequirement, ...],
    schedule_trace: Mapping[str, Any],
) -> ExplorationResult:
    """Return an explicit no-retrieval result for deferred/unavailable gaps."""

    from app.contracts.evidence.evidence_contracts import EvidenceBundle
    from app.contracts.evidence.evidence_packet_contracts import EvidencePacket

    unresolved = [
        item.requirement_id
        for item in requirements
        if item.gap_status != "resolved"
    ]
    request_text = "; ".join(item.statement for item in requirements)
    return ExplorationResult(
        evidence_bundle=EvidenceBundle(
            request=request_text,
            facts=[],
            sources=[],
            confidence=0.0,
            unresolved=unresolved,
        ),
        evidence_packet=EvidencePacket(
            request=request_text,
            candidate_total=0,
            ambiguity_status="unresolved",
            sufficiency="insufficient" if unresolved else "sufficient",
            missing_evidence=unresolved,
            query_trace=[dict(schedule_trace)],
        ),
    )


def _append_scheduled_gaps(
    result: ExplorationResult,
    requirements: tuple[EvidenceRequirement, ...],
    schedule_trace: Mapping[str, Any],
) -> ExplorationResult:
    """Keep non-actionable gaps visible beside a bounded retrieval result."""

    unresolved = [
        item.requirement_id
        for item in requirements
        if item.gap_status not in {"resolved", "ready_for_retrieval", "retrieving"}
    ]
    bundle = result.evidence_bundle.model_copy(deep=True)
    bundle.unresolved = list(dict.fromkeys([*bundle.unresolved, *unresolved]))
    packet = result.evidence_packet.model_copy(deep=True) if result.evidence_packet is not None else None
    if packet is not None:
        packet.missing_evidence = list(dict.fromkeys([*packet.missing_evidence, *unresolved]))
        packet.query_trace = [*packet.query_trace, dict(schedule_trace)]
        if unresolved:
            packet.sufficiency = "partial" if packet.candidate_refs else "insufficient"
    return result.model_copy(update={
        "evidence_bundle": bundle,
        "evidence_packet": packet,
    })


def _failed_retrieval_result(
    request: ExplorationRequest,
    requirements: tuple[EvidenceRequirement, ...],
    exc: Exception,
) -> ExplorationResult:
    """Normalize a retriever exception into a persisted, non-sufficient result."""

    from app.contracts.evidence.evidence_contracts import EvidenceBundle
    from app.contracts.evidence.evidence_packet_contracts import EvidencePacket

    missing = [item.requirement_id for item in requirements if item.required]
    return ExplorationResult(
        evidence_bundle=EvidenceBundle(
            request=request.query,
            unresolved=missing,
        ),
        evidence_packet=EvidencePacket(
            request=request.query,
            candidate_offset=request.candidate_offset,
            candidate_limit=request.candidate_limit,
            ambiguity_status="unresolved",
            sufficiency="insufficient",
            missing_evidence=missing,
            query_trace=[{
                "step": "evidence_retrieval",
                "status": "failed",
                "error_type": type(exc).__name__,
                "cache_only": True,
            }],
        ),
    )


def _coverage_and_outcome(
    request: ExplorationRequest,
    requirements: tuple[EvidenceRequirement, ...],
    result: ExplorationResult,
    *,
    failed: bool = False,
) -> ExplorationResult:
    """Ensure every retrieval preserves its least-sufficient business state."""

    from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
    from app.modules.evidence.coverage import build_evidence_coverage
    from app.modules.evidence.sufficiency import evaluate_sufficiency

    packet = result.evidence_packet or EvidencePacket(
        request=request.query,
        candidate_offset=request.candidate_offset,
        candidate_limit=request.candidate_limit,
    )
    result = result.model_copy(update={"evidence_packet": packet})
    decision = evaluate_sufficiency(request, result)
    coverage = build_evidence_coverage(
        request,
        result,
        decision,
        requirements=requirements,
        source_families_queried=tuple(
            dict.fromkeys(source.source_type for source in result.evidence_bundle.sources)
        ),
        query_trace=tuple(
            item
            for item in packet.query_trace
            if isinstance(item, Mapping)
        ),
        source_scope="project_wide" if request.project_wide else "scoped",
    )
    human_required = (
        coverage.stop_reason == "human_required"
        or any(
            item.gap_status == "requires_human_confirmation"
            for item in requirements
        )
    )
    sufficient = (
        not failed
        and coverage.sufficient
        and packet.sufficiency == "sufficient"
        and not result.evidence_bundle.unresolved
    )
    if failed:
        outcome = EvidenceRetrievalOutcome(
            status="failed",
            reason="retriever_exception_normalized",
            reason_codes=("retriever_exception",),
        )
    elif human_required:
        outcome = EvidenceRetrievalOutcome(
            status="human_required",
            reason="requirements require human confirmation",
            reason_codes=("human_confirmation",),
        )
    elif sufficient:
        outcome = EvidenceRetrievalOutcome(
            status="sufficient",
            reason="coverage and packet are sufficient",
        )
    elif packet.sufficiency == "partial" or result.evidence_bundle.facts:
        outcome = EvidenceRetrievalOutcome(
            status="partial",
            reason="retrieval returned bounded but incomplete evidence",
            reason_codes=("coverage_incomplete",),
        )
    else:
        outcome = EvidenceRetrievalOutcome(
            status="insufficient",
            reason="retrieval did not satisfy the required evidence",
            reason_codes=("coverage_incomplete",),
        )
    return result.model_copy(update={"coverage": coverage, "outcome": outcome})


def _result_from_retrieval_artifact(
    artifact: EvidenceRetrievalArtifact,
    *,
    receipt: Any,
) -> ExplorationResult:
    """Rebuild the public result entirely from its persisted retrieval blob."""

    return ExplorationResult(
        evidence_bundle=artifact.evidence_bundle,
        spatial_cognition=artifact.spatial_cognition,
        evidence_packet=artifact.evidence_packet,
        coverage=artifact.coverage,
        outcome=artifact.outcome,
        receipt=receipt,
    )


def _commit_retrieval_artifact(
    result: ExplorationResult,
    *,
    context: EvidenceContext,
    request: ExplorationRequest,
    requirements: tuple[EvidenceRequirement, ...],
    authority: EvidenceRetrievalAuthority,
    fingerprint: str,
    store: Any,
    failed: bool = False,
) -> ExplorationResult:
    """Persist one normalized result and return only the committed replay view."""

    normalized = _coverage_and_outcome(
        request,
        requirements,
        result,
        failed=failed,
    )
    packet = normalized.evidence_packet
    coverage = normalized.coverage
    outcome = normalized.outcome
    if packet is None or coverage is None or outcome is None:
        raise ArtifactReplayError("retrieval normalization did not produce replayable output")
    provider_attempts = tuple(
        getattr(
            getattr(context, "external_observation_snapshot", None),
            "provider_attempts",
            (),
        )
        or ()
    )
    if not provider_attempts:
        provider_attempts = tuple(
            provider_attempt_from_legacy(
                {
                    "provider": "local_evidence_runtime",
                    "stage": str(getattr(context, "stage", "") or "evidence"),
                    "run_id": str(getattr(context, "run_id", "") or fingerprint[:16]),
                    "status": (
                        "failed"
                        if outcome.status == "failed"
                        else "success_nonempty"
                        if packet.candidate_total or normalized.evidence_bundle.facts
                        else "success_empty"
                    ),
                    "reason_code": outcome.reason or outcome.status,
                    "query_fingerprint": fingerprint,
                },
                requirement_refs=tuple(item.requirement_id for item in requirements),
            )
        ,)
    acquisition_confidence = (
        1.0
        if provider_attempts
        and all(
            item.status in {"SUCCESS_NONEMPTY", "SUCCESS_EMPTY"}
            for item in provider_attempts
        )
        else 0.0
    )
    evidence_confidence = EvidenceConfidence(
        acquisition=acquisition_confidence,
        semantic=1.0 if normalized.evidence_bundle.facts else 0.0,
        binding=(
            1.0
            if packet.candidate_identity_total
            and packet.candidate_identity_total == packet.candidate_total
            else 0.0
        ),
        temporal_fit=1.0 if coverage.sufficient else 0.0,
    )
    evidence_authority = EvidenceAuthority(
        source_authority=(
            "local_source"
            if "data" in context.available_sources
            else "advisory"
        ),
        geometry_authority=(
            "local_representation"
            if packet.candidate_total
            else "none"
        ),
        legal_authority="none",
    )
    artifact = EvidenceRetrievalArtifact(
        context_version=authority.context_version,
        context_fingerprint=authority.context_fingerprint,
        artifact_id="evidence-retrieval-" + fingerprint[:16],
        fingerprint=fingerprint,
        canonical_request=request,
        evidence_bundle=normalized.evidence_bundle,
        evidence_packet=packet,
        coverage=coverage,
        outcome=outcome,
        authority=authority,
        bootstrap_refs=EvidenceRetrievalBootstrapRefs(
            evidence_snapshot_ref=authority.evidence_snapshot_ref,
            external_observations_ref=authority.external_observations_ref,
            gap_ledger_ref=authority.gap_ledger_ref,
        ),
        spatial_cognition=normalized.spatial_cognition,
        provider_attempts=provider_attempts,
        confidence_components=evidence_confidence,
        evidence_authority=evidence_authority,
    )
    persisted, receipt = store.write_once(artifact)
    return _result_from_retrieval_artifact(persisted, receipt=receipt)


class EvidenceApplication:
    """Own requirement meaning while delegating all retrieval execution."""

    @staticmethod
    def _artifact_state(state: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(state)
        result.setdefault("artifact_root", str(run_tmp_root()))
        result.setdefault("artifact_schema_version", "3")
        result.setdefault("run_id", result.get("session_id", ""))
        result.setdefault("branch_id", "main")
        result["artifact_refs"] = dict(result.get("artifact_refs") or {})
        return result

    @staticmethod
    def _ref_digest(ref: Any) -> str:
        if isinstance(ref, Mapping):
            return str(ref.get("digest") or ref.get("descriptor_digest") or "")
        return str(getattr(ref, "digest", "") or getattr(ref, "descriptor_digest", "") or "")

    @staticmethod
    def _ref_descriptor_digest(ref: Any) -> str:
        if isinstance(ref, Mapping):
            return str(ref.get("descriptor_digest") or "")
        return str(getattr(ref, "descriptor_digest", "") or "")

    async def bootstrap(
        self,
        state: Mapping[str, Any],
        *,
        context: Any = None,
    ) -> EvidenceRunResult:
        """Publish the evidence readiness boundary for one frozen context.

        This is intentionally not a requirement retrieval call.  Requirement
        retrieval remains immediate and bounded in ``retrieve``; this product
        only proves that the DATA/KG references and allowed source adapters
        used by those calls are present and reloadable.
        """

        current = dict(state)
        from app.workflow.stages.support import require_upstream_gates

        require_upstream_gates(
            current,
            ("data", "kg"),
            allow_evidence_requests=True,
        )
        if context is None:
            session_id = str(current.get("session_id") or "")
            if session_id:
                try:
                    from app.infrastructure.context_runtime.manager import get_cached_context

                    context = get_cached_context(session_id)
                except Exception:
                    context = None
        refs = dict(current.get("artifact_refs") or {})
        from app.contracts.cognition.snapshot import SessionWorldModelSnapshot
        from app.contracts.cognition.decision import SourceSemanticMappingSnapshot
        from app.contracts.cognition.stage_contracts import CognitionStageSnapshot
        from app.data.model.snapshot import SessionDataSnapshot
        from app.modules.data.application import DataApplication

        catalog_artifact = DataApplication.load_catalog(current)
        data_artifact = load_artifact(
            current,
            "data_snapshot",
            SessionDataSnapshot,
        )
        world_artifact = load_artifact(
            current,
            "world_model_snapshot",
            SessionWorldModelSnapshot,
        )
        cognition_stage = load_artifact(
            current,
            "kg_stage",
            CognitionStageSnapshot,
        )
        schema_mapping_artifact = load_artifact(
            current,
            "schema_mapping_snapshot",
            SourceSemanticMappingSnapshot,
        )
        catalog_admission_error = ""
        if catalog_artifact is not None:
            try:
                from app.data.admission import assert_current_world_catalog

                assert_current_world_catalog(catalog_artifact)
            except (TypeError, ValueError) as exc:
                catalog_admission_error = str(exc)
        data_catalog = getattr(context, "data_resource_catalog", None) if context is not None else current.get("data_catalog")
        if data_catalog is None and catalog_artifact is not None:
            from app.data.resource_catalog import DataResourceCatalog

            data_catalog = DataResourceCatalog(catalog_artifact)
        world_model = getattr(context, "world_model", None) if context is not None else None
        if world_model is None and context is not None:
            mode = str(getattr(context, "world_model_mode", "off") or "off").casefold()
            world_model = (
                getattr(context, "kg", None)
                if mode in {"shadow", "prefer_v2", "v2_only"}
                else getattr(context, "world_model_shadow", None)
            )
            if world_model is None:
                # ``world_model`` is the normal cognition handle in all new
                # contexts.  This final compatibility read is only for an
                # older cached context; it does not make the legacy KG the
                # DATA/KG bootstrap authority.
                world_model = getattr(context, "kg", None)
        expected_world_digest = str(
            getattr(world_artifact, "graph_digest", "") or ""
        )
        current_world_digest = str(
            getattr(world_model, "snapshot_digest", "")
            or getattr(world_model, "graph_digest", "")
            or ""
        )
        if (
            data_catalog is not None
            and str(current.get("session_id") or "")
            and expected_world_digest
            and expected_world_digest != current_world_digest
        ):
            try:
                from app.infrastructure.cognition_runtime.world_model_store import (
                    get_world_model_store,
                )

                reloaded = get_world_model_store(
                    str(current.get("session_id") or ""),
                    str(
                        current.get("village_name")
                        or (current.get("config") or {}).get("village_name")
                        or ""
                    ),
                    data_catalog,
                    schema_mapping_snapshot=schema_mapping_artifact,
                    schema_mapping_artifact_ref=self._ref_descriptor_digest(
                        refs.get("schema_mapping_snapshot")
                    ),
                    artifact_root=str(current.get("artifact_root") or ""),
                    expected_snapshot_digest=expected_world_digest,
                )
                if str(getattr(reloaded, "snapshot_digest", "") or "") == expected_world_digest:
                    world_model = reloaded
            except Exception:
                pass
        data_snapshot = (
            getattr(context, "data_snapshot", None)
            if context is not None
            else None
        ) or data_artifact
        world_model_view = world_model or world_artifact
        live_data_digest = str(getattr(data_snapshot, "digest", "") or "")
        data_digest = str(getattr(data_artifact, "digest", "") or "")
        data_snapshot_ref = str(getattr(data_artifact, "snapshot_id", "") or "")
        data_artifact_ref = self._ref_digest(refs.get("data_snapshot"))
        live_world_ref = str(
            getattr(world_model_view, "snapshot_ref", "") or ""
        )
        live_world_digest = str(
            getattr(world_model_view, "snapshot_digest", "")
            or getattr(world_model_view, "graph_digest", "")
            or ""
        )
        world_ref = str(getattr(world_artifact, "snapshot_ref", "") or "")
        world_digest = str(getattr(world_artifact, "graph_digest", "") or "")
        world_artifact_ref = self._ref_digest(refs.get("world_model_snapshot"))
        schema_mapping_artifact_ref = self._ref_descriptor_digest(
            refs.get("schema_mapping_snapshot")
        )
        schema_mapping_digest = str(
            getattr(schema_mapping_artifact, "mapping_fingerprint", "")
            or getattr(schema_mapping_artifact, "decision_fingerprint", "")
            or ""
        )
        schema_mapping_source_ref = str(
            getattr(schema_mapping_artifact, "source_snapshot_ref", "") or ""
        )
        schema_mapping_source_digest = str(
            getattr(schema_mapping_artifact, "source_snapshot_digest", "") or ""
        )
        source_families: set[str] = set()
        capability_refs: set[str] = set()
        catalog_snapshot = getattr(data_catalog, "snapshot", data_catalog)
        admission_index = None
        if catalog_snapshot is not None and not catalog_admission_error:
            from app.data.admission import (
                build_admission_index,
                is_admitted_capability,
                is_admitted_representation,
            )

            admission_index = build_admission_index(catalog_snapshot)
            source_families.update({"artifact", "data", "gis"})
            capability_refs.add("source_evidence")
            for item in list(getattr(catalog_snapshot, "capabilities", ()) or ()):
                if not is_admitted_capability(
                    catalog_snapshot, item, index=admission_index
                ):
                    continue
                operation = str(getattr(item, "operation", "") or "").strip()
                if operation:
                    capability_refs.add(operation)
            if any(
                is_admitted_representation(
                    catalog_snapshot, item, index=admission_index
                )
                and
                str(getattr(item, "status", "") or "") == "available"
                and str(getattr(item, "geometry_kind", "") or "")
                in {"point", "line", "polygon", "multipatch"}
                for item in getattr(catalog_snapshot, "representations", ()) or ()
            ):
                capability_refs.update({"local_spatial_evidence", "metric_source"})
        if world_model_view is not None:
            source_families.add("kg")
            capability_refs.update({"identity_evidence", "source_evidence"})
        if context is not None and getattr(context, "reports", None):
            source_families.update({"report", "text"})
            capability_refs.add("source_evidence")
        external_snapshot = (
            getattr(context, "external_observation_snapshot", None)
            if context is not None
            else None
        )
        if external_snapshot is None:
            try:
                from app.data.catalog.external_observation_cache import (
                    load_cached_external_observation_snapshot,
                )

                administrative_scope, project_bbox = _external_cache_scope(
                    current,
                    context,
                )
                external_snapshot = load_cached_external_observation_snapshot(
                    project_name=str(
                        current.get("village_name")
                        or (current.get("config") or {}).get("village_name")
                        or ""
                    ),
                    administrative_scope=administrative_scope,
                    project_bbox_wgs84=project_bbox,
                )
            except Exception:
                external_snapshot = None
        external_snapshot = _frozen_external_snapshot(
            external_snapshot,
            project_name=str(
                current.get("village_name")
                or (current.get("config") or {}).get("village_name")
                or ""
            ),
        )
        provider_attempts = tuple(
            getattr(external_snapshot, "provider_attempts", ()) or ()
        )
        external_digest = str(getattr(external_snapshot, "digest", "") or "")
        external_status_counts: dict[str, int] = {}
        for observation in getattr(external_snapshot, "observations", ()) or ():
            status = str(getattr(observation, "status", "") or "missing")
            external_status_counts[status] = external_status_counts.get(status, 0) + 1
        for provider_run in getattr(external_snapshot, "provider_runs", ()) or ():
            status = str(
                provider_run.get("status")
                if isinstance(provider_run, Mapping)
                else getattr(provider_run, "status", "")
            ) or "missing"
            key = f"provider_run:{status}"
            external_status_counts[key] = external_status_counts.get(key, 0) + 1
        if external_snapshot is not None and (
            getattr(external_snapshot, "provider_runs", None)
            or getattr(external_snapshot, "observations", None)
        ):
            source_families.update({"external", "external_map_cache"})
            capability_refs.update({"identity_evidence", "source_evidence"})
        diagnostics: list[str] = []
        gaps: list[str] = []
        ready = True
        if catalog_admission_error:
            diagnostics.append("data_catalog_current_world_admission_failed")
            gaps.append("gap:evidence:data_catalog_admission")
            ready = False
        if data_catalog is None:
            diagnostics.append("data_catalog_unavailable")
            gaps.append("gap:evidence:data_catalog")
            ready = False
        if catalog_artifact is None:
            diagnostics.append("data_catalog_artifact_unavailable")
            gaps.append("gap:evidence:data_catalog_artifact")
            ready = False
        if data_artifact is None:
            diagnostics.append("data_snapshot_artifact_unavailable")
            gaps.append("gap:evidence:data_snapshot_artifact")
            ready = False
        if data_snapshot is None:
            diagnostics.append("live_data_snapshot_unavailable")
            gaps.append("gap:evidence:live_data_snapshot")
            ready = False
        if world_model_view is None:
            diagnostics.append("world_model_unavailable")
            gaps.append("gap:evidence:world_model")
            ready = False
        if world_artifact is None:
            diagnostics.append("world_model_artifact_unavailable")
            gaps.append("gap:evidence:world_model_artifact")
            ready = False
        if schema_mapping_artifact is None:
            diagnostics.append("schema_mapping_artifact_unavailable")
            gaps.append("gap:evidence:schema_mapping_artifact")
            ready = False
        if cognition_stage is None:
            diagnostics.append("cognition_stage_artifact_unavailable")
            gaps.append("gap:evidence:cognition_stage_artifact")
            ready = False
        expected_schema_ref = str(
            getattr(cognition_stage, "schema_mapping_ref", "") or ""
        )
        expected_schema_digest = str(
            getattr(cognition_stage, "schema_mapping_digest", "") or ""
        )
        if not expected_schema_ref:
            diagnostics.append("cognition_stage_schema_mapping_ref_missing")
            gaps.append("gap:evidence:schema_mapping_ref_missing")
            ready = False
        elif schema_mapping_artifact_ref != expected_schema_ref:
            diagnostics.append("schema_mapping_descriptor_mismatch")
            gaps.append("gap:evidence:schema_mapping_descriptor_mismatch")
            ready = False
        if not expected_schema_digest:
            diagnostics.append("cognition_stage_schema_mapping_digest_missing")
            gaps.append("gap:evidence:schema_mapping_digest_missing")
            ready = False
        elif schema_mapping_digest != expected_schema_digest:
            diagnostics.append("schema_mapping_fingerprint_mismatch")
            gaps.append("gap:evidence:schema_mapping_fingerprint_mismatch")
            ready = False
        if data_digest and live_data_digest and data_digest != live_data_digest:
            diagnostics.append("data_snapshot_digest_mismatch")
            gaps.append("gap:evidence:data_snapshot_digest_mismatch")
            ready = False
        live_catalog_digest = str(getattr(catalog_snapshot, "digest", "") or "")
        artifact_catalog_digest = str(getattr(catalog_artifact, "digest", "") or "")
        if live_catalog_digest and artifact_catalog_digest and live_catalog_digest != artifact_catalog_digest:
            diagnostics.append("data_catalog_digest_mismatch")
            gaps.append("gap:evidence:data_catalog_digest_mismatch")
            ready = False
        if world_digest and live_world_digest and world_digest != live_world_digest:
            diagnostics.append("world_model_digest_mismatch")
            gaps.append("gap:evidence:world_model_digest_mismatch")
            ready = False
        if world_ref and live_world_ref and world_ref != live_world_ref:
            diagnostics.append("world_model_snapshot_ref_mismatch")
            gaps.append("gap:evidence:world_model_snapshot_ref_mismatch")
            ready = False
        if (
            world_artifact is not None
            and artifact_catalog_digest
            and str(world_artifact.source_catalog_digest or "") != artifact_catalog_digest
        ):
            diagnostics.append("world_model_source_catalog_mismatch")
            gaps.append("gap:evidence:world_model_source_catalog_mismatch")
            ready = False
        if (
            cognition_stage is not None
            and artifact_catalog_digest
            and str(cognition_stage.source_catalog_digest or "")
            != artifact_catalog_digest
        ):
            diagnostics.append("cognition_stage_source_catalog_mismatch")
            gaps.append("gap:evidence:cognition_stage_source_catalog_mismatch")
            ready = False
        if schema_mapping_artifact is not None:
            if (
                not schema_mapping_source_digest
                or not artifact_catalog_digest
                or schema_mapping_source_digest != artifact_catalog_digest
            ):
                diagnostics.append("schema_mapping_source_catalog_mismatch")
                gaps.append("gap:evidence:schema_mapping_source_catalog_mismatch")
                ready = False
            if world_artifact is not None and (
                not str(getattr(world_artifact, "schema_mapping_digest", "") or "")
                or str(getattr(world_artifact, "schema_mapping_digest", "") or "")
                != schema_mapping_digest
            ):
                diagnostics.append("world_model_schema_mapping_mismatch")
                gaps.append("gap:evidence:world_model_schema_mapping_mismatch")
                ready = False
            if world_artifact is not None and (
                not str(getattr(world_artifact, "schema_mapping_ref", "") or "")
                or str(getattr(world_artifact, "schema_mapping_ref", "") or "")
                != schema_mapping_artifact_ref
            ):
                diagnostics.append("world_model_schema_mapping_ref_mismatch")
                gaps.append("gap:evidence:world_model_schema_mapping_ref_mismatch")
                ready = False
            expected_source_refs = {
                str(value)
                for value in (
                    data_snapshot_ref,
                    str(getattr(catalog_artifact, "snapshot_id", "") or ""),
                    str(getattr(cognition_stage, "source_catalog_ref", "") or ""),
                    str(getattr(world_artifact, "source_catalog_ref", "") or ""),
                )
                if str(value).strip()
            }
            if (
                not schema_mapping_source_ref
                or expected_source_refs
                and schema_mapping_source_ref not in expected_source_refs
            ):
                diagnostics.append("schema_mapping_source_ref_mismatch")
                gaps.append("gap:evidence:schema_mapping_source_ref_mismatch")
                ready = False
        feature_by_resource_ref = {
            (
                f"resource:{getattr(item, 'dataset_ref', '')}:"
                f"{getattr(item, 'source_feature_ref', '')}"
            ): item
            for item in (
                getattr(catalog_artifact, "features", ()) or ()
                if not catalog_admission_error
                else ()
            )
            if str(getattr(item, "dataset_ref", "") or "").strip()
            and str(getattr(item, "source_feature_ref", "") or "").strip()
        }

        def _feature_for_subject_ref(subject_ref: str) -> Any | None:
            """Resolve only a dataset-qualified DATA feature reference."""

            value = str(subject_ref or "").strip()
            if not value.startswith("resource:"):
                return None
            return feature_by_resource_ref.get(value)
        scheduled_gap_rows: list[EvidenceGapScheduleRecord] = []
        immediate_supplement_count = 0
        for provider_run in tuple(
            getattr(external_snapshot, "provider_runs", ()) or ()
        ):
            run_row = (
                dict(provider_run)
                if isinstance(provider_run, Mapping)
                else provider_run.model_dump(mode="json")
            )
            run_status = str(run_row.get("status") or "not_attempted").strip()
            if run_status in {"success_nonempty", "success_empty"}:
                continue
            provider = str(run_row.get("provider") or "unknown").strip()
            external_stage = str(run_row.get("stage") or "unknown").strip()
            run_id = str(run_row.get("run_id") or "missing").strip()
            status_counts = dict(run_row.get("status_counts") or {})
            missing_statuses: set[str] = set()
            for key, value in status_counts.items():
                try:
                    amount = int(value or 0)
                except (TypeError, ValueError):
                    amount = 0
                if str(key) != "success_nonempty" and amount > 0:
                    missing_statuses.add(str(key))
            missing_fields = tuple(sorted(missing_statuses)) or (
                "provider_cache_complete",
            )
            gap_ref = "evidence.gap.external." + semantic_checksum({
                "provider": provider,
                "stage": external_stage,
                "run_id": run_id,
                "status": run_status,
                "source_digest": external_digest,
                "missing_fields": missing_fields,
            })[:24]
            normalized_count = int(
                run_row.get("normalized_record_count") or 0
            )
            scheduled_gap_rows.append(EvidenceGapScheduleRecord(
                gap_ref=gap_ref,
                producer_stage="evidence",
                subject_refs=(
                    f"external-provider-run:{provider}:{external_stage}:{run_id}",
                ),
                missing_fields=missing_fields,
                source_digest=external_digest,
                earliest_resolution_stage="evidence",
                deferred_until="evidence_collection",
                allowed_sources=("external_map_cache", provider),
                retrieval_capability=f"{provider}_cache_collection",
                status="not_available",
                evidence_refs=(
                    (f"external-cache-snapshot:{external_digest}",)
                    if normalized_count > 0
                    else ()
                ),
                failure_reason=f"external_provider_run_{run_status}",
                recovery_pointer=(
                    f"external-cache:{provider}:{external_stage}:{run_id}"
                ),
            ))
        for cognition_gap in tuple(getattr(cognition_stage, "gaps", ()) or ()):
            gap_ref = str(getattr(cognition_gap, "gap_ref", "") or "")
            subject_refs = tuple(
                str(item)
                for item in getattr(cognition_gap, "subject_refs", ()) or ()
                if str(item).strip()
            )
            source_feature_refs = tuple(
                item
                for item in subject_refs
                if _feature_for_subject_ref(item) is not None
            )
            reason = str(getattr(cognition_gap, "reason", "") or "")
            earliest = str(
                getattr(cognition_gap, "earliest_resolution_stage", "")
                or "evidence"
            ).casefold()
            evidence_refs: list[str] = []
            for source_feature_ref in source_feature_refs:
                feature = _feature_for_subject_ref(source_feature_ref)
                if feature is None:
                    continue
                evidence_refs.append(
                    "data:" + source_feature_ref.removeprefix("resource:")
                )
            if earliest == "human" or "ambiguous" in reason:
                status = "requires_human_confirmation"
                deferred_until = "human"
                failure_reason = "identity_conflict_requires_human_confirmation"
            elif (
                source_feature_refs
                and data_catalog is not None
                and world_model_view is not None
            ):
                # Local DATA/KG lookup is performed immediately by attaching
                # the exact source rows.  It supplies evidence but does not
                # pretend to settle semantic identity; L1 receives this row
                # and must either accept a sourced semantic assertion or
                # propagate the gap unchanged.
                status = "open"
                deferred_until = "l1"
                failure_reason = "local_sources_attached_semantic_decision_required"
                immediate_supplement_count += 1
            elif "representation" in reason or "lineage" in reason:
                status = "not_available"
                deferred_until = "data"
                failure_reason = "data_representation_recovery_required"
            else:
                status = "not_available"
                deferred_until = "l1"
                failure_reason = "bounded_local_identity_sources_unavailable"
            scheduled_gap_rows.append(EvidenceGapScheduleRecord(
                gap_ref=gap_ref,
                producer_stage="kg",
                subject_refs=subject_refs,
                missing_fields=tuple(
                    str(item)
                    for item in getattr(cognition_gap, "missing_fields", ()) or ()
                    if str(item).strip()
                ),
                source_digest=str(
                    getattr(cognition_gap, "source_catalog_digest", "") or ""
                ),
                earliest_resolution_stage=earliest,
                deferred_until=deferred_until,
                allowed_sources=("data", "kg", "external_map_cache", "text"),
                retrieval_capability="identity_evidence",
                status=status,
                evidence_refs=tuple(evidence_refs),
                failure_reason=failure_reason,
                recovery_pointer=str(
                    getattr(cognition_gap, "recovery_pointer", "") or ""
                ),
            ))
        unresolved_schedule_refs = tuple(
            item.gap_ref
            for item in scheduled_gap_rows
            if item.status != "resolved"
        )
        artifact_state = self._artifact_state(current)
        external_artifact = EvidenceExternalObservationSnapshot(
            context_version=str(current.get("context_version") or getattr(context, "version", "") or ""),
            context_fingerprint=str(current.get("context_fingerprint") or ""),
            artifact_id="evidence-external-" + external_digest.removeprefix("sha256:")[:16],
            cache_digest=external_digest,
            snapshot=external_snapshot,
            provider_attempts=provider_attempts,
        )
        external_observations_ref = ArtifactRef.model_validate(store_artifact(
            artifact_state,
            "evidence_external_observations",
            "evidence",
            "EvidenceExternalObservationSnapshot",
            external_artifact,
        ))
        refs["evidence_external_observations"] = external_observations_ref.model_dump(mode="json")
        artifact_state = self._artifact_state({**current, "artifact_refs": refs})
        gap_ledger = EvidenceGapLedger(
            context_version=str(current.get("context_version") or getattr(context, "version", "") or ""),
            context_fingerprint=str(current.get("context_fingerprint") or ""),
            artifact_id="evidence-gap-ledger-" + semantic_checksum(scheduled_gap_rows)[:16],
            source_catalog_digest=artifact_catalog_digest,
            world_model_snapshot_digest=world_digest,
            upstream_gap_refs=tuple(
                str(item)
                for item in getattr(cognition_stage, "gap_refs", ()) or ()
                if str(item).strip()
            ),
            gap_rows=tuple(scheduled_gap_rows),
            provider_attempts=provider_attempts,
            confidence_components=EvidenceConfidence(
                acquisition=(
                    1.0
                    if all(item.status in {"SUCCESS_NONEMPTY", "SUCCESS_EMPTY"} for item in provider_attempts)
                    and provider_attempts
                    else 0.0
                ),
                semantic=0.0,
                binding=0.0,
                temporal_fit=0.0,
            ),
            authority=EvidenceAuthority(
                source_authority="cache_only",
                geometry_authority="observation_only",
                legal_authority="none",
            ),
        )
        gap_ledger_ref = ArtifactRef.model_validate(store_artifact(
            artifact_state,
            "evidence_gap_ledger",
            "evidence",
            "EvidenceGapLedger",
            gap_ledger,
        ))
        refs["evidence_gap_ledger"] = gap_ledger_ref.model_dump(mode="json")
        artifact_state = self._artifact_state({**current, "artifact_refs": refs})
        snapshot = EvidenceStageSnapshot(
            context_version=str(current.get("context_version") or getattr(context, "version", "") or ""),
            context_fingerprint=str(current.get("context_fingerprint") or ""),
            artifact_id="evidence-" + semantic_checksum({
                "data": data_digest,
                "world": world_digest,
                "sources": sorted(source_families),
            })[:16],
            status="ready" if ready else "blocked",
            data_catalog_artifact_ref=ArtifactRef.model_validate(refs.get("data_catalog")),
            data_snapshot_artifact_ref=ArtifactRef.model_validate(refs.get("data_snapshot")),
            world_model_artifact_ref=ArtifactRef.model_validate(refs.get("world_model_snapshot")),
            data_snapshot_ref=data_snapshot_ref,
            data_snapshot_digest=data_digest,
            data_artifact_ref=data_artifact_ref,
            source_catalog_ref=str(getattr(catalog_artifact, "snapshot_id", "") or ""),
            source_catalog_digest=artifact_catalog_digest,
            world_model_snapshot_ref=world_ref,
            world_model_snapshot_digest=world_digest,
            schema_mapping_artifact_ref=schema_mapping_artifact_ref,
            schema_mapping_digest=schema_mapping_digest,
            source_families=tuple(sorted(source_families)),
            capability_refs=tuple(sorted(capability_refs)),
            external_cache_digest=external_digest,
            external_observations_ref=external_observations_ref,
            gap_ledger_ref=gap_ledger_ref,
            external_cache_complete=bool(
                getattr(external_snapshot, "complete", False)
            ),
            provider_attempts=provider_attempts,
            confidence_components=gap_ledger.confidence_components,
            authority=gap_ledger.authority,
            external_status_counts=dict(sorted(external_status_counts.items())),
            diagnostics=tuple(sorted(set(diagnostics))),
            gap_refs=tuple(sorted(set([*gaps, *unresolved_schedule_refs]))),
            upstream_gap_refs=tuple(
                str(item)
                for item in getattr(cognition_stage, "gap_refs", ()) or ()
                if str(item).strip()
            ),
            scheduled_gap_count=len(scheduled_gap_rows),
            immediate_supplement_count=immediate_supplement_count,
            unresolved_gap_count=len(unresolved_schedule_refs),
            gap_rows=tuple(scheduled_gap_rows),
            data_dependency_graph_digest=str(current.get("data_dependency_graph_digest") or ""),
        )
        snapshot_ref = ArtifactRef.model_validate(
            store_artifact(
                artifact_state,
                "evidence_snapshot",
                "evidence",
                "EvidenceStageSnapshot",
                snapshot,
            )
        )
        refs["evidence_snapshot"] = snapshot_ref.model_dump(mode="json")
        artifact_state = self._artifact_state({**current, "artifact_refs": refs})
        pending = []
        if not ready:
            pending = [
                PendingRequest(
                    request_id="pr-evidence-bootstrap",
                    stage="evidence",
                    request_type="evidence_source_unavailable",
                    context={"diagnostics": list(snapshot.diagnostics), "gap_refs": list(snapshot.gap_refs)},
                )
            ]
        gate = GateDecision(
            stage="evidence",
            passed=ready,
            feedback_route=None if ready else "HUMAN",
            pending_requests=pending,
            # The gate proves runtime/source integrity.  Collection-scoped
            # semantic gaps are typed inputs for L1, not claims of closure;
            # putting them on this gate would deadlock the very stage assigned
            # to resolve or propagate them.  True runtime gaps remain blocking.
            evidence_requests=list(dict.fromkeys(gaps)),
            context_version=snapshot.context_version,
            artifact_id="gate-evidence-" + semantic_checksum(snapshot)[:16],
            route_reason=(
                "evidence_runtime_ready_with_semantic_gaps"
                if ready and unresolved_schedule_refs
                else "evidence_runtime_ready"
                if ready
                else "evidence_runtime_inputs_missing"
            ),
        )
        gate_ref = persist_gate_decision(
            artifact_state,
            "evidence",
            gate,
            output_refs={
                "evidence_snapshot": snapshot_ref,
                "evidence_external_observations": external_observations_ref,
                "evidence_gap_ledger": gap_ledger_ref,
            },
        )
        return EvidenceRunResult(
            snapshot=snapshot,
            snapshot_ref=snapshot_ref,
            external_observations_ref=external_observations_ref,
            gap_ledger_ref=gap_ledger_ref,
            gate_ref=gate_ref,
            state_patch={
                "artifact_refs": refs,
                "evidence_snapshot_status": snapshot.status,
                "evidence_gap_refs": list(snapshot.gap_refs),
                "evidence_gap_rows": [
                    item.model_dump(mode="json") for item in snapshot.gap_rows
                ],
            },
        )

    @staticmethod
    def load_bootstrap(state: Mapping[str, Any]) -> EvidenceStageSnapshot | None:
        return load_artifact(dict(state), "evidence_snapshot", EvidenceStageSnapshot)

    async def retrieve_dimension_context(
        self,
        dimension_key: str,
        config: Any,
        state: Mapping[str, Any],
        *,
        trace_sink: dict[str, Any] | None = None,
        excluded_fact_refs: Iterable[str] | None = None,
    ) -> tuple[str, Any | None]:
        """Build the bounded analysis projection for one current dimension.

        Dimension workers provide the business dimension and current state;
        the evidence runtime owns query planning, routing, provider access,
        fusion, and prompt projection.
        """

        from app.infrastructure.evidence_runtime.facade import (
            retrieve_dimension_context,
        )

        return await retrieve_dimension_context(
            dimension_key,
            config,
            dict(state),
            trace_sink=trace_sink,
            excluded_fact_refs=excluded_fact_refs,
        )

    def collect_authoritative_source_features(
        self,
        context: Any,
    ) -> dict[str, list[object]]:
        """Return current-session source features through the Evidence boundary."""

        from app.infrastructure.evidence_runtime.source_semantic import (
            collect_authoritative_source_features,
        )

        return collect_authoritative_source_features(context)

    def describe_source_features(
        self,
        source_features: dict[str, list[object]],
    ) -> tuple[list[Any], int]:
        """Describe source features for deterministic semantic binding."""

        from app.infrastructure.evidence_runtime.source_semantic import (
            source_descriptors,
        )

        return source_descriptors(source_features)

    def install_source_semantic_snapshot(self, context: Any, snapshot: Any) -> None:
        """Install an accepted, current-session semantic overlay."""

        from app.infrastructure.evidence_runtime.source_semantic import (
            install_source_semantic_snapshot,
        )

        install_source_semantic_snapshot(context, snapshot)
        commit = getattr(getattr(context, "ports", None), "world_model_commit", None)
        commit_semantics = getattr(commit, "commit_semantic_decisions", None)
        if callable(commit_semantics) and str(
            getattr(context, "world_model_mode", "off") or "off"
        ).strip().lower() in {"shadow", "prefer_v2", "v2_only"}:
            outcome = commit_semantics(snapshot)
            if str(outcome.get("status") or "") == "aborted":
                raise RuntimeError("world-model semantic decision commit aborted")

    def accepted_semantic_decisions(self, snapshot: Any) -> dict[str, Any]:
        """Return only accepted decisions from a persisted semantic snapshot."""

        from app.infrastructure.evidence_runtime.source_semantic import (
            accepted_semantic_decisions,
        )

        return accepted_semantic_decisions(snapshot)

    async def classify_source_semantics(
        self,
        context: Any,
        *,
        enabled: Any = None,
        source_features: dict[str, list[object]] | None = None,
        classifier: Any = None,
    ) -> Any:
        """Classify current source semantics without exposing runtime routing."""

        from app.infrastructure.evidence_runtime.source_semantic import (
            classify_source_semantics,
        )

        return await classify_source_semantics(
            context,
            enabled=enabled,
            source_features=source_features,
            classifier=classifier,
        )

    def install_intent_layer(self, kg: Any, intent: Any) -> None:
        """Install the accepted target intent into the current KG projection."""

        from app.infrastructure.evidence_runtime.source_semantic import (
            install_intent_layer,
        )

        install_intent_layer(kg, intent)

    async def retrieve(
        self,
        requirement: EvidenceRequirement | Iterable[EvidenceRequirement],
        context: EvidenceContext,
        *,
        spatial_spec: Any = None,
        candidate_offset: int = 0,
        candidate_limit: int = 12,
    ) -> ExplorationResult:
        requirements = _as_requirements(requirement)
        from app.infrastructure.evidence_runtime.gap_scheduler import schedule_requirements

        requirements, schedule_trace = schedule_requirements(
            requirements,
            current_stage=context.stage or "L1",
            available_capabilities=context.available_capabilities,
            available_sources=context.available_sources,
        )
        requirements = tuple(
            item.model_copy(update={
                "metadata": {
                    **dict(item.metadata or {}),
                    "scheduler_trace": schedule_trace,
                }
            })
            for item in requirements
        )
        canonical_request = _request_for(
            requirements,
            context,
            candidate_offset=candidate_offset,
            candidate_limit=candidate_limit,
        )
        authority = context.retrieval_authority()
        from app.infrastructure.evidence_runtime.artifact_store import (
            EvidenceRetrievalArtifactStore,
            canonicalize_request,
            retrieval_fingerprint,
        )

        canonical_request = canonicalize_request(canonical_request)
        fingerprint = retrieval_fingerprint(
            authority,
            canonical_request,
            spatial_spec=spatial_spec,
        )
        store = EvidenceRetrievalArtifactStore(
            context.artifact_root,
            workflow_run_id=authority.workflow_run_id,
            branch_id=authority.branch_id,
        )
        cached = store.load(fingerprint=fingerprint, authority=authority)
        if cached is not None:
            artifact, receipt = cached
            return _result_from_retrieval_artifact(artifact, receipt=receipt)
        actionable = tuple(
            item
            for item in requirements
            if item.gap_status in {"ready_for_retrieval", "retrieving"}
        )
        if not actionable:
            return _commit_retrieval_artifact(
                _scheduled_gap_result(requirements, schedule_trace),
                context=context,
                request=canonical_request,
                requirements=requirements,
                authority=authority,
                fingerprint=fingerprint,
                store=store,
            )
        request = _request_for(
            actionable,
            context,
            candidate_offset=candidate_offset,
            candidate_limit=candidate_limit,
        )
        if context.world_model_mode.strip().lower() in {"shadow", "prefer_v2", "v2_only"} and context.data_catalog is not None:
            from app.infrastructure.evidence_runtime.v2_catalog import retrieve_catalog_evidence

            try:
                result = retrieve_catalog_evidence(
                    context,
                    actionable,
                    candidate_offset=candidate_offset,
                    candidate_limit=candidate_limit,
                )
            except Exception as exc:
                return _commit_retrieval_artifact(
                    _failed_retrieval_result(canonical_request, requirements, exc),
                    context=context,
                    request=canonical_request,
                    requirements=requirements,
                    authority=authority,
                    fingerprint=fingerprint,
                    store=store,
                    failed=True,
                )
            return _commit_retrieval_artifact(
                _append_scheduled_gaps(result, requirements, schedule_trace),
                context=context,
                request=canonical_request,
                requirements=requirements,
                authority=authority,
                fingerprint=fingerprint,
                store=store,
            )
        from app.infrastructure.evidence_runtime.facade import retrieve_evidence as run_runtime

        try:
            result = await run_runtime(
                request,
                session_id=context.session_id,
                village_name=context.village_name,
                spatial_spec=spatial_spec,
            )
        except Exception as exc:
            return _commit_retrieval_artifact(
                _failed_retrieval_result(canonical_request, requirements, exc),
                context=context,
                request=canonical_request,
                requirements=requirements,
                authority=authority,
                fingerprint=fingerprint,
                store=store,
                failed=True,
            )
        return _commit_retrieval_artifact(
            _append_scheduled_gaps(result, requirements, schedule_trace),
            context=context,
            request=canonical_request,
            requirements=requirements,
            authority=authority,
            fingerprint=fingerprint,
            store=store,
        )


EvidenceFacade = EvidenceApplication


# Transport adapters for existing API/workflow request shapes.  New business
# stages use EvidenceFacade.retrieve so requirement semantics stay explicit.
from app.infrastructure.evidence_runtime.facade import (  # noqa: E402
    _EVIDENCE_CACHE,
    clear_session_evidence_cache,
    gate_evidence_digest,
    render_evidence_prompt_section,
    retrieve_evidence,
    retrieve_evidence_for_gate,
    retrieve_evidence_for_gate_sync,
)

__all__ = [
    "EvidenceApplication",
    "EvidenceFacade",
    "EvidenceContext",
    "EvidenceRunResult",
    "clear_session_evidence_cache",
    "gate_evidence_digest",
    "render_evidence_prompt_section",
    "retrieve_evidence",
    "retrieve_evidence_for_gate",
    "retrieve_evidence_for_gate_sync",
    "_EVIDENCE_CACHE",
]
