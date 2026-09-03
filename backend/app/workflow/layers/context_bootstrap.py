from __future__ import annotations

from typing import Any, Dict

from app.infrastructure.context_runtime.manager import build_planning_context
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _context_reports_text(context: Any) -> str:
    """Join the current-state report bodies into one evidence text."""
    parts: list[str] = []
    for payload in dict(getattr(context, "reports", {}) or {}).values():
        if isinstance(payload, dict):
            parts.append(str(payload.get("content") or payload.get("summary") or ""))
        else:
            parts.append(str(payload or ""))
    return "\n".join(part for part in parts if part)[:12000]


def _context_authority(context: Any, *, session_id: str) -> tuple[str, str, dict[str, Any]]:
    """Return the bounded context identity used by DATA/KG/EVIDENCE CAS.

    The live ``PlanningContext`` owns the large catalog/graph objects.  The
    workflow checkpoint only receives this flat authority record so a resumed
    worker can prove that every stage artifact belongs to the same snapshot.
    """

    snapshot = getattr(context, "data_snapshot", None)
    version = str(getattr(context, "version", 1) or 1)
    content_hash = str(getattr(context, "content_hash", "") or "")
    if not content_hash:
        raise RuntimeError("context has no content_hash - not frozen")
    fingerprint = "sha256:" + content_hash[:16]
    world_model = getattr(context, "world_model", None)
    legacy_kg = getattr(context, "kg", None)
    world_model_mode = str(getattr(context, "world_model_mode", "off") or "off")
    world_ref = str(
        getattr(world_model, "snapshot_ref", "")
        or getattr(context, "kg_session_ref", "")
        or getattr(legacy_kg, "snapshot_ref", "")
        or ""
    )
    world_digest = str(
        getattr(world_model, "snapshot_digest", "")
        or getattr(legacy_kg, "snapshot_digest", "")
        or ""
    )
    shadow = getattr(context, "world_model_shadow", None)
    catalog = getattr(context, "data_resource_catalog", None)
    catalog_digest = str(
        getattr(getattr(catalog, "snapshot", None), "digest", "") or ""
    )
    authority = {
        "session_id": session_id,
        "version": version,
        "snapshot_id": str(getattr(snapshot, "snapshot_id", "") or ""),
        "snapshot_digest": str(getattr(snapshot, "digest", "") or ""),
        "data_snapshot_digest": str(getattr(snapshot, "digest", "") or ""),
        "data_resource_catalog_digest": catalog_digest,
        "world_model_mode": world_model_mode,
        "world_model_snapshot_ref": world_ref,
        "world_model_snapshot_digest": world_digest,
        "world_model_epoch": str(
            getattr(world_model, "version", "")
            or getattr(legacy_kg, "version", "")
            or ""
        ),
        "world_model_shadow_snapshot_ref": str(
            getattr(shadow, "snapshot_ref", "") or ""
        ),
        "world_model_shadow_snapshot_digest": str(
            getattr(shadow, "snapshot_digest", "") or ""
        ),
        "world_model_shadow_diff_ref": str(
            getattr(context, "world_model_shadow_diff_ref", "") or ""
        ),
        "boundary_scope_ref": str(
            getattr(getattr(context, "boundary_scope_artifact", None), "scope_ref", "") or ""
        ),
        "boundary_digest": str(
            getattr(getattr(context, "boundary_scope_artifact", None), "boundary_digest", "") or ""
        ),
    }
    return version, fingerprint, authority


