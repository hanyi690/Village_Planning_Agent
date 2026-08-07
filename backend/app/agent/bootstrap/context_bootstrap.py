from __future__ import annotations

import hashlib
from typing import Any, Dict

from app.services.context.planning_context import build_planning_context
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def bootstrap_context_node(state: Dict[str, Any]) -> Dict[str, Any]:
    if state.get("bootstrap_context_done"):
        return {}

    session_id = state.get("session_id", "")
    if not session_id:
        logger.warning("[bootstrap] no session_id; skipping context build")
        return {"bootstrap_context_done": True, "context_version": "", "context_fingerprint": ""}

    village_name = str((state.get("config") or {}).get("village_name", ""))
    try:
        context = await build_planning_context(session_id, village_name=village_name or None)
    except Exception as exc:
        logger.error("[bootstrap] context build failed: %s", exc)
        return {"bootstrap_context_done": True, "context_version": "", "context_fingerprint": ""}

    version = str(getattr(context, "version", 1))
    meta = context.snapshot_meta()
    fingerprint_input = repr(sorted(meta.items()))
    fingerprint = "sha256:" + hashlib.sha256(
        fingerprint_input.encode("utf-8")
    ).hexdigest()[:16]

    try:
        from app.modules.schema.contracts.l1_contracts import L1Snapshot

        l1_snapshot = None
        refs = state.get("artifact_refs") or {}
        l1_ref_data = refs.get("l1_snapshot")
        if l1_ref_data:
            from app.modules.ports.artifact_store import ArtifactRef
            from app.services.artifact_store import FilesystemArtifactStore

            ref = ArtifactRef(**l1_ref_data)
            payload = FilesystemArtifactStore().retrieve(ref)
            l1_snapshot = L1Snapshot(**payload)
        if l1_snapshot is not None:
            context.location_facts = list(getattr(l1_snapshot, "location_facts", []) or [])
    except Exception as exc:
        logger.debug("[bootstrap] L1 location facts unavailable: %s", exc)

    return {
        "context_version": version,
        "context_fingerprint": fingerprint,
        "context_ref": {"session_id": session_id, "version": version},
        "bootstrap_context_done": True,
    }


__all__ = ["bootstrap_context_node"]
