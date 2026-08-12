from __future__ import annotations

from typing import Any, Dict

from app.services.context.planning_context import build_planning_context
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _hydrate_l1_spatial_facts(state: Dict[str, Any], context: Any) -> None:
    """Attach L1 location facts and materialize their GIS↔KG bindings."""
    try:
        # Context objects can survive in-process while the session KG memory
        # is advanced by target projection/L1 enrichment.  Rebuild the semantic lookup
        # from the persisted session memory before hydrating facts; otherwise
        # the next stage sees the old village-only gazetteer and loses the
        # facility/place bindings created by L1.
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.services.context.planning_context import _load_session_semantic_memory

        session_id = str(state.get("session_id", "") or "")
        kg = getattr(context, "kg", None)
        if session_id and kg is not None:
            restored_gazetteer = build_gazetteer(
                kg,
                getattr(context, "workspace", None),
                _load_session_semantic_memory(session_id),
            )
            if restored_gazetteer.entries:
                context.gazetteer = restored_gazetteer
                if getattr(context, "ports", None) is not None:
                    from app.infrastructure.kg.adapters.gazetteer_adapter import KGGazetteerAdapter

                    context.ports.gazetteer = KGGazetteerAdapter(restored_gazetteer)

        from app.infrastructure.artifacts.runtime import load_artifact
        from app.modules.schema.contracts.l1_contracts import L1Snapshot

        snapshot = load_artifact(state, "l1_snapshot", L1Snapshot)
        if snapshot is None:
            return
        facts = list(getattr(snapshot, "location_facts", []) or [])
        context.location_facts = facts

        from app.infrastructure.kg.enrichment.report_entity_enrichment import (
            _location_fact_mentions,
            _materialize_gis_village_entries,
        )

        bases = list(dict.fromkeys(
            str(item.get("name", ""))[:-1]
            for item in _location_fact_mentions(facts)
            if str(item.get("name", "")).endswith("村")
        ))
        written = _materialize_gis_village_entries(
            getattr(context, "gazetteer", None),
            getattr(context, "workspace", None),
            bases,
        )
        if written and getattr(context, "ports", None) is not None:
            from app.infrastructure.kg.adapters.gazetteer_adapter import KGGazetteerAdapter

            context.ports.gazetteer = KGGazetteerAdapter(context.gazetteer)
        # L1 facts are the authoritative typed spatial evidence.  Rebuild the
        # index after hydration so facilities, roads, water and areas are
        # visible to GROUND in the same snapshot as village bindings.
        from app.evidence.index.place_evidence_index import PlaceEvidenceIndex
        context.evidence_index = PlaceEvidenceIndex.build(context)
        logger.info(
            "[bootstrap] hydrated %d L1 location facts; GIS village bindings=%d; evidence entries=%d",
            len(facts), written, len(getattr(context.evidence_index, "entries", []) or []),
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
        from app.services.context.planning_context import get_cached_context
        cached = get_cached_context(session_id)
        if cached is not None:
            _hydrate_l1_spatial_facts(state, cached)
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
        from app.modules.schema.contracts.l1_contracts import L1Snapshot

        l1_snapshot = None
        refs = state.get("artifact_refs") or {}
        l1_ref_data = refs.get("l1_snapshot")
        if l1_ref_data:
            from app.infrastructure.artifacts.runtime import load_artifact

            l1_snapshot = load_artifact(state, "l1_snapshot", L1Snapshot)
        if l1_snapshot is not None:
            context.location_facts = list(getattr(l1_snapshot, "location_facts", []) or [])
            _hydrate_l1_spatial_facts(state, context)
    except Exception as exc:
        logger.debug("[bootstrap] L1 location facts unavailable: %s", exc)

    return {
        "context_version": version,
        "context_fingerprint": fingerprint,
        "context_ref": {"session_id": session_id, "version": version},
        "bootstrap_context_done": True,
    }


__all__ = ["bootstrap_context_node"]
