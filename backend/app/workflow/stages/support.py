"""Shared, stage-neutral helpers for workflow stage adapters."""

from __future__ import annotations

import hashlib
import inspect
from typing import Any, Dict, List

from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
from app.contracts.workflow.workflow_contracts import GateDecision
from app.infrastructure.logging import get_logger
from app.workflow.stage_adapter import (
    STAGE_AUTHORITY_OUTPUT_KEYS,
    StageCompletion,
    persist_gate_decision,
)

logger = get_logger(__name__)

_RETRY_ROUTES: Dict[str, frozenset[str]] = {
    "target_projection": frozenset({"REPAIR", "REVISE", "L3"}),
    "ground": frozenset({"EXPLORE", "HUMAN"}),
    "select": frozenset({"RETRY_GROUND"}),
    "validate": frozenset({"RETRY_EXECUTE", "RETRY_SELECT", "RETRY_GROUND", "RETRY_TARGET_PROJECTION", "RETRY_L3"}),
    "reconcile": frozenset({"RETRY_EXECUTE", "RETRY_L3"}),
    "deliver": frozenset({"RETRY_VALIDATE"}),
}

# These are workflow policy, not implementation details of a particular
# stage.  Keeping them here lets the root graph route gates without importing
# a stage module and accidentally coupling orchestration to business code.
STAGE_FORWARD_TARGET: Dict[str, str] = {
    "l1": "advance_phase",
    "l2": "advance_phase",
    "l3": "target_projection",
    "target_projection": "ground",
    "ground": "select",
    "select": "execute",
    "validate": "reconcile",
    "reconcile": "deliver",
    "deliver": "__end__",
}

GATE_CHANNELS = (
    "target_projection_gate",
    "ground_gate",
    "select_gate",
    "validate_gate",
    "reconcile_gate",
    "deliver_gate",
)


def _pass_gate(stage: str) -> GateDecision:
    """Create the explicit pass decision used by an approved resume."""
    return GateDecision(
        stage=stage,
        passed=True,
        feedback_route=None,
        pending_requests=[],
        evidence_requests=[],
    )


def _gate_route(gate: Any) -> str:
    if gate is None:
        return "PASS"
    route = getattr(gate, "feedback_route", None)
    if route is None and isinstance(gate, dict):
        route = gate.get("feedback_route")
    return route or "PASS"


class UpstreamGateBlockedError(RuntimeError):
    """Raised when a stage cannot prove every required upstream gate.

    The workflow keeps the actual typed gate in CAS.  This exception is only
    the small boundary diagnostic used by direct facades and stage adapters;
    callers can inspect ``stage``, ``route`` and ``reason`` without parsing a
    report or a legacy bundle payload.
    """

    def __init__(self, stage: str, route: str, reason: str) -> None:
        self.stage = str(stage)
        self.route = str(route or "BLOCK")
        self.reason = str(reason or "upstream gate is not complete")
        super().__init__(
            f"UPSTREAM_GATE_BLOCKED: {self.stage} route={self.route}; {self.reason}"
        )


def _gate_pending(gate: Any) -> tuple[list[Any], list[Any]]:
    if isinstance(gate, dict):
        return (
            list(gate.get("pending_requests") or []),
            list(gate.get("evidence_requests") or []),
        )
    return (
        list(getattr(gate, "pending_requests", None) or []),
        list(getattr(gate, "evidence_requests", None) or []),
    )


