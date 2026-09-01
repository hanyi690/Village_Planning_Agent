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

from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.core.common.gate_progress import canonical_input_checksum, canonical_output_checksum


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


def _output_snapshot(value: Any, *, depth: int = 0) -> Any:
    """Keep stage outputs inspectable without copying typed GIS payloads.

    StepReport is an audit record, not a second artifact store.  It therefore
    records scalar metadata and collection sizes while leaving full payloads
    behind the artifact refs.
    """
    if depth >= 2:
        if isinstance(value, dict):
            result = {"keys": list(value)[:20], "key_count": len(value)}
            if isinstance(value.get("features"), list):
                result["feature_count"] = len(value["features"])
            return result
        if isinstance(value, (list, tuple)):
            return {"items": len(value)}
    if isinstance(value, dict):
        return {
            str(key): _output_snapshot(item, depth=depth + 1)
            for key, item in list(value.items())[:40]
            if key not in {"planned_state", "parcel_changeset", "spatial_changeset"}
        }
    if isinstance(value, (list, tuple)):
        return {"items": len(value), "sample": [_output_snapshot(item, depth=depth + 1) for item in value[:3]]}
    if isinstance(value, str) and len(value) > 800:
        return {"chars": len(value), "preview": value[:500]}
    return value


def _gate_route(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("feedback_route") or ("PASS" if value.get("passed") else None)
    return getattr(value, "feedback_route", None) or ("PASS" if getattr(value, "passed", False) else None)


def _gate_field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _semantic_refs(refs: Dict[str, Any] | None) -> Dict[str, Any]:
    """Return deterministic artifact identities without storage metadata."""
    result: Dict[str, Any] = {}
    for key, ref in sorted((refs or {}).items()):
        if isinstance(ref, dict):
            result[key] = {
                "schema_id": ref.get("schema_id", ""),
                "schema_version": ref.get("schema_version", ""),
                "identity": ref.get("descriptor_digest", ""),
                "blob_digest": ref.get("digest", ""),
                "parent_digests": ref.get("parent_digests", {}),
                "run_id": ref.get("run_id", ""),
                "branch_id": ref.get("branch_id", ""),
            }
        else:
            result[key] = semantic_checksum(ref)
    return result


def _stage_route(gate: Any, result: Dict[str, Any]) -> str:
    route = _gate_route(gate)
    if route:
        return route
    return "DIAGNOSTIC" if result.get("fatal_error") or result.get("execution_errors") else "PASS"


def _stage_reason(gate: Any, result: Dict[str, Any], route: str) -> str:
    reason = str(_gate_field(gate, "route_reason", "") or "")
    if reason:
        return reason
    if result.get("fatal_error"):
        return "stage_output_fatal_error"
    if result.get("execution_errors"):
        return "stage_output_execution_errors"
    return f"stage_output_{route.lower()}"


def _stage_issue_fingerprint(gate: Any, result: Dict[str, Any]) -> str:
    """Fingerprint all actionable issues, including gate requests."""
    pending = _gate_field(gate, "pending_requests", []) or []
    issues = _gate_field(gate, "issues", []) or []
    return semantic_checksum({
        "gate_issue_fingerprint": _gate_field(gate, "issue_fingerprint", ""),
        "pending_requests": pending,
        "gate_issues": issues,
        "validation_issues": result.get("validation_issues") or [],
        "diagnostics": result.get("diagnostics") or [],
        "errors": result.get("execution_errors") or [],
    })


def _semantic_stage_output(result: Dict[str, Any], refs: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "artifact_refs": _semantic_refs(refs),
        "stage_outputs": {
            key: value
            for key, value in result.items()
            if not key.endswith("_gate")
            and key not in {"artifact_refs", "planned_state", "parcel_changeset", "spatial_changeset"}
        },
    }


def _input_snapshot(state: Dict[str, Any], stage: str) -> Dict[str, Any]:
    refs = _semantic_refs(state.get("artifact_refs") or {})
    context_ref = state.get("context_ref") or {
        "session_id": state.get("session_id", ""),
        "version": state.get("context_version", ""),
    }
    sources = list(state.get("metadata", {}).get("source_refs", []) or [])
    try:
        from app.infrastructure.context_runtime.manager import get_cached_context

        context = get_cached_context(str(state.get("session_id", "")))
        if context is not None and context.data_snapshot is not None:
            sources.extend(
                f"{item.key}:{item.digest}"
                for item in context.data_snapshot.collections
            )
    except Exception:
        pass
    return {
        "artifact_refs": refs,
        "context_ref": context_ref,
        "source_refs": sources,
        "input_checksum": canonical_input_checksum(state.get("artifact_refs") or {}),
    }


def build_input_audit(
    state: Dict[str, Any],
    *,
    stage: str,
    source_refs: list[str] | None = None,
    artifact_refs: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build the same ref/checksum input contract for layer aggregates."""
    refs = artifact_refs if artifact_refs is not None else state.get("artifact_refs") or {}
    refs = _semantic_refs(refs)
    context_ref = state.get("context_ref") or {
        "session_id": state.get("session_id", ""),
        "version": state.get("context_version", ""),
    }
    sources = list(source_refs or [])
    return {
        "artifact_refs": refs,
        "context_ref": context_ref,
        "source_refs": sources,
        "input_checksum": canonical_input_checksum(artifact_refs if artifact_refs is not None else state.get("artifact_refs") or {}),
    }


async def _save(session_id: str, stage: str, step_name: str, **kwargs: Any) -> None:
    if not session_id:
        return
    try:
        from app.infrastructure.reports.step_report import save_step_report

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
            diagnostics={"status": "stage_started", "attempt": (state.get("retry") or state.get("retry_counts") or {}).get(stage.lower(), 0) + 1},
            )
            try:
                result = await fn(state)
                result = result or {}
                refs = result.get("artifact_refs") or {}
                gate = next((result.get(k) for k in result if k.endswith("_gate")), None)
                route = _stage_route(gate, result)
                semantic_output = _semantic_stage_output(result, refs)
                canonical_input = inputs["input_checksum"]
                canonical_output = canonical_output_checksum(semantic_output)
                if gate is not None:
                    audit_record = {
                        "input_checksum": str(_gate_field(gate, "input_checksum", "") or "") or canonical_input,
                        "output_checksum": str(_gate_field(gate, "output_checksum", "") or "") or canonical_output,
                        "issue_fingerprint": str(_gate_field(gate, "issue_fingerprint", "") or ""),
                        "route_reason": str(_gate_field(gate, "route_reason", "") or ""),
                        "progress_made": _gate_field(gate, "progress_made", None),
                    }
                else:
                    current_input = canonical_input
                    output_checksum = canonical_output
                    previous_audit = (state.get("stage_audit") or {}).get(stage, {})
                    previous_input = str(previous_audit.get("input_checksum") or "")
                    previous_output = str(previous_audit.get("output_checksum") or "")
                    has_previous = bool(previous_input or previous_output)
                    semantic_changed = (
                        not has_previous
                        or current_input != previous_input
                        or output_checksum != previous_output
                    )
                    stage_outputs_present = bool(
                        refs
                        or any(
                            key not in {"artifact_refs", "planned_state", "parcel_changeset", "spatial_changeset"}
                            and not key.endswith("_gate")
                            for key in result
                        )
                    )
                    audit_record = {
                        "input_checksum": current_input,
                        "output_checksum": output_checksum,
                        "issue_fingerprint": _stage_issue_fingerprint(None, result),
                        "route_reason": _stage_reason(None, result, route),
                        "progress_made": semantic_changed and stage_outputs_present,
                    }
                inputs = {**inputs, "input_checksum": audit_record["input_checksum"]}
                outputs = {
                    "artifact_refs": _semantic_refs(refs),
                    "output_keys": sorted(k for k in result if k not in {"planned_state", "parcel_changeset", "spatial_changeset"}),
                    "output_summary": _output_snapshot({
                        **result,
                        "artifact_refs": _semantic_refs(refs),
                    }),
                    "output_checksum": audit_record["output_checksum"],
                }
                gate_audit = {
                    "gate_input_checksum": audit_record["input_checksum"],
                    "gate_output_checksum": audit_record["output_checksum"],
                    "issue_fingerprint": audit_record["issue_fingerprint"],
                    "route_reason": audit_record["route_reason"],
                    "progress_made": audit_record["progress_made"],
                }
                await _save(
                    session_id, stage, step_name,
                    inputs=inputs,
                    outputs=outputs,
                    artifacts=[{"key": key, **(ref or {})} for key, ref in refs.items() if ref],
                    diagnostics={
                        "status": "stage_completed",
                        "gate_route": route,
                        "attempt": (state.get("retry") or state.get("retry_counts") or {}).get(stage.lower(), 0) + 1,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        **gate_audit,
                    },
                )
                return {**result, "stage_audit": {stage: audit_record}}
            except Exception as exc:
                await _save(
                    session_id, stage, step_name,
                    inputs=inputs,
                    diagnostics={
                        "status": "stage_failed",
                        "diagnostic_code": f"{stage.lower()}_{type(exc).__name__.lower()}",
                        "attempt": (state.get("retry") or state.get("retry_counts") or {}).get(stage.lower(), 0) + 1,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )
                raise
        return wrapper
    return decorator


__all__ = ["audited_stage", "build_input_audit"]
