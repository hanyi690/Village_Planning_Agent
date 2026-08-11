"""Main-graph post-L3 node functions (Wave M).

Each function is a LangGraph node operating on the main ``AgentState`` dict
(single state source). It reads the typed inputs produced by the previous
stage, calls the underlying deterministic aggregate (PARSE/GROUND/SELECT/
EXECUTE/VALIDATE/RECONCILE/DELIVER), evaluates the stage gate and writes the
typed artifacts + gate back into the shared AgentState.

The main graph uses these nodes directly so the L3 gate PASS flows into PARSE
without a wrapper graph or a ``gis_agent`` black-box node.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.modules.schema.contracts.workflow_contracts import GateDecision
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Stage -> routes that indicate a retryable outcome (the node owns the counter).
_RETRY_ROUTES: Dict[str, frozenset[str]] = {
    "parse": frozenset({"REPAIR", "REVISE"}),
    "ground": frozenset({"EXPLORE"}),
    "select": frozenset({"RETRY_GROUND"}),
    "validate": frozenset({"RETRY_EXECUTE", "RETRY_SELECT", "RETRY_GROUND", "RETRY_PARSE", "RETRY_L3"}),
    "reconcile": frozenset({"RETRY_EXECUTE", "RETRY_L3"}),
    "deliver": frozenset({"RETRY_VALIDATE"}),
}

# Stage -> next stage after a HUMAN approve (forward chain).
_STAGE_FORWARD_TARGET = {
    "l1": "l2_worker",
    "l2": "l3_worker",
    # Layer-3 review is the hand-off into the explicit post-L3 chain.
    "l3": "parse",
    "parse": "ground",
    "ground": "select",
    "select": "execute",
    "validate": "reconcile",
    "reconcile": "deliver",
    "deliver": "__end__",
}

# Gate state channel names (there is no execute_gate).
_GATE_CHANNELS = (
    "parse_gate", "ground_gate", "select_gate",
    "validate_gate", "reconcile_gate", "deliver_gate",
)


def _pass_gate(stage: str) -> GateDecision:
    """Construct a force-pass GateDecision for a stage (approve path)."""
    return GateDecision(
        stage=stage, passed=True, feedback_route=None,
        pending_requests=[], evidence_requests=[],
    )


def _gate_route(gate: Any) -> str:
    """Extract feedback_route from a gate (typed or dict), defaulting to PASS."""
    if gate is None:
        return "PASS"
    route = getattr(gate, "feedback_route", None)
    if route is None and isinstance(gate, dict):
        route = gate.get("feedback_route")
    return route or "PASS"


def _evaluate_progress_gate(
    evaluator: Any,
    report: Any,
    *,
    input_artifact_refs: Dict[str, Any],
    previous_gate: Any,
) -> Any:
    """Pass audit metadata when supported by the evaluator/test double."""
    import inspect

    parameters = inspect.signature(evaluator).parameters.values()
    supports_metadata = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        or parameter.name == "input_artifact_refs"
        for parameter in parameters
    )
    if not supports_metadata:
        return evaluator(report)
    return evaluator(
        report,
        input_artifact_refs=input_artifact_refs,
        previous_gate=previous_gate,
    )


def _gate_failure_context(gate: Any) -> str:
    """Human-readable failure reason from a gate decision."""
    if gate is None:
        return ""
    if isinstance(gate, dict):
        pending = gate.get("pending_requests") or []
        evidence = gate.get("evidence_requests") or []
        route = gate.get("feedback_route")
    else:
        pending = getattr(gate, "pending_requests", None) or []
        evidence = getattr(gate, "evidence_requests", None) or []
        route = getattr(gate, "feedback_route", None)

    for pr in pending:
        ctx = pr.get("context") if isinstance(pr, dict) else getattr(pr, "context", None)
        if isinstance(ctx, dict):
            for key in ("message", "detail"):
                val = ctx.get(key)
                if val:
                    return str(val)
        req_type = pr.get("request_type") if isinstance(pr, dict) else getattr(pr, "request_type", None)
        if req_type:
            return str(req_type)
    if evidence:
        return str(evidence[0])
    if route:
        return f"route={route}"
    return ""


def _retry_patch(state: Dict[str, Any], stage: str) -> Dict[str, Any]:
    """Compose retry side-effects (counts bump + error_feedback) for a stage."""
    gate = state.get(f"{stage}_gate")
    if gate is None:
        return {}
    if _gate_route(gate) not in _RETRY_ROUTES.get(stage, frozenset()):
        return {}
    counts = dict(state.get("retry_counts") or {})
    feedback = dict(state.get("error_feedback") or {})
    return {
        "retry_counts": {
            **counts,
            stage: counts.get(stage, 0) + 1,
        },
        "error_feedback": {
            **feedback,
            stage: _gate_failure_context(gate),
        },
    }


def _accumulate_gate(gates: List[Any], gate: Any) -> List[Any]:
    return list(gates or []) + ([gate] if gate is not None else [])


def _run_id(state: Dict[str, Any]) -> str:
    return state.get("run_id") or state.get("session_id", "")


def _context_version(state: Dict[str, Any]) -> str:
    return state.get("context_version", "")


def _adopt_context(state: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Make the loaded context reference explicit in the next state patch."""
    version = str(getattr(context, "version", "") or "")
    state["context_version"] = version
    state["context_ref"] = {"session_id": state.get("session_id", ""), "version": version}
    if not state.get("context_fingerprint"):
        import hashlib

        meta = context.snapshot_meta()
        state["context_fingerprint"] = "sha256:" + hashlib.sha256(
            repr(sorted(meta.items())).encode("utf-8")
        ).hexdigest()[:16]
    return {
        "context_version": state["context_version"],
        "context_ref": state["context_ref"],
        "context_fingerprint": state.get("context_fingerprint", ""),
    }


def _get_cached_context(state: Dict[str, Any]) -> Any:
    session_id = state.get("session_id", "")
    if not session_id:
        return None
    try:
        from app.services.context.planning_context import get_cached_context
        return get_cached_context(session_id)
    except Exception:
        return None


