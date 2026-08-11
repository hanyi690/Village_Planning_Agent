"""Post-L3 chain resume service (Wave N P5 — HITL interrupt + resume).

Resumes a paused post-L3 chain (human_review interrupt) using the official
LangGraph ``Command(resume=...)`` pattern against the SAME main graph
(``create_unified_planning_graph``) via ``PlanningRuntimeService``. The pause
happens inside the main graph's ``human_review`` node; resuming a different
compiled graph would not see the checkpoint. Resolves final typed outputs from
``artifact_refs`` instead of expecting them inline in AgentState, then persists a lightweight JSON snapshot per session
(``.run-tmp/post_l3/{session_id}``) and returns the result dict.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validate_session_id(session_id: str) -> str:
    if not session_id or not _SAFE_ID.match(session_id) or ".." in session_id:
        raise ValueError(f"unsafe session_id: {session_id!r}")
    return session_id


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return str(obj)


def _dump_artifact(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            return obj
    return obj


class PostL3ResultStore:
    """Lightweight JSON store for post-L3 results under ``.run-tmp/post_l3/``.

    Follows the FilesystemArtifactStore atomic-write pattern: the payload is
    written to a temp file in the same directory, then renamed into place.
    """

    def __init__(self, base_dir: str | Path = ".run-tmp"):
        self.base_dir = Path(base_dir)

    def _session_dir(self, session_id: str) -> Path:
        _validate_session_id(session_id)
        return self.base_dir / "post_l3" / session_id

    def save(self, session_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        d = self._session_dir(session_id)
        d.mkdir(parents=True, exist_ok=True)
        manifest = {
            "session_id": session_id,
            "resolved_at": datetime.now().isoformat(),
            "result": result,
        }
        fd, tmp = tempfile.mkstemp(dir=str(d), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2, default=_json_default)
            os.replace(tmp, d / "result.json")
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        logger.info("[PostL3ResultStore] saved result for session %s", session_id)
        return manifest

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        path = self._session_dir(session_id) / "result.json"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)


def _collect_result(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pick the post-L3 output artifacts out of the final chain state."""
    from app.agent.bootstrap.artifact_runtime import load_artifact

    def artifact(key: str) -> Any:
        try:
            return _dump_artifact(load_artifact(state, key))
        except Exception:
            return None

    return {
        "session_id": state.get("session_id", ""),
        "delivery_manifest": artifact("delivery_manifest"),
        "validation_report": artifact("validation_report"),
        "reconciliation_report": artifact("reconciliation_report"),
        "export_result": artifact("export_result") or {},
        "render_artifacts": artifact("render_artifacts") or {},
        "human_review_items": list(state.get("human_review_items") or []),
        "human_review_decisions": state.get("human_review_decisions"),
        "status": state.get("post_l3_status") or state.get("status", ""),
    }


async def resume_post_l3_chain(session_id: str, decisions: Dict[str, Any]) -> Dict[str, Any]:
    """Resume a paused post-L3 chain and return its final result.

    Args:
        session_id: thread_id of the paused main graph (= planning session id).
        decisions: human review decisions passed to ``interrupt()`` via
            ``Command(resume=...)``.

    Returns:
        dict with the collected final AgentState (delivery_manifest,
        validation_report, reconciliation_report, export_result,
        human_review_decisions, ...).
    """
    from app.services.runtime import PlanningRuntimeService

    await PlanningRuntimeService.ensure_initialized()
    await PlanningRuntimeService.resume_from_interrupt(session_id, decisions)

    final_state = await PlanningRuntimeService.aget_state_values(session_id) or {}

    result = _collect_result(final_state)
    PostL3ResultStore().save(session_id, result)

    logger.info("[post_l3_resume] resumed session %s -> %s", session_id, result["status"])
    return result


__all__ = ["resume_post_l3_chain", "PostL3ResultStore"]
