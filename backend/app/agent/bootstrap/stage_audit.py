"""Stage-level audit wrapper for the real session planning graph.

The wrapper records only references and deterministic fingerprints, never the
large typed payloads that are stored in ArtifactStore.
"""

from __future__ import annotations

import hashlib
import json
import time
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _checksum(value: Any) -> str:
    raw = json.dumps(_jsonable(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _gate_route(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("feedback_route") or ("PASS" if value.get("passed") else None)
    return getattr(value, "feedback_route", None) or ("PASS" if getattr(value, "passed", False) else None)


def _input_snapshot(state: Dict[str, Any], stage: str) -> Dict[str, Any]:
    return {
        "artifact_refs": state.get("artifact_refs") or {},
        "context_ref": state.get("context_ref") or {
            "session_id": state.get("session_id", ""),
            "version": state.get("context_version", ""),
        },
        "source_refs": state.get("uploaded_files") or state.get("metadata", {}).get("source_refs", []),
        "input_checksum": _checksum({
            "stage": stage,
            "artifact_refs": state.get("artifact_refs") or {},
            "context_ref": state.get("context_ref") or {},
            "source_refs": state.get("uploaded_files") or [],
        }),
    }


async def _save(session_id: str, stage: str, step_name: str, **kwargs: Any) -> None:
    if not session_id:
        return
    try:
        from app.services.step_report import save_step_report

        await save_step_report(session_id, stage, step_name=step_name, **kwargs)
    except Exception:
        # Audit persistence must never turn a domain result into a different
        # result; the stage itself remains responsible for its own failure.
        return


def audited_stage(stage: str) -> Callable[[Callable[..., Awaitable[Dict[str, Any]]]], Callable[..., Awaitable[Dict[str, Any]]]]:
    """Decorate an async graph node with started/completed/failed reports."""
    def decorator(fn: Callable[..., Awaitable[Dict[str, Any]]]):
        @wraps(fn)
        async def wrapper(state: Dict[str, Any]) -> Dict[str, Any]:
            started = time.perf_counter()
            session_id = state.get("session_id", "")
            step_name = fn.__name__
            inputs = _input_snapshot(state, stage)
            await _save(
                session_id, stage, step_name,
                inputs=inputs,
                diagnostics={"status": "stage_started", "attempt": (state.get("retry_counts") or {}).get(stage.lower(), 0) + 1},
            )
            try:
                result = await fn(state)
                result = result or {}
                refs = result.get("artifact_refs") or {}
                outputs = {
                    "artifact_refs": refs,
                    "output_keys": sorted(k for k in result if k not in {"planned_state", "parcel_changeset", "allocated_geojson"}),
                    "output_checksum": _checksum(refs),
                }
                gate = next((result.get(k) for k in result if k.endswith("_gate")), None)
                await _save(
                    session_id, stage, step_name,
                    inputs=inputs,
                    outputs=outputs,
                    artifacts=[{"key": key, **(ref or {})} for key, ref in refs.items() if ref],
                    diagnostics={
                        "status": "stage_completed",
                        "gate_route": _gate_route(gate),
                        "attempt": (state.get("retry_counts") or {}).get(stage.lower(), 0) + 1,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )
                return result
            except Exception as exc:
                await _save(
                    session_id, stage, step_name,
                    inputs=inputs,
                    diagnostics={
                        "status": "stage_failed",
                        "diagnostic_code": f"{stage.lower()}_{type(exc).__name__.lower()}",
                        "attempt": (state.get("retry_counts") or {}).get(stage.lower(), 0) + 1,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )
                raise
        return wrapper
    return decorator


__all__ = ["audited_stage"]