async def _require_context(state: Dict[str, Any]) -> Any:
    """Load the checkpoint's PlanningContext, rebuilding after process restart.

    ``bootstrap_context_done`` is only a checkpoint marker; the actual context
    lives in an in-process cache and can disappear when a worker restarts.
    Rebuilding through the canonical factory is idempotent and preserves the
    single versioned context contract.  A version mismatch is fail-closed.
    """
    context = _get_cached_context(state)
    if context is None:
        # Reuse the bootstrap node so recovery also hydrates L1 location facts
        # from the canonical artifact_refs map before spatial grounding.
        from app.agent.bootstrap.context_bootstrap import bootstrap_context_node
        await bootstrap_context_node(state)
        context = _get_cached_context(state)
    if context is None:
        raise RuntimeError("PLANNING_CONTEXT_UNAVAILABLE: bootstrap returned no context")
    # The context object is cached across the L1/L2/L3 waves.  Enrichment can
    # finish after bootstrap, so a cached context must still hydrate the
    # authoritative L1 location-fact artifact before GROUND.  Without this
    # call the resolver saw the same context version but an empty
    # ``location_facts`` list, making the L1 -> KG -> GROUND evidence path
    # disappear after a normal layer completion.
    try:
        from app.agent.bootstrap.context_bootstrap import _hydrate_l1_spatial_facts

        _hydrate_l1_spatial_facts(state, context)
    except Exception as exc:
        logger.warning("[post_l3:main] cached context L1 hydration failed: %s", exc)
    expected = _context_version(state)
    actual = str(getattr(context, "version", ""))
    if expected and actual and expected != actual:
        raise RuntimeError(
            f"CONTEXT_VERSION_MISMATCH: checkpoint={expected} loaded={actual}"
        )
    _adopt_context(state, context)
    return context


def _to_typed(data: Any, cls: type) -> Any:
    """Reconstruct a typed Pydantic object from a dict (for aggregate consumption)."""
    if data is None:
        return None
    if isinstance(data, cls):
        return data
    if isinstance(data, dict):
        try:
            return cls(**data)
        except Exception:
            return data
    return data


def _dump(obj: Any) -> Any:
    """Serialize typed Pydantic objects to JSON-safe dicts for checkpoint."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:
            return obj
    return obj


def _dump_list(items: list) -> list:
    """Serialize a list of typed objects (or pass through dicts)."""
    return [_dump(i) for i in (items or [])]


def _jsonable(obj: Any) -> Any:
    """Recursively convert to msgpack/JSON-safe primitives.

    Handles pydantic models, SimpleNamespace, dataclasses, numpy scalars/arrays
    and nested containers so checkpoint serialization never hits an unserializable
    type (e.g. ``types.SimpleNamespace``) inside GeoJSON/layout payloads.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
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


def _persist_artifact(
    state: Dict[str, Any], module: str, artifact_type: str, payload: Any,
) -> Dict[str, Any]:
    """Store a typed artifact and update the canonical ref-only map."""
    try:
        from app.agent.bootstrap.artifact_runtime import store_artifact
        key_by_type = {
            "GroundingResult": "grounding_result",
            "SiteSelectionDecision": "site_selection",
            "ParcelChangeSet": "parcel_changeset",
            "PlannedState": "planned_state",
            "ValidationReport": "validation_report",
            "ReconciliationReport": "reconciliation_report",
            "DeliveryManifest": "delivery_manifest",
            "PlanningProgram": "planning_program",
            "IntentCompilationResult": "intent_compilation",
            "ExecutionPlan": "execution_plan",
            "ExecutionOutcome": "execution_outcome",
            "AllocatedGeoJSON": "allocated_geojson",
            "RenderLayers": "render_layers",
            "DeliverySpatialSnapshot": "delivery_spatial_snapshot",
            "DeferralLedger": "deferral_ledger",
        }
        key = key_by_type.get(artifact_type, artifact_type.lower())
        return store_artifact(state, key, module, artifact_type, payload)
    except Exception as exc:
        from app.agent.bootstrap.artifact_runtime import ArtifactReplayError
        if isinstance(exc, ArtifactReplayError):
            raise
        logger.warning("[post_l3:main] artifact persist failed (%s): %s", artifact_type, exc)
        return {}


def _load_planning_program(state: Dict[str, Any]) -> Any:
    from app.modules.schema.contracts.l3_contracts import PlanningProgram
    program = _load_ref_artifact(state, "planning_program", PlanningProgram)
    return program


def _load_ref_artifact(state: Dict[str, Any], key: str, cls: type) -> Any:
    """Load a typed artifact from the canonical refs in stamped state."""
    try:
        from app.agent.bootstrap.artifact_runtime import ArtifactReplayError, load_artifact
        value = load_artifact(state, key, cls)
        return value
    except ArtifactReplayError:
        raise
    except Exception as exc:
        logger.warning("[post_l3:main] ref load failed for %s: %s", key, exc)
        return None


def _spatial_spec_village_names(spec: Any) -> List[str]:
    """Collect village labels from a possibly composed spatial spec."""
    names: List[str] = []
    children = getattr(spec, "children", None) or []
    for child in children:
        names.extend(_spatial_spec_village_names(child))
    reference = getattr(spec, "reference", None)
    filt = getattr(reference, "filter", None) if reference is not None else None
    label = str((filt or {}).get("label_contains") or "").strip()
    if label:
        names.append(label)
    return list(dict.fromkeys(names))


def _spec_has_source_support(spec: Any, program: Any, context: Any) -> bool:
    """Require a real BSM-backed gazetteer entry for named village specs."""
    labels = _spatial_spec_village_names(spec)
    if not labels:
        return True
    entries = getattr(getattr(context, "gazetteer", None), "entries", []) or []
    resolved_names = set()
    for entry in entries:
        if getattr(entry, "bsms", None):
            resolved_names.add(str(getattr(entry, "name", "")))
            resolved_names.update(str(alias) for alias in (getattr(entry, "aliases", []) or []))
    for label in labels:
        base = label.removesuffix("自然村").removesuffix("村")
        if label not in resolved_names and base not in resolved_names:
            # A report sentence is provenance, not geometry. Named-village
            # spatial specs require a BSM-backed gazetteer entry; otherwise
            # GROUND must expose the missing evidence instead of fabricating
            # a location or silently dropping the requirement.
            return False
    return True