def _context_stage_refs_complete(state: Dict[str, Any], context: Any) -> bool:
    """Check that all bootstrap products and their three gates are reloadable."""

    refs = dict(state.get("artifact_refs") or {})
    required = (
        "data_catalog", "data_snapshot", "data_stage", "data_gate",
        "schema_mapping_snapshot", "world_model_snapshot", "kg_stage", "kg_gate",
        "evidence_snapshot", "evidence_external_observations",
        "evidence_gap_ledger", "evidence_gate",
    )
    if any(not refs.get(key) for key in required):
        return False
    try:
        from app.workflow.state import load_root_gate
        from app.infrastructure.artifacts.runtime import load_artifact, load_embedded_artifact
        from app.data.model.snapshot import SessionDataSnapshot
        from app.contracts.data.stage_contracts import DataStageSnapshot
        from app.contracts.cognition.snapshot import SessionWorldModelSnapshot
        from app.contracts.cognition.decision import SourceSemanticMappingSnapshot
        from app.contracts.cognition.stage_contracts import CognitionStageSnapshot
        from app.contracts.evidence.stage_contracts import (
            EvidenceExternalObservationSnapshot,
            EvidenceGapLedger,
            EvidenceStageSnapshot,
        )

        for stage in ("data", "kg", "evidence"):
            gate = load_root_gate(dict(state), stage)
            if not gate.passed or gate.feedback_route not in (None, "", "PASS"):
                return False
            if list(getattr(gate, "pending_requests", None) or []):
                return False
            if list(getattr(gate, "evidence_requests", None) or []) and stage != "kg":
                # A persisted PASS with outstanding requests is an old/invalid
                # artifact.  Re-run the bootstrap so replay cannot silently
                # promote a partial DATA/KG/EVIDENCE context.
                return False
        from app.modules.data.application import DataApplication

        catalog = DataApplication.load_catalog(dict(state))
        snapshot = load_artifact(dict(state), "data_snapshot", SessionDataSnapshot)
        data_stage = load_artifact(dict(state), "data_stage", DataStageSnapshot)
        schema_mapping = load_artifact(
            dict(state), "schema_mapping_snapshot", SourceSemanticMappingSnapshot
        )
        world = load_artifact(dict(state), "world_model_snapshot", SessionWorldModelSnapshot)
        kg_stage = load_artifact(dict(state), "kg_stage", CognitionStageSnapshot)
        evidence = load_artifact(dict(state), "evidence_snapshot", EvidenceStageSnapshot)
        external = (
            load_embedded_artifact(
                dict(state),
                evidence.external_observations_ref.model_dump(mode="json"),
                EvidenceExternalObservationSnapshot,
            )
            if evidence is not None and evidence.external_observations_ref is not None
            else None
        )
        gap_ledger = (
            load_embedded_artifact(
                dict(state),
                evidence.gap_ledger_ref.model_dump(mode="json"),
                EvidenceGapLedger,
            )
            if evidence is not None and evidence.gap_ledger_ref is not None
            else None
        )
        live_snapshot = getattr(context, "data_snapshot", None)
        live_world = getattr(context, "world_model", None)
        if (
            catalog is None
            or snapshot is None
            or data_stage is None
            or schema_mapping is None
            or world is None
            or kg_stage is None
            or evidence is None
            or external is None
            or gap_ledger is None
        ):
            return False
        if live_snapshot is not None and snapshot.digest != str(getattr(live_snapshot, "digest", "") or ""):
            return False
        if live_world is not None and world.graph_digest != str(getattr(live_world, "snapshot_digest", "") or ""):
            # After L1 identity GROUND, the bootstrap DATA/KG/EVIDENCE closure
            # remains bound to the immutable base World Model.  Accept the
            # live child only through the exact transition artifact; never
            # rewrite the upstream artifacts under the child authority.
            from app.contracts.cognition.stage_contracts import (
                L1WorldProjectionSnapshot,
            )
            from app.contracts.artifacts.ref import ArtifactRef

            transition = load_artifact(
                dict(state),
                "l1_world_projection",
                L1WorldProjectionSnapshot,
            )
            current_world = load_artifact(
                dict(state),
                "world_model_current_snapshot",
                SessionWorldModelSnapshot,
            )
            if transition is None or current_world is None:
                return False
            base_ref = ArtifactRef.model_validate(
                refs.get("world_model_snapshot")
            )
            current_ref = ArtifactRef.model_validate(
                refs.get("world_model_current_snapshot")
            )
            if not (
                transition.source_world_model_artifact_ref.descriptor_digest
                == base_ref.descriptor_digest
                and transition.source_world_model_snapshot_digest
                == world.graph_digest
                and transition.resulting_world_model_artifact_ref.descriptor_digest
                == current_ref.descriptor_digest
                and transition.resulting_world_model_snapshot_digest
                == current_world.graph_digest
                and current_world.graph_digest
                == str(getattr(live_world, "snapshot_digest", "") or "")
            ):
                return False
        schema_mapping_ref = refs.get("schema_mapping_snapshot") or {}
        if not isinstance(schema_mapping_ref, dict):
            schema_mapping_ref = getattr(schema_mapping_ref, "model_dump", lambda **_: {})()
        external_ref = refs.get("evidence_external_observations") or {}
        if not isinstance(external_ref, dict):
            external_ref = getattr(external_ref, "model_dump", lambda **_: {})()
        gap_ledger_ref = refs.get("evidence_gap_ledger") or {}
        if not isinstance(gap_ledger_ref, dict):
            gap_ledger_ref = getattr(gap_ledger_ref, "model_dump", lambda **_: {})()
        kg_gap_refs = set(str(item) for item in kg_stage.gap_refs if str(item).strip())
        evidence_upstream_gap_refs = set(
            str(item) for item in evidence.upstream_gap_refs if str(item).strip()
        )
        evidence_gap_row_refs = set(
            str(getattr(item, "gap_ref", ""))
            for item in evidence.gap_rows
            if str(getattr(item, "gap_ref", "")).strip()
        )
        schema_mapping_semantic_digest = str(
            getattr(schema_mapping, "mapping_fingerprint", "")
            or getattr(schema_mapping, "decision_fingerprint", "")
            or ""
        )
        from app.contracts.artifacts.ref import ArtifactRef

        def _same_identity(frozen: Any, active: Any) -> bool:
            if frozen is None or active is None:
                return False
            try:
                active_ref = ArtifactRef.model_validate(active)
            except Exception:
                return False
            return all(
                getattr(frozen, field, None) == getattr(active_ref, field)
                for field in ("descriptor_digest", "digest", "semantic_digest")
            )

        return (
            data_stage.source_snapshot_digest == snapshot.digest
            and str(schema_mapping_ref.get("descriptor_digest") or "")
            == kg_stage.schema_mapping_ref
            and schema_mapping_semantic_digest == kg_stage.schema_mapping_digest
            and schema_mapping.source_snapshot_digest == catalog.digest
            and world.schema_mapping_digest == schema_mapping_semantic_digest
            and world.schema_mapping_ref
            == str(schema_mapping_ref.get("descriptor_digest") or "")
            and kg_stage.world_model_snapshot_digest == world.graph_digest
            and evidence.status == "ready"
            and _same_identity(evidence.data_catalog_artifact_ref, refs.get("data_catalog"))
            and _same_identity(evidence.data_snapshot_artifact_ref, refs.get("data_snapshot"))
            and _same_identity(evidence.world_model_artifact_ref, refs.get("world_model_snapshot"))
            and evidence.data_snapshot_digest == snapshot.digest
            and evidence.world_model_snapshot_digest == world.graph_digest
            and evidence.schema_mapping_artifact_ref
            == str(schema_mapping_ref.get("descriptor_digest") or "")
            and evidence.schema_mapping_digest
            == schema_mapping_semantic_digest
            and evidence.external_observations_ref is not None
            and evidence.gap_ledger_ref is not None
            and evidence.external_observations_ref.digest
            == str(external_ref.get("digest") or "")
            and evidence.external_observations_ref.descriptor_digest
            == str(external_ref.get("descriptor_digest") or "")
            and evidence.external_observations_ref.semantic_digest
            == str(external_ref.get("semantic_digest") or "")
            and evidence.gap_ledger_ref.digest
            == str(gap_ledger_ref.get("digest") or "")
            and evidence.gap_ledger_ref.descriptor_digest
            == str(gap_ledger_ref.get("descriptor_digest") or "")
            and evidence.gap_ledger_ref.semantic_digest
            == str(gap_ledger_ref.get("semantic_digest") or "")
            and external.cache_digest == evidence.external_cache_digest
            and kg_gap_refs <= evidence_upstream_gap_refs
            and kg_gap_refs <= evidence_gap_row_refs
            and tuple(gap_ledger.gap_rows) == tuple(evidence.gap_rows)
        )
    except Exception:
        return False


