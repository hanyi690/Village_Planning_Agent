from __future__ import annotations

import hashlib
import json
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
    """Attach L1 facts and build the GIS/KG evidence index once per snapshot."""
    try:
        from app.infrastructure.artifacts.runtime import load_artifact
        from app.contracts.domain.l1_contracts import L1Snapshot

        snapshot = load_artifact(state, "l1_snapshot", L1Snapshot)
        if snapshot is None:
            return
        facts = list(getattr(snapshot, "location_facts", []) or [])
        context.location_facts = facts

        from app.infrastructure.context.planning_context_factory import _load_session_semantic_memory

        session_id = str(state.get("session_id", "") or "")
        memory = _load_session_semantic_memory(session_id) if session_id else None
        hydration_key = _spatial_hydration_key(state, context, facts, memory)
        if (
            getattr(context, "evidence_index", None) is not None
            and getattr(context, "evidence_index_key", "") == hydration_key
        ):
            logger.debug(
                "[bootstrap] L1 spatial evidence already hydrated key=%s facts=%d",
                hydration_key[:12],
                len(facts),
            )
            return

        # 统一接地核心（设计 §7）：回填/绑定/索引全部收敛到 domain/ground。
        # 水合路径 bump=False（只准备证据，不写注解、不 bump kg_version）。
        from app.domain.ground.anchors import ground_l1_anchors
        from app.infrastructure.paths import session_run_dir

        cache_path = None
        if session_id:
            try:
                cache_path = session_run_dir(session_id) / "grounded-anchor-cache.json"
            except Exception:
                cache_path = None
        await ground_l1_anchors(
            context,
            session_id,
            cache_path=cache_path,
            llm=None,
            bump=False,
        )
        context.evidence_index_key = hydration_key
        gazetteer_entries = len(
            getattr(getattr(context, "gazetteer", None), "entries", []) or []
        )
        logger.info(
            "[bootstrap] hydrated %d L1 location facts; gazetteer entries=%d; evidence entries=%d; key=%s",
            len(facts),
            gazetteer_entries,
            len(getattr(context.evidence_index, "entries", []) or []),
            hydration_key[:12],
        )
    except Exception as exc:
        logger.warning("[bootstrap] L1 spatial fact hydration failed: %s", exc)


async def bootstrap_context_node(state: Dict[str, Any]) -> Dict[str, Any]:
    session_id = state.get("session_id", "")
    if state.get("bootstrap_context_done") and state.get("context_version") and session_id:
        # A checkpoint may be resumed in a fresh worker process where the
        # in-process cache is empty.  The boolean is not proof that the
        # PlanningContext is available; rebuild the same authoritative
        # context instead of allowing downstream stages to receive None.
        from app.infrastructure.context.planning_context_factory import get_cached_context
        cached = get_cached_context(session_id)
        if cached is not None:
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

    return {
        "context_version": version,
        "context_fingerprint": fingerprint,
        "context_ref": {"session_id": session_id, "version": version},
        "bootstrap_context_done": True,
    }


__all__ = ["bootstrap_context_node"]