def _filter_unsupported_spatial_specs(specs: List[Any], program: Any, context: Any) -> tuple[List[Any], List[Dict[str, Any]]]:
    """Preserve specs and annotate missing evidence for the GROUND gate."""
    kept: List[Any] = list(specs)
    diagnostics: List[Dict[str, Any]] = []
    for spec in specs:
        if _spec_has_source_support(spec, program, context):
            continue
        labels = _spatial_spec_village_names(spec)
        diagnostics.append({
            "code": "UNSUPPORTED_SPATIAL_REFERENCE",
            "intervention_id": getattr(spec, "intervention_id", ""),
            "labels": labels,
            "message": "named village has no GIS BSM binding and no object-specific source evidence; GROUND must resolve or route HUMAN",
        })
    return kept, diagnostics


# ── PARSE ──────────────────────────────────────────────────────────────


async def parse_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """PARSE node: compile PlanningProgram -> IntentCompilationResult + specs."""
    from app.agent.parse.aggregate import compile_program_async

    retry_patch = _retry_patch(state, "parse")
    program = _load_planning_program(state)
    if program is None:
        logger.warning("[post_l3:main:parse] no planning_program; empty compile")
    context = await _require_context(state)
    result, specs, gate = await compile_program_async(
        program,
        run_id=_run_id(state),
        context_version=str(getattr(context, "version", "")),
    )
    specs, unsupported = _filter_unsupported_spatial_specs(specs, program, context)
    if unsupported:
        from app.modules.schema.contracts.parse_result_contracts import ParseDiagnostic

        diagnostics = list(getattr(result, "diagnostics", []) or [])
        diagnostics.extend(ParseDiagnostic(**item) for item in unsupported)
        result.diagnostics = diagnostics
        result.spatial_reference_specs = specs
        logger.warning(
            "[post_l3:main:parse] retained %d spatial refs with unsupported-source diagnostics: %s",
            len(unsupported),
            unsupported,
        )
    intent_ref = _persist_artifact(state, "parse", "IntentCompilationResult", result)
    return {
        "specs": _dump_list(specs),
        "parse_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "artifact_refs": {"intent_compilation": intent_ref} if intent_ref else {},
        **_adopt_context(state, context),
        **retry_patch,
    }


# ── GROUND ─────────────────────────────────────────────────────────────


async def ground_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """GROUND node: specs + context -> GroundingResult + gate."""
    from app.agent.ground.aggregate import ground_aggregate
    from app.agent.ground.aggregate import retrieve_evidence
    from app.agent.ground.gate import evaluate_ground_gate
    from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec

    retry_patch = _retry_patch(state, "ground")
    context = await _require_context(state)
    specs = [_to_typed(s, SpatialReferenceSpec) for s in (state.get("specs") or [])]
    evidence = []
    if retry_patch:
        prior_gate = state.get("ground_gate")
        requests = getattr(prior_gate, "evidence_requests", None)
        if requests is None and isinstance(prior_gate, dict):
            requests = prior_gate.get("evidence_requests")
        try:
            evidence = await retrieve_evidence(context, requests or None)
        except Exception as e:
            logger.warning("[post_l3:main:ground] retrieve_evidence failed: %s", e)
    result = ground_aggregate(specs, context)
    if evidence and hasattr(result, "spatial_query_evidence"):
        result.spatial_query_evidence.extend(evidence)
        refs = [ref for e in evidence for ref in e.result_refs if ref]
        if refs:
            for candidate in (getattr(result, "candidates", None) or []):
                if hasattr(candidate, "evidence_refs"):
                    candidate.evidence_refs.extend(refs)
    gate = evaluate_ground_gate(result, expected_spec_count=len(specs))
    ref = _persist_artifact(state, "ground", "GroundingResult", result)
    return {
        "ground_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "artifact_refs": {"grounding_result": ref} if ref else {},
        **_adopt_context(state, context),
        **retry_patch,
    }


# ── SELECT ─────────────────────────────────────────────────────────────