async def _persist_context_stage_artifacts(
    state: Dict[str, Any],
    context: Any,
    *,
    authority_ref: dict[str, Any] | None = None,
    version: str | None = None,
    fingerprint: str | None = None,
) -> Dict[str, Any]:
    """Materialize DATA, KG and EVIDENCE products before any L1 worker runs.

    This helper is deliberately idempotent.  It is called both on a fresh
    bootstrap and on checkpoint replay; every product is content-addressed and
    only bounded references are returned to LangGraph state.
    """

    session_id = str(state.get("session_id") or getattr(context, "session_id", "") or "")
    if not session_id:
        raise RuntimeError("context stage artifacts require session_id")
    derived_version, derived_fingerprint, derived_authority = _context_authority(
        context, session_id=session_id
    )
    version = str(version or derived_version)
    fingerprint = str(fingerprint or derived_fingerprint)
    authority = {**derived_authority, **dict(authority_ref or {})}
    refs = dict(state.get("artifact_refs") or {})
    artifact_state: Dict[str, Any] = {
        **dict(state),
        "session_id": session_id,
        "run_id": str(state.get("run_id") or session_id),
        "context_version": version,
        "context_fingerprint": fingerprint,
        "context_ref": authority,
        "artifact_refs": refs,
    }
    if _context_stage_refs_complete(artifact_state, context):
        from app.contracts.evidence.stage_contracts import EvidenceStageSnapshot
        from app.infrastructure.artifacts.runtime import load_artifact

        evidence_snapshot = load_artifact(
            artifact_state,
            "evidence_snapshot",
            EvidenceStageSnapshot,
        )
        return {
            "evidence_snapshot_status": evidence_snapshot.status,
            "evidence_gap_refs": list(evidence_snapshot.gap_refs),
            "evidence_gap_rows": [
                item.model_dump(mode="json")
                for item in evidence_snapshot.gap_rows
            ],
        }

    catalog = getattr(context, "data_resource_catalog", None)
    data_snapshot = getattr(context, "data_snapshot", None)
    if catalog is None or data_snapshot is None:
        raise RuntimeError("CONTEXT_BOOTSTRAP_FAILED: normalized DATA catalog/snapshot unavailable")
    from app.modules.data.application import DataApplication
    from app.modules.cognition.application import CognitionApplication
    from app.modules.evidence.application import EvidenceApplication

    data_result = await DataApplication().run(
        artifact_state,
        catalog=catalog,
        data_snapshot=data_snapshot,
    )
    refs.update(data_result.to_state_patch()["artifact_refs"])
    artifact_state["artifact_refs"] = refs
    from app.data.resource_catalog import DataResourceCatalog

    authoritative_catalog = DataResourceCatalog(data_result.catalog)
    context.data_resource_catalog = authoritative_catalog
    if getattr(context, "workspace", None) is not None:
        context.workspace.attach_resource_catalog(authoritative_catalog)
    catalog_snapshot = authoritative_catalog.snapshot
    catalog_snapshot_id = str(getattr(catalog_snapshot, "snapshot_id", "") or "")
    source_snapshot_ref = catalog_snapshot_id or str(
        getattr(data_snapshot, "snapshot_id", "") or ""
    )
    cognition_result = await CognitionApplication().bootstrap(
        session_id,
        source_snapshot_ref,
        catalog=authoritative_catalog,
        state=artifact_state,
        village_name=str(getattr(context, "village_name", "") or ""),
        external_observation_snapshot=getattr(
            context, "external_observation_snapshot", None
        ),
    )
    refs.update(cognition_result.to_state_patch()["artifact_refs"])
    artifact_state["artifact_refs"] = refs
    final_authority = {
        **authority,
        "data_resource_catalog_digest": data_result.catalog.digest,
        "world_model_snapshot_ref": cognition_result.snapshot.snapshot_ref,
        "world_model_snapshot_digest": cognition_result.snapshot.graph_digest,
        "world_model_epoch": str(cognition_result.snapshot.version),
    }
    artifact_state["context_ref"] = final_authority
    artifact_state["world_model_snapshot_ref"] = (
        cognition_result.snapshot.snapshot_ref
    )
    artifact_state["world_model_snapshot_digest"] = (
        cognition_result.snapshot.graph_digest
    )
    artifact_state["world_model_epoch"] = str(cognition_result.snapshot.version)

    from app.infrastructure.context_runtime.manager import (
        context_has_cognition_ports,
        get_cached_context,
    )

    published_context = get_cached_context(session_id)
    if not context_has_cognition_ports(
        published_context,
        world_model_mode=str(getattr(context, "world_model_mode", "off") or "off"),
    ):
        raise RuntimeError(
            "CONTEXT_BOOTSTRAP_FAILED: Cognition did not publish WorldModel ports"
        )
    context = published_context
    if str(
        getattr(getattr(context, "world_model", None), "snapshot_digest", "") or ""
    ) != cognition_result.snapshot.graph_digest:
        raise RuntimeError(
            "CONTEXT_BOOTSTRAP_FAILED: published WorldModel digest mismatch"
        )
    fingerprint = "sha256:" + context.content_hash[:16]
    artifact_state["context_fingerprint"] = fingerprint
    evidence_result = await EvidenceApplication().bootstrap(
        artifact_state,
        context=context,
    )
    refs.update(evidence_result.to_state_patch()["artifact_refs"])
    return {
        "artifact_refs": refs,
        "data_snapshot_id": str(getattr(data_snapshot, "snapshot_id", "") or ""),
        "data_snapshot_digest": str(getattr(data_snapshot, "digest", "") or ""),
        "world_model_snapshot_ref": cognition_result.snapshot.snapshot_ref,
        "world_model_snapshot_digest": cognition_result.snapshot.graph_digest,
        "world_model_epoch": str(cognition_result.snapshot.version),
        "context_version": version,
        "context_fingerprint": fingerprint,
        "context_ref": {
            **final_authority,
        },
        "evidence_snapshot_status": evidence_result.snapshot.status,
        "evidence_gap_refs": list(evidence_result.snapshot.gap_refs),
        "evidence_gap_rows": [
            item.model_dump(mode="json")
            for item in evidence_result.snapshot.gap_rows
        ],
    }