def _require_gate_output_binding(state: Dict[str, Any], stage: str) -> None:
    """Prove the gate was evaluated against the checkpoint's exact output."""

    output_keys = STAGE_AUTHORITY_OUTPUT_KEYS.get(stage, ())
    if not output_keys:
        return
    refs = dict(state.get("artifact_refs") or {})
    gate_key = f"{stage}_gate"
    raw_gate_ref = refs.get(gate_key)
    if not raw_gate_ref:
        raise UpstreamGateBlockedError(stage, "MISSING", f"missing artifact ref: {gate_key}")
    try:
        gate_ref = ArtifactDescriptor.model_validate(raw_gate_ref)
    except Exception as exc:
        raise UpstreamGateBlockedError(stage, "INVALID", f"invalid artifact ref: {gate_key}") from exc
    for output_key in output_keys:
        raw_output_ref = refs.get(output_key)
        if not raw_output_ref:
            raise UpstreamGateBlockedError(
                stage,
                "MISSING",
                f"gate authority output is absent: {output_key}",
            )
        try:
            output_ref = ArtifactDescriptor.model_validate(raw_output_ref)
        except Exception as exc:
            raise UpstreamGateBlockedError(
                stage,
                "INVALID",
                f"invalid gate authority output ref: {output_key}",
            ) from exc
        bound_digest = str(gate_ref.parent_digests.get(output_key) or "")
        if not bound_digest or bound_digest != output_ref.digest:
            raise UpstreamGateBlockedError(
                stage,
                "STALE",
                (
                    f"gate/output digest mismatch for {output_key}: "
                    f"bound={bound_digest or '<missing>'} current={output_ref.digest}"
                ),
            )


def require_upstream_gates(
    state: Dict[str, Any],
    required_stages: tuple[str, ...] | list[str],
    *,
    allow_pending: bool = False,
    allow_evidence_requests: bool = False,
) -> dict[str, GateDecision]:
    """Prove that all upstream gates are durable, complete and consumable.

    A ``passed`` boolean alone is not sufficient: older evaluators could mark
    a partial artifact as usable while retaining evidence requests.  Spatial
    stages must fail closed for those artifacts.  ``allow_pending`` exists
    only for explicitly bounded recovery callers; production downstream
    stages use the strict default.  ``allow_evidence_requests`` is a narrower
    exception for the EVIDENCE bootstrap: a passed DATA/KG gate may carry
    typed evidence requests for EVIDENCE to consume, but failed gates,
    non-PASS routes and pending requests remain blocking.
    """

    from app.workflow.state import load_root_gate

    normalized_stages = tuple(
        str(raw_stage or "").strip().lower() for raw_stage in required_stages
    )
    if allow_evidence_requests and set(normalized_stages) != {"data", "kg"}:
        raise ValueError(
            "allow_evidence_requests is reserved for the DATA+KG EVIDENCE bootstrap"
        )

    resolved: dict[str, GateDecision] = {}
    for stage in normalized_stages:
        try:
            gate = load_root_gate(dict(state), stage)
        except Exception as exc:
            raise UpstreamGateBlockedError(stage, "MISSING", str(exc)) from exc
        _require_gate_output_binding(state, stage)
        pending, evidence = _gate_pending(gate)
        route = str(gate.feedback_route or ("PASS" if gate.passed else "BLOCK"))
        if not gate.passed or route not in {"PASS", ""}:
            raise UpstreamGateBlockedError(
                stage,
                route,
                _gate_failure_context(gate) or "gate did not pass",
            )
        if pending and (allow_evidence_requests or not allow_pending):
            raise UpstreamGateBlockedError(
                stage,
                "PENDING",
                (
                    f"pending_requests={len(pending)} evidence_requests={len(evidence)}; "
                    "resolve pending requests before consuming this artifact"
                ),
            )
        if evidence and allow_evidence_requests and stage != "kg":
            raise UpstreamGateBlockedError(
                stage,
                "PENDING",
                "only KG evidence requests may be consumed by the EVIDENCE bootstrap",
            )
        if evidence and not (allow_pending or allow_evidence_requests):
            raise UpstreamGateBlockedError(
                stage,
                "PENDING",
                (
                    f"pending_requests={len(pending)} evidence_requests={len(evidence)}; "
                    "resolve evidence gaps before consuming this artifact"
                ),
            )
        resolved[stage] = gate
    return resolved