async def select_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """SELECT node: GroundingResult + intent + context -> SiteSelectionDecision."""
    from app.agent.execute.plan_builder import build_execution_plan
    from app.agent.select.aggregate import select_aggregate
    from app.agent.select.gate import evaluate_select_gate
    from app.modules.schema.contracts.grounding_contracts import GroundingResult
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
    from app.modules.schema.contracts.deferral_contracts import DeferralLedger

    retry_patch = _retry_patch(state, "select")
    context = await _require_context(state)
    grounding = _load_ref_artifact(state, "grounding_result", GroundingResult)
    intent = _load_ref_artifact(state, "intent_compilation", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    deferral_ledger = _load_ref_artifact(state, "deferral_ledger", DeferralLedger)
    import asyncio
    from app.core.settings import GIS_TIMEOUT
    try:
        async with asyncio.timeout(max(30, int(GIS_TIMEOUT) * 4)):
            decision, briefs = await asyncio.to_thread(
                select_aggregate, grounding, plan_intent, context
            )
    except TimeoutError as exc:
        logger.error("[post_l3:main:select] aggregate timeout; failing closed")
        raise RuntimeError("SELECT_TIMEOUT: candidate selection exceeded its cancellation boundary") from exc
    intent.typed_intent = plan_intent
    projects = list(getattr(plan_intent, "project_targets", None) or [])
    spatial_projects = [
        project for project in projects if getattr(project, "requires_spatial", True)
    ]
    gate = evaluate_select_gate(
        decision,
        target_count=len(spatial_projects),
        input_artifact_refs=state.get("artifact_refs"),
        previous_gate=state.get("select_gate"),
    )
    execution_plan = build_execution_plan(
        intent,
        decision,
        briefs,
        run_id=_run_id(state),
        context_version=_context_version(state),
        deferral_ledger=deferral_ledger,
    )
    ref = _persist_artifact(state, "select", "SiteSelectionDecision", decision)
    plan_ref = _persist_artifact(state, "select", "ExecutionPlan", execution_plan)
    return {
        "land_design_briefs": _dump_list(briefs),
        "select_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "artifact_refs": {"site_selection": ref, "execution_plan": plan_ref},
        **_adopt_context(state, context),
        **retry_patch,
    }


# ── EXECUTE ────────────────────────────────────────────────────────────


def _execution_outcome_from_result(execution_plan: Any, result: Dict[str, Any]) -> Any:
    """Classify each planned task from the actual worker dispatch and output."""
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionOutcome, ExecutionResult

    from app.agent.execute.nodes.worker_common import worker_result_key, worker_route_key
    action_results = list(result.get("action_results", []) or [])
    action_target_ids = {
        str(getattr(item, "target_id", "") or (item.get("target_id") if isinstance(item, dict) else ""))
        for item in action_results
    }
    errors = list(result.get("execution_errors", []) or [])
    worker_results = list(result.get("worker_results", []) or [])
    routed_tasks = result.get("tasks_to_run")
    task_results = []
    for task in list(getattr(execution_plan, "worker_tasks", None) or []):
        task_id = str(getattr(task, "task_id", ""))
        target_id = str(getattr(task, "target_id", ""))
        output_kind = getattr(task, "expected_output_kind", "parcel")
        task_worker_type = getattr(task, "worker_type", "")
        task_worker_type = str(getattr(task_worker_type, "value", task_worker_type))
        stage = worker_route_key(task_worker_type)
        result_key = worker_result_key(task_worker_type)
        matching_results = [
            worker for worker in worker_results
            if str(getattr(worker, "worker_type", "") if not isinstance(worker, dict) else worker.get("worker_type", "")) == result_key
        ]
        task_records = [
            item
            for worker in matching_results
            for item in (getattr(worker, "task_results", []) if not isinstance(worker, dict) else worker.get("task_results", [])) or []
            if str(getattr(item, "task_id", "") if not isinstance(item, dict) else item.get("task_id", "")) == task_id
        ]
        task_errors = [
            item for item in errors
            if str(item.get("stage", "") if isinstance(item, dict) else "") in {stage, task_worker_type, target_id}
        ]
        diagnostics = [item for item in task_errors if isinstance(item, dict)]
        failed = False
        if isinstance(routed_tasks, list) and stage not in routed_tasks:
            diagnostics.append({"code": "worker_not_dispatched", "stage": stage})
            failed = True
        elif not task_records:
            diagnostics.append({"code": "task_result_missing", "task_id": task_id})
            failed = True
        else:
            task_record = task_records[-1]
            record_status = getattr(task_record, "status", "failed") if not isinstance(task_record, dict) else task_record.get("status", "failed")
            record_diagnostics = getattr(task_record, "diagnostics", []) if not isinstance(task_record, dict) else task_record.get("diagnostics", [])
            diagnostics.extend(item for item in (record_diagnostics or []) if isinstance(item, dict))
            failed = record_status != "succeeded" or bool(task_errors)
            if output_kind == "action" and target_id not in action_target_ids:
                diagnostics.append({"code": "action_result_missing", "target_id": target_id})
                failed = True
        task_results.append(ExecutionResult(
            task_id=task_id,
            target_id=target_id,
            status="failed" if failed else "succeeded",
            expected_output_kind=output_kind,
            output_artifacts=[] if failed else [output_kind],
            errors=[str(item) for item in task_errors] + (
                list(getattr(task_records[-1], "errors", []) if not isinstance(task_records[-1], dict) else task_records[-1].get("errors", []))
                if task_records else []
            ),
            diagnostics=diagnostics,
        ))
    for task in list(getattr(execution_plan, "deferred_tasks", None) or []):
        task_results.append(ExecutionResult(
            task_id=str(getattr(task, "task_id", "")),
            target_id=str(getattr(task, "target_id", "")),
            status="deferred",
            expected_output_kind=getattr(task, "expected_output_kind", "parcel"),
        ))
    return ExecutionOutcome(
        task_results=task_results,
        action_results=action_results,
        diagnostics=list(result.get("worker_conflict_diagnostics", []) or []) + errors,
    )


async def execute_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """EXECUTE node: wrapper that maps AgentState -> ExecuteAgentState, runs the
    EXECUTE subgraph, and maps the result back to AgentState refs.

    Parent and subgraph have different state schemas, so per LangGraph official
    practice the subgraph is invoked inside a node (not mounted via add_node).
    EXECUTE is compiled with its own independent checkpointer and invoked under
    a distinct ``checkpoint_ns`` so its checkpoints are isolated from the
    parent's ``""`` namespace.
    """
    from app.services.runtime import PlanningRuntimeService
    from app.agent.execute.execute_state import ExecuteAgentState
    from app.agent.execute.planned_state_builder import changeset_to_planned_state
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan

    context = await _require_context(state)
    intent = _load_ref_artifact(state, "intent_compilation", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    site_selection = _load_ref_artifact(state, "site_selection", SiteSelectionDecision)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
    if execution_plan is None and intent is not None and site_selection is not None:
        from app.agent.execute.plan_builder import build_execution_plan

        execution_plan = build_execution_plan(
            intent,
            site_selection,
            state.get("land_design_briefs") or [],
            run_id=_run_id(state),
            context_version=_context_version(state),
        )
    bundle = getattr(context, "bundle", None)
    gis_data = bundle.to_geojson_dict() if bundle is not None and hasattr(bundle, "to_geojson_dict") else {}

    plan_briefs = list(getattr(execution_plan, "land_design_briefs", None) or state.get("land_design_briefs") or [])
    exec_state = ExecuteAgentState(
        session_id=state.get("session_id", ""),
        village_name=state.get("config", {}).get("village_name", ""),
        gis_data=gis_data,
        gis_bundle=bundle,
        intent=plan_intent,
        facility_anchors=getattr(context, "village_anchors", None),
        site_selection=site_selection,
        land_design_briefs=plan_briefs,
        execution_plan=execution_plan,
        kg_session_ref=getattr(context, "kg_session_ref", "") or "",
        messages=list(state.get("messages") or []),
    )

    from app.agent.execute.nodes.worker_common import _execution_intent_from_plan

    execution_intent = _execution_intent_from_plan(exec_state)
    graph = PlanningRuntimeService._execute_subgraph
    if graph is None:
        await PlanningRuntimeService.ensure_initialized()
        graph = PlanningRuntimeService._execute_subgraph
    kg_obj = getattr(context, "kg", None)
    if kg_obj is not None and execution_intent is not None:
        try:
            from app.modules.kg.builder.layer3 import build_intent_layer

            build_intent_layer(kg_obj, execution_intent)
        except Exception as e:
            logger.warning("[post_l3:main:execute] build_intent_layer failed: %s", e)
    # EXECUTE contains several GIS workers and must have a structured
    # cancellation boundary.  Without it a native geometry operation can
    # keep the session task alive indefinitely after a bad external feature.
    import asyncio
    from app.core.settings import LLM_REQUEST_TIMEOUT

    try:
        async with asyncio.timeout(max(30, int(LLM_REQUEST_TIMEOUT))):
            result = await graph.ainvoke(
                exec_state,
                config={"configurable": {"thread_id": state.get("session_id", ""), "checkpoint_ns": "execute"}},
            )
    except TimeoutError as exc:
        logger.error("[post_l3:main:execute] subgraph timeout; failing closed")
        raise RuntimeError("EXECUTE_TIMEOUT: GIS worker subgraph exceeded its cancellation boundary") from exc

    changeset = result.get("parcel_changeset")
    if changeset is not None:
        planned_state = changeset_to_planned_state(
            changeset,
            execution_intent,
            list(result.get("layout_configs", []) or []),
        )
    else:
        logger.warning("[post_l3:main:execute] no parcel_changeset produced")
        planned_state = None

    outcome = _execution_outcome_from_result(execution_plan, result)
    l4_write_result: Dict[str, Any] = {}
    if planned_state is not None:
        from app.agent.execute.nodes.write_l4 import _write_l4_node

        exec_state.parcel_changeset = changeset
        exec_state.layout_configs = list(result.get("layout_configs", []) or [])
        exec_state.planned_state = planned_state
        exec_state.execution_outcome = outcome
        exec_state.validation_result = dict(result.get("validation_result") or {})
        try:
            l4_write_result = await _write_l4_node(exec_state) or {}
        except Exception as exc:
            logger.exception("[post_l3:main:execute] L4 write failed")
            l4_write_result = {
                "l4_write_error": "l4_write_failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
    refs = {
        "execution_outcome": _persist_artifact(state, "execute", "ExecutionOutcome", outcome),
        "parcel_changeset": _persist_artifact(state, "execute", "ParcelChangeSet", changeset),
        "planned_state": _persist_artifact(state, "execute", "PlannedState", planned_state),
        "allocated_geojson": _persist_artifact(
            state, "execute", "AllocatedGeoJSON", result.get("allocated_geojson", {}) or {}
        ),
    }
    l4_error = l4_write_result.get("l4_write_error")
    execution_errors = list(result.get("execution_errors", []) or [])
    if l4_error:
        execution_errors.append({"stage": "L4", "code": l4_error, "missing_targets": l4_write_result.get("missing_targets", [])})
    fatal_error = None
    diagnostic_terminal = None
    if l4_error:
        from app.services.artifact_fingerprint import semantic_checksum

        missing_targets = _jsonable(l4_write_result.get("missing_targets", []))
        fatal_error = {
            "stage": "EXECUTE",
            "code": str(l4_error),
            "message": f"L4 write failed: {l4_error}",
            "missing_targets": missing_targets,
        }
        diagnostic_terminal = {
            "stage": "execute",
            "reason": str(l4_error),
            "issue_fingerprint": semantic_checksum(l4_write_result),
            "missing_targets": missing_targets,
        }
    return {
        "layout_configs": _jsonable(list(result.get("layout_configs", []) or [])),
        "action_results": _jsonable(outcome.action_results),
        "execution_errors": _jsonable(execution_errors),
        "l4_write_result": _jsonable(l4_write_result),
        "execution_outcome_target_coverage": _jsonable(l4_write_result.get("execution_outcome_target_ids", [])),
        **({
            "fatal_error": fatal_error,
            "delivery_status": "diagnostic_only",
            "diagnostic_terminal": diagnostic_terminal,
        } if l4_error else {}),
        "artifact_refs": refs,
        **_adopt_context(state, context),
    }


# ── VALIDATE ───────────────────────────────────────────────────────────


async def validate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """VALIDATE node: run validate_aggregate + gate."""
    from app.agent.validate.aggregate import validate_aggregate
    from app.agent.validate.gate import evaluate_validate_gate
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.planned_state_contracts import PlannedState
    from app.modules.schema.contracts.parcel_change_contracts import ParcelChangeSet
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
    from app.modules.schema.contracts.execution_plan_contracts import (
        ExecutionOutcome,
        ExecutionPlan,
    )

    retry_patch = _retry_patch(state, "validate")
    context = await _require_context(state)
    constraint_index = getattr(context, "constraint_index", None)
    planned_state = _load_ref_artifact(state, "planned_state", PlannedState)
    changeset = _load_ref_artifact(state, "parcel_changeset", ParcelChangeSet)
    intent = _load_ref_artifact(state, "intent_compilation", IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    selection = _load_ref_artifact(state, "site_selection", SiteSelectionDecision)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
    execution_outcome = _load_ref_artifact(state, "execution_outcome", ExecutionOutcome)
    report = validate_aggregate(
        planned_state,
        changeset,
        state.get("layout_configs"),
        plan_intent,
        constraint_index,
        run_id=_run_id(state),
        decision=selection,
        execution_plan=execution_plan,
        execution_outcome=execution_outcome,
    )
    input_keys = {
        "intent_compilation", "site_selection", "execution_plan",
        "execution_outcome", "parcel_changeset", "planned_state", "deferral_ledger",
    }
    input_refs = {
        key: value
        for key, value in (state.get("artifact_refs") or {}).items()
        if key in input_keys
    }
    gate = _evaluate_progress_gate(
        evaluate_validate_gate,
        report,
        input_artifact_refs=input_refs,
        previous_gate=state.get("validate_gate"),
    )
    ref = _persist_artifact(state, "validate", "ValidationReport", report)
    return {
        "validate_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "artifact_refs": {"validation_report": ref} if ref else {},
        **_adopt_context(state, context),
        **retry_patch,
    }


# ── RECONCILE ──────────────────────────────────────────────────────────


async def reconcile_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """RECONCILE node: run reconcile_aggregate + gate."""
    from app.agent.reconcile.aggregate import reconcile_aggregate
    from app.agent.reconcile.gate import evaluate_reconcile_gate
    from app.modules.schema.contracts.l3_contracts import PlanningProgram
    from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec
    from app.modules.schema.contracts.grounding_contracts import GroundingResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
    from app.modules.schema.contracts.parcel_change_contracts import ParcelChangeSet
    from app.modules.schema.contracts.planned_state_contracts import PlannedState
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.execution_plan_contracts import (
        ExecutionOutcome,
        ExecutionPlan,
    )

    retry_patch = _retry_patch(state, "reconcile")
    context = await _require_context(state)
    program = _load_planning_program(state)
    if program is None:
        from app.modules.schema.contracts.reconciliation_contracts import (
            ReconciliationInconsistency,
            ReconciliationReport,
        )
        report = ReconciliationReport(
            inconsistencies=[
                ReconciliationInconsistency(
                    intervention_id="__missing_program__",
                    field="planning_program",
                    expected="non-null PlanningProgram",
                    actual="None",
                    severity="error",
                    responsible_stage="L3",
                )
            ],
        )
        gate = _evaluate_progress_gate(
            evaluate_reconcile_gate,
            report,
            input_artifact_refs=state.get("artifact_refs") or {},
            previous_gate=state.get("reconcile_gate"),
        )
        ref = _persist_artifact(state, "reconcile", "ReconciliationReport", report)
        return {
            "reconcile_gate": _dump(gate),
            "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
            "artifact_refs": {"reconciliation_report": ref} if ref else {},
            **_adopt_context(state, context),
            **retry_patch,
        }
    specs = [_to_typed(s, SpatialReferenceSpec) for s in (state.get("specs") or [])]
    grounding = _load_ref_artifact(state, "grounding_result", GroundingResult)
    decision = _load_ref_artifact(state, "site_selection", SiteSelectionDecision)
    changeset = _load_ref_artifact(state, "parcel_changeset", ParcelChangeSet)
    planned_state = _load_ref_artifact(state, "planned_state", PlannedState)
    intent = _load_ref_artifact(state, "intent_compilation", IntentCompilationResult)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
    execution_outcome = _load_ref_artifact(state, "execution_outcome", ExecutionOutcome)
    report = reconcile_aggregate(
        program,
        specs,
        grounding,
        decision,
        changeset,
        planned_state,
        intent,
        execution_plan=execution_plan,
        execution_outcome=execution_outcome,
        run_id=_run_id(state),
    )
    input_keys = {
        "planning_program", "intent_compilation", "grounding_result",
        "site_selection", "execution_plan", "execution_outcome",
        "parcel_changeset", "planned_state", "validation_report", "deferral_ledger",
    }
    input_refs = {
        key: value
        for key, value in (state.get("artifact_refs") or {}).items()
        if key in input_keys
    }
    gate = _evaluate_progress_gate(
        evaluate_reconcile_gate,
        report,
        input_artifact_refs=input_refs,
        previous_gate=state.get("reconcile_gate"),
    )
    ref = _persist_artifact(state, "reconcile", "ReconciliationReport", report)
    return {
        "reconcile_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "artifact_refs": {"reconciliation_report": ref} if ref else {},
        **_adopt_context(state, context),
        **retry_patch,
    }


# ── DELIVER ────────────────────────────────────────────────────────────


async def deliver_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """DELIVER node: export + deliver_aggregate + gate + render layers."""
    from app.agent.deliver.aggregate import deliver_aggregate
    from app.agent.deliver.gate import evaluate_deliver_gate
    from app.modules.spatial_ops.output.export_package import export_gdb_package
    from app.modules.schema.contracts.planned_state_contracts import PlannedState
    from app.modules.schema.contracts.validation_report_contracts import ValidationReport
    from app.modules.schema.contracts.reconciliation_contracts import ReconciliationReport
    from app.modules.schema.contracts.deferral_contracts import DeferralLedger
    from app.modules.schema.contracts.execution_plan_contracts import (
        ExecutionOutcome,
        ExecutionPlan,
    )

    retry_patch = _retry_patch(state, "deliver")
    context = await _require_context(state)
    bundle = getattr(context, "bundle", None)
    gis_data = bundle.to_geojson_dict() if bundle is not None and hasattr(bundle, "to_geojson_dict") else {}
    planned_state = _load_ref_artifact(state, "planned_state", PlannedState)
    validation_report = _load_ref_artifact(state, "validation_report", ValidationReport)
    reconciliation_report = _load_ref_artifact(state, "reconciliation_report", ReconciliationReport)
    execution_plan = _load_ref_artifact(state, "execution_plan", ExecutionPlan)
    execution_outcome = _load_ref_artifact(state, "execution_outcome", ExecutionOutcome)
    deferral_ledger = _load_ref_artifact(state, "deferral_ledger", DeferralLedger)
    allocated_geojson = _load_ref_artifact(state, "allocated_geojson", dict) or {}

    # Keep the delivery invariant explicit: every deferred execution task
    # must have a ledger entry.  Older checkpoints can contain a revised
    # ExecutionPlan whose deferred tasks were created by a later HUMAN
    # decision while the ledger reference still points at the prior revision.
    # Reconcile that metadata at the delivery boundary with an auditable
    # system decision; never silently treat the tasks as delivered.
    if execution_plan is not None:
        from app.modules.schema.contracts.deferral_contracts import (
            HumanDeferralDecision,
            TargetDeferral,
        )

        ledger_entries = list(getattr(deferral_ledger, "entries", None) or [])
        ledger_ids = {str(entry.target_id) for entry in ledger_entries}
        missing_deferred = [
            task for task in (getattr(execution_plan, "deferred_tasks", None) or [])
            if str(getattr(task, "target_id", ""))
            and str(getattr(task, "target_id", "")) not in ledger_ids
        ]
        if missing_deferred:
            decision = HumanDeferralDecision(
                decision_id=str(state.get("human_review_event_id") or "delivery-ledger-reconciliation"),
                decided_by="system:delivery-ledger-reconciliation",
                rationale=(
                    "ExecutionPlan already classified this target as deferred; "
                    "delivery recorded the missing immutable ledger link before export."
                ),
            )
            ledger_entries.extend(
                TargetDeferral(
                    target_id=str(task.target_id),
                    reason="execution_plan_deferred_ledger_reconciliation",
                    source_refs=(
                        f"artifact:execution_plan:{(state.get('artifact_refs') or {}).get('execution_plan', {}).get('artifact_id', 'execution_plan')}",
                    ),
                    decision=decision,
                )
                for task in missing_deferred
            )
            deferral_ledger = DeferralLedger(entries=tuple(ledger_entries))
            ledger_ref = _persist_artifact(state, "deliver", "DeferralLedger", deferral_ledger)
        else:
            ledger_ref = None

    validation_result = {}
    if validation_report is not None:
        validation_result = {"passed": validation_report.overall_passed}

    expected_spatial_output_count = sum(
        1
        for task in (getattr(execution_plan, "worker_tasks", None) or [])
        if str(getattr(task, "expected_output_kind", "")) != "action"
    )
    delivery_snapshot = None
    delivery_snapshot_ref = None
    complete_planned_geojson = None
    delivery_snapshot_error = ""
    if expected_spatial_output_count > 0 and isinstance(gis_data, dict):
        try:
            from app.modules.schema.contracts.parcel_change_contracts import ParcelChangeSet
            from app.modules.spatial_ops.io import (
                build_delivery_spatial_snapshot_from_gis_data,
                load_complete_planned_geojson,
            )
            from app.services.run_paths import session_run_dir

            changeset = _load_ref_artifact(state, "parcel_changeset", ParcelChangeSet)
            planned_changes = list(getattr(changeset, "changes", None) or [])
            delivery_snapshot = build_delivery_spatial_snapshot_from_gis_data(
                gis_data,
                planned_geojson=allocated_geojson,
                planned_changes=planned_changes,
                output_dir=session_run_dir(state.get("session_id", "")) / "spatial_snapshot",
                output_artifact_ref=(
                    f"delivery-spatial-snapshot-{state.get('session_id', '')}"
                ),
                provenance={"stage": "DELIVER"},
            )
            complete_planned_geojson = load_complete_planned_geojson(delivery_snapshot)
            delivery_snapshot_ref = _persist_artifact(
                state,
                "deliver",
                "DeliverySpatialSnapshot",
                delivery_snapshot,
            )
        except Exception as exc:
            delivery_snapshot_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "[post_l3:main:deliver] delivery snapshot failed: %s",
                delivery_snapshot_error,
            )

    planned_geojson_for_delivery = complete_planned_geojson or allocated_geojson
    render_result = []
    try:
        from app.agent.deliver.render_layers import build_delivery_render_layers

        render_result = build_delivery_render_layers(
            planned_state,
            planned_geojson_for_delivery,
            gis_data,
        )
    except Exception as e:
        logger.warning("[post_l3:main:deliver] render_layers failed: %s", e)

    export_result = None
    if planned_state is not None and expected_spatial_output_count > 0:
        try:
            allocated_for_export = planned_geojson_for_delivery
            allocated_features = (
                allocated_for_export.get("features", [])
                if isinstance(allocated_for_export, dict)
                else []
            )
            current_landuse = gis_data.get("landuse_current_geojson") if isinstance(gis_data, dict) else None
            # If every spatial change is deferred, preserve the authoritative
            # current land-use layer as the planned layer. This is an explicit
            # no-change result, not a synthetic planning allocation; all
            # feature properties carry the provenance for downstream review.
            if not allocated_features and isinstance(current_landuse, dict):
                import copy

                allocated_for_export = copy.deepcopy(current_landuse)
                for feature in allocated_for_export.get("features", []) or []:
                    properties = feature.setdefault("properties", {})
                    properties["planning_status"] = "unchanged_preserved"
                    properties["planning_provenance"] = "current_landuse_no_verified_change"
            export_result = export_gdb_package(
                layout_configs=render_result,
                allocated_geojson=allocated_for_export or None,
                gis_data=gis_data,
                village_name=state.get("config", {}).get("village_name", ""),
                session_id=state.get("session_id", ""),
                validation_result=validation_result,
            )
            if delivery_snapshot is not None:
                export_result["planned_landuse_source"] = "delivery_spatial_snapshot"
            elif allocated_for_export is not allocated_geojson:
                export_result["planned_landuse_source"] = "current_landuse_preserved"
        except Exception as e:
            logger.warning("[post_l3:main:deliver] export failed: %s", e)
            export_result = None

    current_parcels = []
    if bundle is not None and hasattr(bundle, "bundle_parcels"):
        current_parcels = list(bundle.bundle_parcels())
    elif bundle is not None and hasattr(bundle, "polygons"):
        current_parcels = list(bundle.polygons.get("landuse_current") or [])

    render_ref = _persist_artifact(state, "deliver", "RenderLayers", render_result)

    # DELIVER owns the operator-facing render side effects.  Keep these
    # session-scoped and deterministic so replay can reuse the same layer
    # artifact while the report still exposes the actual files produced.
    render_artifacts: Dict[str, Any] = {
        "layer_count": len(render_result),
        "feature_counts": {
            str(layer.get("layerType") or layer.get("layer_type") or "layer"): len(
                (layer.get("geojson") or layer.get("data") or {}).get("features") or []
            )
            for layer in render_result
            if isinstance(layer, dict)
        },
    }
    if delivery_snapshot is not None:
        render_artifacts["delivery_snapshot_checksum"] = delivery_snapshot.checksum
    if delivery_snapshot_error:
        render_artifacts["delivery_snapshot_error"] = delivery_snapshot_error
    try:
        from pathlib import Path

        from app.services.run_paths import session_run_dir

        output_dir = session_run_dir(state.get("session_id", "")) / "render"
        from app.tools.gis.html_render import render_interactive_map
        from app.tools.gis.static_render import render_map_preview

        village_name = str((state.get("config") or {}).get("village_name", ""))
        if render_result:
            render_artifacts["static_preview"] = render_map_preview(
                render_result, str(output_dir), village_name
            )
            render_artifacts["interactive_map"] = render_interactive_map(
                render_result, str(output_dir), village_name
            )
        else:
            render_artifacts["mapless"] = True
    except Exception as exc:
        # Preserve the typed RenderLayers artifact and make the missing file
        # an explicit DELIVER diagnostic instead of hiding it in a log.
        render_artifacts["error"] = {
            "code": "RENDER_FILE_FAILED",
            "type": type(exc).__name__,
            "message": str(exc),
        }

    render_error = ""
    if isinstance(render_artifacts.get("error"), dict):
        render_error = str(render_artifacts["error"].get("message") or "")
    manifest = deliver_aggregate(
        planned_state,
        validation_report,
        reconciliation_report,
        list(state.get("upstream_gates") or []),
        export_result,
        current_parcels=current_parcels,
        run_id=_run_id(state),
        execution_plan=execution_plan,
        execution_outcome=execution_outcome,
        deferral_ledger=deferral_ledger,
        expected_spatial_output_count=expected_spatial_output_count,
        render_layer_count=len(render_result),
        render_error=render_error,
    )
    gate = evaluate_deliver_gate(
        manifest,
        input_artifact_refs=state.get("artifact_refs") or {},
        previous_gate=state.get("deliver_gate"),
    )
    manifest_ref = _persist_artifact(state, "deliver", "DeliveryManifest", manifest)

    return {
        "artifact_refs": {
            key: ref for key, ref in {
                "delivery_manifest": manifest_ref,
                "render_layers": render_ref,
                "delivery_spatial_snapshot": delivery_snapshot_ref,
                "deferral_ledger": ledger_ref,
            }.items() if ref
        },
        "deliver_gate": _dump(gate),
        "delivery_status": manifest.delivery_status,
        "deferral_summary": manifest.deferral_summary,
        "diagnostic_terminal": (
            {
                "stage": "deliver",
                "reason": "remaining_non_deferred_delivery_blockers",
                **manifest.diagnostic_summary,
            }
            if manifest.delivery_status == "diagnostic_only"
            else {}
        ),
        "export_result": export_result,
        "render_artifacts": render_artifacts,
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        **_adopt_context(state, context),
        **retry_patch,
    }


# Keep stage audit behavior at the graph boundary so every real session
# records the same input/output contract without duplicating persistence code.
from app.agent.bootstrap.stage_audit import audited_stage

parse_node = audited_stage("PARSE")(parse_node)
ground_node = audited_stage("GROUND")(ground_node)
select_node = audited_stage("SELECT")(select_node)
execute_node = audited_stage("EXECUTE")(execute_node)
validate_node = audited_stage("VALIDATE")(validate_node)
reconcile_node = audited_stage("RECONCILE")(reconcile_node)
deliver_node = audited_stage("DELIVER")(deliver_node)

# ── HUMAN REVIEW ───────────────────────────────────────────────────────


def _collect_human_items(state: Dict[str, Any]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Extract pending_requests from the most recent HUMAN gate decision.

    Returns (stage, items); stage is None when no gate routed HUMAN.
    """
    items: List[Dict[str, Any]] = []
    for gate_attr in _GATE_CHANNELS:
        gate = state.get(gate_attr)
        if gate is None:
            continue
        route = getattr(gate, "feedback_route", None)
        if route is None and isinstance(gate, dict):
            route = gate.get("feedback_route")
        if route != "HUMAN":
            continue
        pending = getattr(gate, "pending_requests", None)
        if pending is None and isinstance(gate, dict):
            pending = gate.get("pending_requests")
        pending = pending or []
        for pr in pending:
            if hasattr(pr, "model_dump"):
                items.append(pr.model_dump())
            elif isinstance(pr, dict):
                items.append(pr)
        return gate_attr.replace("_gate", ""), items
    return None, items


def _retry_exhaustion_items(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Synthetic review items when retries were exhausted without a HUMAN gate."""
    if not state.get("error_feedback"):
        return []
    return [
        {
            "request_id": "post-l3-retry-exhausted",
            "stage": "post_l3",
            "request_type": "retry_exhausted",
            "context": {
                "message": "post-L3 retries exhausted; manual intervention required",
                "detail": dict(state.get("error_feedback") or {}),
                "retry_counts": dict(state.get("retry_counts") or {}),
                "max_retries": state.get("max_retries", 3),
            },
        }
    ]


def _detect_retry_exhaustion_stage(state: Dict[str, Any]) -> Optional[str]:
    counts = state.get("retry_counts") or {}
    max_retries = state.get("max_retries", 3)
    for stage, count in counts.items():
        if count >= max_retries:
            return stage
    return "post_l3"


def collect_human_review_items(state: Dict[str, Any]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Public helper: return (stage, human-review items) for the current state.

    Falls back to synthetic retry-exhaustion items when no gate routed HUMAN.
    """
    stage, items = _collect_human_items(state)
    if stage is not None:
        return stage, items
    exhaustion_stage = _detect_retry_exhaustion_stage(state)
    return exhaustion_stage, _retry_exhaustion_items(state)


__all__ = [
    "parse_node", "ground_node", "select_node", "execute_node",
    "validate_node", "reconcile_node", "deliver_node",
    "collect_human_review_items",
    "_gate_route", "_retry_patch", "_pass_gate",
    "_STAGE_FORWARD_TARGET", "_GATE_CHANNELS",
]