async def _hydrate_l1_spatial_facts(state: Dict[str, Any], context: Any) -> None:
    """Attach persisted L1 observation inputs to the planning context."""
    try:
        from app.infrastructure.artifacts.runtime import load_artifact
        from app.contracts.l1.l1_contracts import L1ObservationSnapshot
        from app.contracts.evidence.identity_contracts import EvidenceObservationSnapshot

        snapshot = load_artifact(state, "l1_snapshot", L1ObservationSnapshot)
        if snapshot is None:
            return
        l1_ref = (state.get("artifact_refs") or {}).get("l1_snapshot")
        if isinstance(l1_ref, dict):
            context.l1_snapshot_ref = str(l1_ref.get("digest") or "")
        else:
            context.l1_snapshot_ref = str(getattr(l1_ref, "digest", "") or "")
        mode = str(
            getattr(context, "world_model_mode", "off") or "off"
        ).strip().casefold()
        if (
            mode in {"shadow", "prefer_v2", "v2_only"}
            and (state.get("artifact_refs") or {}).get(
                "l1_world_projection"
            )
        ):
            from app.infrastructure.artifacts.runtime import (
                validate_l1_world_projection_transition,
            )

            validate_l1_world_projection_transition(dict(state))
            projection_ref = (
                state.get("artifact_refs") or {}
            ).get("l1_world_projection") or {}
            context.l1_world_projection_ref = str(
                projection_ref.get("digest")
                if isinstance(projection_ref, dict)
                else getattr(projection_ref, "digest", "")
                or ""
            )
            # In V2 the sidecars are commit/replay inputs, not PlanningContext
            # payloads. L2/L3 retrieve bounded rows through a typed world view.
            context.l1_fact_records = []
            context.location_mentions = []
            context.evidence_observations = []
            context.grounded_bindings = []
            return
        fact_records = list(getattr(snapshot, "fact_records", []) or [])
        facts = list(getattr(snapshot, "location_mentions", []) or [])
        context.l1_fact_records = fact_records
        context.location_mentions = facts

        observation_snapshot = load_artifact(
            state,
            "l1_observations",
            EvidenceObservationSnapshot,
        )
        context.evidence_observations = (
            list(observation_snapshot.observations)
            if observation_snapshot is not None
            else []
        )

        try:
            from app.contracts.evidence.identity_contracts import GroundedEntityBindingSnapshot

            binding_snapshot = load_artifact(
                state,
                "l1_bindings",
                GroundedEntityBindingSnapshot,
            )
            if binding_snapshot is not None:
                context.grounded_bindings = list(binding_snapshot.bindings)
                logger.debug(
                    "[bootstrap] restored %d persisted L1 entity bindings",
                    len(context.grounded_bindings),
                )
        except Exception as exc:
            logger.debug("[bootstrap] persisted L1 bindings unavailable: %s", exc)

        gazetteer_entries = len(
            getattr(getattr(context, "gazetteer", None), "entries", []) or []
        )
        logger.info(
            "[bootstrap] hydrated %d L1 location facts; gazetteer entries=%d",
            len(facts),
            gazetteer_entries,
        )
    except Exception as exc:
        logger.warning("[bootstrap] L1 spatial fact hydration failed: %s", exc)