def _gate_failure_context(gate: Any) -> str:
    if gate is None:
        return ""
    pending = gate.get("pending_requests", []) if isinstance(gate, dict) else getattr(gate, "pending_requests", [])
    evidence = gate.get("evidence_requests", []) if isinstance(gate, dict) else getattr(gate, "evidence_requests", [])
    route = gate.get("feedback_route") if isinstance(gate, dict) else getattr(gate, "feedback_route", None)
    for request in pending or []:
        context = request.get("context") if isinstance(request, dict) else getattr(request, "context", None)
        if isinstance(context, dict):
            for key in ("message", "detail"):
                if context.get(key):
                    return str(context[key])
        request_type = request.get("request_type") if isinstance(request, dict) else getattr(request, "request_type", None)
        if request_type:
            return str(request_type)
    if evidence:
        return str(evidence[0])
    return f"route={route}" if route else ""


def _retry_patch(state: Dict[str, Any], stage: str) -> Dict[str, Any]:
    gate = state.get(f"{stage}_gate")
    if gate is None or _gate_route(gate) not in _RETRY_ROUTES.get(stage, frozenset()):
        return {}
    counts = dict(state.get("retry_counts") or {})
    feedback = dict(state.get("error_feedback") or {})
    patch = {
        "retry_counts": {**counts, stage: counts.get(stage, 0) + 1},
        "error_feedback": {**feedback, stage: _gate_failure_context(gate)},
    }
    if stage == "validate":
        budgets = dict(state.get("validation_budget_used") or {})
        patch["validation_budget_used"] = {
            **budgets,
            "validate": int(budgets.get("validate", 0)) + 1,
        }
    return patch


def _accumulate_gate(gates: List[Any], gate: Any) -> List[Any]:
    return list(gates or []) + ([gate] if gate is not None else [])


def _run_id(state: Dict[str, Any]) -> str:
    return state.get("run_id") or state.get("session_id", "")


def _context_version(state: Dict[str, Any]) -> str:
    return state.get("context_version", "")


def _adopt_context(state: Dict[str, Any], context: Any) -> Dict[str, Any]:
    version = str(getattr(context, "version", "") or "")
    state["context_version"] = version
    snapshot = getattr(context, "data_snapshot", None)
    state["context_ref"] = {
        "session_id": state.get("session_id", ""),
        "version": version,
        "snapshot_id": str(getattr(snapshot, "snapshot_id", "") or ""),
        "snapshot_digest": str(getattr(snapshot, "digest", "") or ""),
        "data_snapshot_digest": str(getattr(snapshot, "digest", "") or ""),
        "data_resource_catalog_digest": str(
            getattr(getattr(getattr(context, "data_resource_catalog", None), "snapshot", None), "digest", "")
            or ""
        ),
        "world_model_mode": str(getattr(context, "world_model_mode", "v2_only") or "v2_only"),
        "world_model_snapshot_ref": str(
            getattr(getattr(context, "world_model", None), "snapshot_ref", "")
            or getattr(getattr(context, "kg", None), "snapshot_ref", "")
            or ""
        ),
        "world_model_snapshot_digest": str(
            getattr(getattr(context, "world_model", None), "snapshot_digest", "")
            or getattr(getattr(context, "kg", None), "snapshot_digest", "")
            or ""
        ),
        "world_model_epoch": str(
            getattr(getattr(context, "world_model", None), "version", "")
            or getattr(getattr(context, "kg", None), "version", "")
            or ""
        ),
    }
    meta = context.snapshot_meta()
    state["context_fingerprint"] = "sha256:" + hashlib.sha256(
        repr(sorted(meta.items())).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "context_version": state["context_version"],
        "context_ref": state["context_ref"],
        "context_fingerprint": state.get("context_fingerprint", ""),
    }


async def _require_context(state: Dict[str, Any]) -> Any:
    from app.workflow.layers.context_bootstrap import bootstrap_context_node
    from app.infrastructure.context_runtime.manager import get_cached_context

    session_id = state.get("session_id", "")
    context = get_cached_context(session_id) if session_id else None
    if context is None:
        await bootstrap_context_node(state)
        context = get_cached_context(session_id) if session_id else None
    if context is None:
        raise RuntimeError("PLANNING_CONTEXT_UNAVAILABLE: bootstrap returned no context")
    try:
        from app.workflow.layers.context_bootstrap import _hydrate_l1_spatial_facts

        await _hydrate_l1_spatial_facts(state, context)
    except Exception as exc:
        logger.warning("[workflow:stage-support] cached context hydration failed: %s", exc)
    expected = _context_version(state)
    actual = str(getattr(context, "version", ""))
    if expected and actual and expected != actual:
        raise RuntimeError(f"CONTEXT_VERSION_MISMATCH: checkpoint={expected} loaded={actual}")
    return context


