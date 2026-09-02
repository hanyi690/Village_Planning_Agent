"""Candidate-only evidence tools for the LLM.

The LLM can inspect bounded evidence and request verified bundle geometry by
feature reference.  It cannot create or overwrite a BSM, entity, relation, or
geometry record.
"""

from __future__ import annotations

from typing import Any, Annotated, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from .shared import budget_check, tool_reply


async def _context_for_session(session_id: str, village_name: str = "") -> Any | None:
    try:
        from app.infrastructure.evidence_runtime.context_hydration import prepare_evidence_context

        return await prepare_evidence_context(
            session_id,
            village_name=village_name,
            include_reports=True,
        )
    except Exception:
        return None


async def data_geometry_by_ref_impl(
    session_id: str,
    geometry_ref: str,
) -> dict[str, Any]:
    """Resolve one opaque DATA geometry ref for V2 LLM inspection.

    The model cannot submit a new coordinate or field selector.  The ref must
    already occur in the normalized catalog snapshot (source, resource,
    representation, or geometry identity); GROUND remains the execution
    authority and re-resolves it before producing a planned layer.
    """
    context = await _context_for_session(session_id)
    catalog = getattr(context, "data_resource_catalog", None) if context else None
    ref = str(geometry_ref or "").strip()
    if catalog is None or not ref:
        return {"success": False, "error": "DATA catalog or geometry_ref unavailable"}
    snapshot = getattr(catalog, "snapshot", None)
    try:
        from app.data.admission import (
            assert_current_world_catalog,
            build_admission_index,
        )

        assert_current_world_catalog(snapshot)
        admission_index = build_admission_index(snapshot)
    except (TypeError, ValueError):
        return {
            "success": False,
            "error": "DATA catalog current-world admission is not valid",
        }
    features = list(getattr(snapshot, "features", ()) or ())
    representations = list(getattr(snapshot, "representations", ()) or ())
    allowed = set()
    bare_counts: dict[str, int] = {}
    for feature in features:
        source_ref = str(getattr(feature, "source_feature_ref", "") or "")
        bare_counts[source_ref] = bare_counts.get(source_ref, 0) + 1
    for feature in features:
        feature_key = (
            str(getattr(feature, "dataset_ref", "") or ""),
            str(getattr(feature, "source_feature_ref", "") or ""),
        )
        if feature_key not in admission_index.feature_keys:
            continue
        resource_ref = (
            f"resource:{feature_key[0]}:{feature_key[1]}"
        )
        allowed.update(
            str(value).strip()
            for value in (
                feature_key[1] if bare_counts.get(feature_key[1]) == 1 else "",
                resource_ref,
            )
            if str(value or "").strip()
        )
    for representation in representations:
        if str(getattr(representation, "representation_ref", "") or "") not in admission_index.representation_refs:
            continue
        allowed.update(
            str(value).strip()
            for value in (
                getattr(representation, "representation_ref", ""),
                getattr(representation, "resource_ref", ""),
                getattr(representation, "geometry_ref", ""),
            )
            if str(value or "").strip()
        )
    if ref not in allowed:
        return {"success": False, "error": "geometry_ref is not present in DATA catalog", "geometry_ref": ref}
    geometry = catalog.resolve_geometry(
        resource_ref=ref,
        geometry_ref=ref,
        representation_ref=ref,
    )
    if geometry is None:
        return {"success": False, "error": "DATA ref has no executable geometry", "geometry_ref": ref}
    return budget_check(
        {
            "success": True,
            "geometry_ref": ref,
            "geometry_authority": "data_resource_catalog",
            "geometry": geometry,
        },
        hard_limit=6000,
    )


@tool
async def data_geometry_by_ref(
    session_id: str = "",
    geometry_ref: str = "",
    state: Annotated[Optional[dict[str, Any]], InjectedState()] = None,
) -> str:
    """仅按 EvidencePacket 已返回的 DATA opaque ref 读取几何。"""
    if not session_id and state:
        session_id = str(state.get("session_id", "") or "")
    return tool_reply(await data_geometry_by_ref_impl(session_id, geometry_ref))


__all__ = [
    "data_geometry_by_ref",
    "data_geometry_by_ref_impl",
]