async def bootstrap_context_node(state: Dict[str, Any]) -> Dict[str, Any]:
    session_id = state.get("session_id", "")
    expected_context_ref = state.get("context_ref") or {}
    expected_snapshot_digest = str(
        expected_context_ref.get("snapshot_digest")
        or expected_context_ref.get("data_snapshot_digest")
        or ""
    )
    expected_world_model_digest = str(
        state.get("world_model_snapshot_digest")
        or expected_context_ref.get("world_model_snapshot_digest")
        or ""
    )
    if state.get("bootstrap_context_done") and state.get("context_version") and session_id:
        # A checkpoint may be resumed in a fresh worker process where the
        # in-process cache is empty.  The boolean is not proof that the
        # PlanningContext is available; rebuild the same authoritative
        # context instead of allowing downstream stages to receive None.
        from app.core.settings import COGNITION_WORLD_MODEL_MODE
        from app.infrastructure.context_runtime.manager import (
            context_has_cognition_ports,
            get_cached_context,
            invalidate_planning_context,
        )

        cached = get_cached_context(session_id)
        if cached is not None:
            cached_snapshot_digest = str(
                getattr(getattr(cached, "data_snapshot", None), "digest", "") or ""
            )
            cached_world_model_digest = str(
                getattr(
                    getattr(cached, "world_model", None),
                    "snapshot_digest",
                    "",
                )
                or ""
            )
            expected_mode = str(
                COGNITION_WORLD_MODEL_MODE or "off"
            ).strip().lower()
            cached_mode = str(
                getattr(cached, "world_model_mode", "off") or "off"
            ).strip().lower()
            if (
                cached_mode != expected_mode
                or (
                    expected_snapshot_digest
                    and cached_snapshot_digest != expected_snapshot_digest
                )
                or (
                    expected_world_model_digest
                    and cached_world_model_digest != expected_world_model_digest
                )
                or not context_has_cognition_ports(
                    cached,
                    world_model_mode=expected_mode,
                )
            ):
                invalidate_planning_context(session_id)
                cached = None
            if cached is None:
                pass
            else:
                await _hydrate_l1_spatial_facts(state, cached)
                try:
                    return await _persist_context_stage_artifacts(state, cached)
                except Exception as exc:
                    logger.error("[bootstrap] cached DATA/KG/EVIDENCE artifacts unavailable: %s", exc)
                    raise RuntimeError(
                        f"CONTEXT_BOOTSTRAP_FAILED: cached stage artifacts unavailable: {exc}"
                    ) from exc
    if not session_id:
        logger.warning("[bootstrap] no session_id; skipping context build")
        raise RuntimeError(
            "CONTEXT_BOOTSTRAP_FAILED: no session_id; cannot establish PlanningContext"
        )

    village_name = str((state.get("config") or {}).get("village_name", ""))
    # V2-authoritative modes require the immutable DATA catalog explicitly.
    # A workflow checkpoint may carry only refs, so reuse a matching live
    # Context catalog when available; callers starting a cold V2 run must put
    # the normalized catalog on the bootstrap state.
    data_catalog = state.get("data_catalog")
    if data_catalog is None:
        try:
            from app.infrastructure.context_runtime.manager import get_cached_context

            cached = get_cached_context(session_id)
            data_catalog = getattr(cached, "data_resource_catalog", None)
        except Exception:
            data_catalog = None
    if data_catalog is None:
        # Cold production sessions do not carry the in-memory catalog in their
        # checkpoint.  Rehydrate it from DATA-owned upload persistence before
        # Context Runtime decides whether V2 can start; never bootstrap a V2
        # run by reconstructing a legacy Bundle.
        try:
            from app.data.catalog.session_resource_catalog import load_session_data_catalog

            data_catalog = await load_session_data_catalog(
                session_id,
                village_name=village_name,
            )
        except Exception as exc:
            logger.debug("[bootstrap] session DATA catalog unavailable: %s", exc)
            data_catalog = None
    boundary_scope_artifact = None
    boundary_scope_ref = (state.get("artifact_refs") or {}).get("boundary_scope")
    if boundary_scope_ref:
        try:
            from app.contracts.data.boundary_contracts import BoundaryScopeArtifact
            from app.infrastructure.artifacts.runtime import load_artifact

            boundary_scope_artifact = load_artifact(
                dict(state), "boundary_scope", BoundaryScopeArtifact
            )
        except Exception as exc:
            logger.debug("[bootstrap] persisted boundary scope unavailable: %s", exc)
    if boundary_scope_artifact is None:
        try:
            from app.data.catalog.session_resource_catalog import load_session_boundary_scope

            boundary_scope_artifact = await load_session_boundary_scope(session_id)
        except Exception as exc:
            logger.debug("[bootstrap] session boundary scope unavailable: %s", exc)
    expected_version = str(
        (state.get("context_ref") or {}).get("version")
        or state.get("context_version")
        or ""
    )
    schema_mapping_snapshot = None
    schema_mapping_artifact_ref = ""
    schema_mapping_ref_value = dict(
        (state.get("artifact_refs") or {}).get("schema_mapping_snapshot")
        or {}
    )
    if schema_mapping_ref_value:
        try:
            from app.contracts.cognition.decision import (
                SourceSemanticMappingSnapshot,
            )
            from app.infrastructure.artifacts.runtime import load_artifact

            schema_mapping_snapshot = load_artifact(
                dict(state),
                "schema_mapping_snapshot",
                SourceSemanticMappingSnapshot,
            )
            schema_mapping_artifact_ref = str(
                schema_mapping_ref_value.get("descriptor_digest") or ""
            )
        except Exception:
            schema_mapping_snapshot = None
            schema_mapping_artifact_ref = ""
    try:
        context = await build_planning_context(
            session_id,
            village_name=village_name or None,
            include_reports=not bool(expected_version),
            version=int(expected_version) if expected_version.isdigit() else None,
            expected_snapshot_digest=expected_snapshot_digest or None,
            expected_world_model_digest=expected_world_model_digest or None,
            data_catalog=data_catalog,
            boundary_scope_artifact=boundary_scope_artifact,
            schema_mapping_snapshot=schema_mapping_snapshot,
            schema_mapping_artifact_ref=schema_mapping_artifact_ref,
            artifact_root=str(state.get("artifact_root") or ""),
            defer_cognition_bootstrap=not bool(
                schema_mapping_snapshot and schema_mapping_artifact_ref
            ),
        )
    except Exception as exc:
        logger.error("[bootstrap] context build failed: %s", exc)
        raise RuntimeError(
            f"CONTEXT_BOOTSTRAP_FAILED: build_planning_context raised {exc}"
        ) from exc

    version = str(getattr(context, "version", 1))
    content_hash = getattr(context, "content_hash", "")
    if not content_hash:
        raise RuntimeError(
            "CONTEXT_BOOTSTRAP_FAILED: context has no content_hash - not frozen"
        )
    fingerprint = "sha256:" + content_hash[:16]

    try:
        from app.contracts.l1.l1_contracts import L1ObservationSnapshot

        l1_snapshot = None
        refs = state.get("artifact_refs") or {}
        l1_ref_data = refs.get("l1_snapshot")
        if l1_ref_data:
            from app.infrastructure.artifacts.runtime import load_artifact

            l1_snapshot = load_artifact(state, "l1_snapshot", L1ObservationSnapshot)
        if l1_snapshot is not None:
            context.location_mentions = list(
                getattr(l1_snapshot, "location_mentions", []) or []
            )
            await _hydrate_l1_spatial_facts(state, context)
    except Exception as exc:
        logger.debug("[bootstrap] L1 location facts unavailable: %s", exc)

    snapshot = getattr(context, "data_snapshot", None)
    snapshot_ref = {
        "snapshot_id": str(getattr(snapshot, "snapshot_id", "") or ""),
        "snapshot_digest": str(getattr(snapshot, "digest", "") or ""),
    }
    world_model_mode = str(getattr(context, "world_model_mode", "off") or "off")
    world_model_snapshot_ref = str(
        getattr(getattr(context, "world_model", None), "snapshot_ref", "")
        or getattr(context, "kg_session_ref", "")
        or getattr(getattr(context, "kg", None), "snapshot_ref", "")
        or ""
    )
    world_model_snapshot_digest = str(
        getattr(getattr(context, "world_model", None), "snapshot_digest", "")
        or getattr(getattr(context, "kg", None), "snapshot_digest", "")
        or ""
    )
    world_model_shadow_snapshot_ref = str(
        getattr(getattr(context, "world_model_shadow", None), "snapshot_ref", "") or ""
    )
    world_model_shadow_snapshot_digest = str(
        getattr(getattr(context, "world_model_shadow", None), "snapshot_digest", "") or ""
    )
    data_catalog_digest = str(
        getattr(getattr(getattr(context, "data_resource_catalog", None), "snapshot", None), "digest", "")
        or ""
    )
    shadow_diff_ref = str(getattr(context, "world_model_shadow_diff_ref", "") or "")
    # The context reference is intentionally flat and bounded.  It is copied
    # into StepReport/artifact provenance; the large catalog and graph stay in
    # their own stores and are addressed by these immutable digests.
    authority_ref = {
        "world_model_mode": world_model_mode,
        "world_model_snapshot_ref": world_model_snapshot_ref,
        "world_model_snapshot_digest": world_model_snapshot_digest,
        "world_model_shadow_snapshot_ref": world_model_shadow_snapshot_ref,
        "world_model_shadow_snapshot_digest": world_model_shadow_snapshot_digest,
        "world_model_shadow_diff_ref": shadow_diff_ref,
        "data_resource_catalog_digest": data_catalog_digest,
        "boundary_scope_ref": str(
            getattr(boundary_scope_artifact, "scope_ref", "") or ""
        ),
        "boundary_digest": str(
            getattr(boundary_scope_artifact, "boundary_digest", "") or ""
        ),
    }
    try:
        stage_patch = await _persist_context_stage_artifacts(
            state,
            context,
            authority_ref=authority_ref,
            version=version,
            fingerprint=fingerprint,
        )
    except Exception as exc:
        logger.error("[bootstrap] DATA/KG/EVIDENCE artifact bootstrap failed: %s", exc)
        raise RuntimeError(
            f"CONTEXT_BOOTSTRAP_FAILED: stage artifacts unavailable: {exc}"
        ) from exc
    return {
        "context_version": version,
        "context_fingerprint": fingerprint,
        "world_model_mode": world_model_mode,
        "world_model_snapshot_ref": world_model_snapshot_ref,
        "world_model_snapshot_digest": world_model_snapshot_digest,
        "world_model_shadow_diff_ref": shadow_diff_ref,
        "context_ref": {
            "session_id": session_id,
            "version": version,
            **snapshot_ref,
            **authority_ref,
        },
        "bootstrap_context_done": True,
        **stage_patch,
    }


__all__ = ["bootstrap_context_node"]