def _dump(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:
            return obj
    return obj


def _jsonable(obj: Any) -> Any:
    """Recursively reduce worker diagnostics to checkpoint-safe primitives."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(key): _jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(value) for value in obj]
    if hasattr(obj, "model_dump"):
        try:
            return _jsonable(obj.model_dump(mode="json"))
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return _jsonable(vars(obj))
    if hasattr(obj, "tolist"):
        try:
            return _jsonable(obj.tolist())
        except Exception:
            pass
    return str(obj)


def _load_ref_artifact(state: Dict[str, Any], key: str, cls: type | None) -> Any:
    from app.infrastructure.artifacts.runtime import ArtifactReplayError, load_artifact

    try:
        return load_artifact(state, key, cls)
    except ArtifactReplayError:
        raise
    except Exception as exc:
        logger.warning("[workflow:stage-support] ref load failed for %s: %s", key, exc)
        return None


def _load_embedded_artifact(state: Dict[str, Any], descriptor: Dict[str, Any], cls: type | None) -> Any:
    from app.infrastructure.artifacts.runtime import ArtifactReplayError, load_embedded_artifact

    try:
        return load_embedded_artifact(state, descriptor, cls)
    except ArtifactReplayError:
        raise
    except Exception as exc:
        logger.warning("[workflow:stage-support] embedded child load failed: %s", exc)
        return None


def _evaluate_progress_gate(evaluator: Any, report: Any, *, input_artifact_refs: Dict[str, Any], previous_gate: Any) -> Any:
    parameters = inspect.signature(evaluator).parameters.values()
    supports_metadata = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        or parameter.name == "input_artifact_refs"
        for parameter in parameters
    )
    if not supports_metadata:
        return evaluator(report)
    return evaluator(report, input_artifact_refs=input_artifact_refs, previous_gate=previous_gate)


def stage_completion_patch(
    state: Dict[str, Any],
    stage: str,
    *,
    output_refs: Dict[str, Any],
    gate: Any,
    context_patch: Dict[str, Any] | None = None,
    retry_patch: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build the one compact root patch shared by migrated workflow stages."""

    normalized_outputs = {
        key: value if isinstance(value, ArtifactDescriptor) else ArtifactDescriptor.model_validate(value)
        for key, value in output_refs.items()
        if value
    }
    gate_ref = persist_gate_decision(
        state,
        stage,
        gate,
        output_refs=normalized_outputs,
    )
    completion = StageCompletion(
        stage=stage,
        output_refs=normalized_outputs,
        gate_ref=gate_ref,
    )
    gate_payload = _dump(gate)
    serialized = completion.model_dump(mode="json")
    artifact_refs = {
        **normalized_outputs,
        f"{stage}_gate": gate_ref,
    }
    return {
        "artifact_refs": {
            key: value.model_dump(mode="json")
            if isinstance(value, ArtifactDescriptor)
            else value
            for key, value in artifact_refs.items()
        },
        "gate_ref": serialized["gate_ref"],
        f"{stage}_gate": gate_payload,
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), gate_payload),
        **dict(context_patch or {}),
        **dict(retry_patch or {}),
    }


__all__ = [
    "GATE_CHANNELS", "STAGE_FORWARD_TARGET", "_accumulate_gate", "_adopt_context",
    "_dump", "_evaluate_progress_gate", "_gate_route", "_jsonable", "_load_ref_artifact",
    "_load_embedded_artifact", "UpstreamGateBlockedError", "require_upstream_gates",
    "_pass_gate", "_require_context", "_retry_patch", "_run_id",
    "stage_completion_patch",
]
