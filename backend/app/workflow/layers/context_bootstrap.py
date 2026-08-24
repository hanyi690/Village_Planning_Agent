from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict

from app.infrastructure.context.planning_context_factory import build_planning_context
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(mode="json"))
        except Exception:
            pass
    if hasattr(value, "to_dict"):
        try:
            return _jsonable(value.to_dict())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _spatial_hydration_key(
    state: Dict[str, Any],
    context: Any,
    facts: list[Any],
    memory: Any,
) -> str:
    snapshot = getattr(context, "data_snapshot", None)
    payload = {
        "context_version": getattr(context, "version", 0),
        "kg_version": getattr(context, "kg_version", 0),
        "snapshot_digest": getattr(snapshot, "digest", ""),
        "l1_snapshot_ref": _jsonable((state.get("artifact_refs") or {}).get("l1_snapshot")),
        "facts": _jsonable(facts),
        "memory": _jsonable(memory),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _context_reports_text(context: Any) -> str:
    """Join the current-state report bodies into one evidence text."""
    parts: list[str] = []
    for payload in dict(getattr(context, "reports", {}) or {}).values():
        if isinstance(payload, dict):
            parts.append(str(payload.get("content") or payload.get("summary") or ""))
        else:
            parts.append(str(payload or ""))
    return "\n".join(part for part in parts if part)[:12000]


async def _hydrate_l1_spatial_facts(state: Dict[str, Any], context: Any) -> None:
    """Attach L1 facts and build the GIS/KG EvidenceGraph once per snapshot."""
    try:
        from app.infrastructure.artifacts.runtime import load_artifact
        from app.contracts.domain.l1_contracts import L1Snapshot

        snapshot = load_artifact(state, "l1_snapshot", L1Snapshot)
        if snapshot is None:
            return
        l1_ref = (state.get("artifact_refs") or {}).get("l1_snapshot")
        if isinstance(l1_ref, dict):
            context.l1_snapshot_ref = str(l1_ref.get("digest") or "")
        else:
            context.l1_snapshot_ref = str(getattr(l1_ref, "digest", "") or "")
        fact_records = list(getattr(snapshot, "fact_records", []) or [])
        facts = list(getattr(snapshot, "location_facts", []) or [])
        context.l1_fact_records = fact_records
        # The raw-input register is produced only by L1 and is restored as an
        # immutable downstream input.  Later stages must never re-parse the
        # session's raw ``village_data`` document.
        context.l1_input_register = getattr(snapshot, "input_register", None)
        context.location_facts = facts

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

        from app.infrastructure.context.planning_context_factory import _load_session_semantic_memory

        session_id = str(state.get("session_id", "") or "")
        memory = _load_session_semantic_memory(session_id) if session_id else None
        hydration_key = _spatial_hydration_key(
            state,
            context,
            [*facts, *fact_records],
            memory,
        )
        if (
            getattr(context, "evidence_graph", None) is not None
            and getattr(context, "evidence_graph_key", "") == hydration_key
        ):
            logger.debug(
                "[bootstrap] L1 spatial evidence already hydrated key=%s facts=%d",
                hydration_key[:12],
                len(facts),
            )
            return

        # A completed L1 grounding wave is a durable artifact.  On resume or
        # after a process restart, restore it before considering a new
        # hydration pass; otherwise the same anchors are recomputed merely
        # because the in-process PlanningContext cache was lost.
        persisted_anchors = []
        try:
            from app.contracts.spatial.grounding_contracts import GroundedAnchor

            payload = load_artifact(state, "grounded_anchors")
            if isinstance(payload, list):
                persisted_anchors = [
                    item if isinstance(item, GroundedAnchor) else GroundedAnchor.model_validate(item)
                    for item in payload
                    if isinstance(item, (dict, GroundedAnchor))
                ]
        except Exception as exc:
            logger.debug("[bootstrap] persisted grounded anchors unavailable: %s", exc)
        if persisted_anchors:
            context.grounded_anchors = persisted_anchors
            kg = getattr(context, "kg", None)
            if kg is not None:
                try:
                    from app.domain.ground.anchors import _inject_anchors_into_kg

                    _inject_anchors_into_kg(context, kg, persisted_anchors, session_id)
                except Exception as exc:
                    logger.warning("[bootstrap] persisted anchor KG replay failed: %s", exc)
            try:
                from app.evidence.retrieval.evidence_graph import EvidenceGraph

                context.evidence_graph = EvidenceGraph.build(context)
            except Exception as exc:
                logger.warning("[bootstrap] persisted anchor evidence rebuild failed: %s", exc)
            context.evidence_graph_key = hydration_key
            logger.info(
                "[bootstrap] restored %d persisted L1 anchors; skipped recomputation",
                len(persisted_anchors),
            )
            return

        # 统一接地核心（设计 §7）：回填/绑定/索引全部收敛到 domain/ground。
        # 水合路径 bump=False（只准备证据，不写注解、不 bump kg_version）。
        from app.domain.ground.anchors import ground_l1_anchors
        from app.infrastructure.paths import session_run_dir
        from app.spatial.grounding.call_budget import get_ground_llm_budget

        cache_path = None
        if session_id:
            try:
                cache_path = session_run_dir(session_id) / "grounded-anchor-cache.json"
            except Exception:
                cache_path = None
        grounding_llm = None
        llm_disabled = str(os.getenv("GROUND_LLM_ENABLED", "false")).strip().lower() not in {
            "1", "true", "yes", "on"
        } or any(
            str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}
            for name in ("DISABLE_GROUND_LLM", "DISABLE_GROUND_REPORT_LLM")
        )
        if not llm_disabled:
            try:
                from app.spatial.grounding.report_grounder import create_grounding_llm

                grounding_llm = create_grounding_llm()
            except Exception as exc:
                logger.debug("[bootstrap] grounding LLM unavailable: %s", exc)

        await ground_l1_anchors(
            context,
            session_id,
            cache_path=cache_path,
            llm=grounding_llm,
            bump=False,
            ground_llm_budget=get_ground_llm_budget(
                context,
                scope_key=f"workflow:{session_id}",
            ),
        )
        context.evidence_graph_key = hydration_key
        gazetteer_entries = len(
            getattr(getattr(context, "gazetteer", None), "entries", []) or []
        )
        logger.info(
            "[bootstrap] hydrated %d L1 location facts; gazetteer entries=%d; evidence entries=%d; key=%s",
            len(facts),
            gazetteer_entries,
            len(context.evidence_graph.iter_entries()) if context.evidence_graph is not None else 0,
            hydration_key[:12],
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
    if state.get("bootstrap_context_done") and state.get("context_version") and session_id:
        # A checkpoint may be resumed in a fresh worker process where the
        # in-process cache is empty.  The boolean is not proof that the
        # PlanningContext is available; rebuild the same authoritative
        # context instead of allowing downstream stages to receive None.
        from app.infrastructure.context.planning_context_factory import get_cached_context
        cached = get_cached_context(session_id)
        if cached is not None:
            cached_snapshot_digest = str(
                getattr(getattr(cached, "data_snapshot", None), "digest", "") or ""
            )
            if expected_snapshot_digest and cached_snapshot_digest != expected_snapshot_digest:
                from app.infrastructure.context.planning_context_factory import invalidate_planning_context

                invalidate_planning_context(session_id)
                cached = None
            if cached is None:
                pass
            else:
                await _hydrate_l1_spatial_facts(state, cached)
                return {}
    if not session_id:
        logger.warning("[bootstrap] no session_id; skipping context build")
        raise RuntimeError(
            "CONTEXT_BOOTSTRAP_FAILED: no session_id; cannot establish PlanningContext"
        )

    village_name = str((state.get("config") or {}).get("village_name", ""))
    expected_version = str(
        (state.get("context_ref") or {}).get("version")
        or state.get("context_version")
        or ""
    )
    try:
        context = await build_planning_context(
            session_id,
            village_name=village_name or None,
            include_reports=not bool(expected_version),
            version=int(expected_version) if expected_version.isdigit() else None,
            expected_snapshot_digest=expected_snapshot_digest or None,
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
        from app.contracts.domain.l1_contracts import L1Snapshot

        l1_snapshot = None
        refs = state.get("artifact_refs") or {}
        l1_ref_data = refs.get("l1_snapshot")
        if l1_ref_data:
            from app.infrastructure.artifacts.runtime import load_artifact

            l1_snapshot = load_artifact(state, "l1_snapshot", L1Snapshot)
        if l1_snapshot is not None:
            context.location_facts = list(getattr(l1_snapshot, "location_facts", []) or [])
            await _hydrate_l1_spatial_facts(state, context)
    except Exception as exc:
        logger.debug("[bootstrap] L1 location facts unavailable: %s", exc)

    snapshot = getattr(context, "data_snapshot", None)
    snapshot_ref = {
        "snapshot_id": str(getattr(snapshot, "snapshot_id", "") or ""),
        "snapshot_digest": str(getattr(snapshot, "digest", "") or ""),
    }
    return {
        "context_version": version,
        "context_fingerprint": fingerprint,
        "context_ref": {
            "session_id": session_id,
            "version": version,
            **snapshot_ref,
        },
        "bootstrap_context_done": True,
    }


__all__ = ["bootstrap_context_node"]
