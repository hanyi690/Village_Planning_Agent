"""Main-graph post-L3 node functions (Wave M).

Each function is a LangGraph node operating on the main ``AgentState`` dict
(single state source). It reads the typed inputs produced by the previous
stage, calls the underlying deterministic aggregate (PARSE/GROUND/SELECT/
EXECUTE/VALIDATE/RECONCILE/DELIVER), evaluates the stage gate and writes the
typed artifacts + gate back into the shared AgentState.

The standalone ``post_l3_chain`` subgraph (``app.agent.bootstrap.post_l3_chain``)
is kept for isolated chain tests; the main graph uses these nodes directly so
the L3 gate PASS flows into PARSE without a ``gis_agent`` black-box node.
"""

from __future__ import annotations

from typing import Any, Dict, List

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


def _gate_route(gate: Any) -> str:
    """Extract feedback_route from a gate (typed or dict), defaulting to PASS."""
    if gate is None:
        return "PASS"
    route = getattr(gate, "feedback_route", None)
    if route is None and isinstance(gate, dict):
        route = gate.get("feedback_route")
    return route or "PASS"


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


async def _resolve_context(state: Dict[str, Any]) -> Any:
    """Return the live PlanningContext for the session (cache-backed)."""
    session_id = state.get("session_id", "")
    if not session_id:
        return None
    try:
        from app.services.context.planning_context import build_planning_context

        return await build_planning_context(session_id, refresh=False)
    except Exception as e:
        logger.warning("[post_l3:main] context resolve failed: %s", e)
        return None


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
    """Store a typed artifact to FilesystemArtifactStore; return ArtifactRef dict."""
    try:
        from app.modules.ports.artifact_store import ArtifactRef
        from app.services.artifact_store import FilesystemArtifactStore

        run_id = _run_id(state)
        ref = ArtifactRef(
            context_version=_context_version(state),
            artifact_id=f"{module}-{run_id}-v1",
            module=module, run_id=run_id,
            artifact_type=artifact_type, revision="v1",
        )
        payload_json = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
        FilesystemArtifactStore().store(ref, payload_json)
        return ref.model_dump(mode="json")
    except Exception:
        return {}


def _load_planning_program(state: Dict[str, Any]) -> Any:
    """Resolve PlanningProgram from state or artifact store (or None)."""
    from app.modules.schema.contracts.l3_contracts import PlanningProgram

    program = _to_typed(state.get("planning_program"), PlanningProgram)
    if program is not None:
        return program
    ref_data = state.get("l3_program_ref")
    if isinstance(ref_data, dict) and ref_data.get("artifact_id"):
        try:
            from app.modules.ports.artifact_store import ArtifactRef
            from app.modules.schema.contracts.l3_contracts import PlanningProgram
            from app.services.artifact_store import FilesystemArtifactStore

            ref = ArtifactRef(**ref_data)
            payload = FilesystemArtifactStore().retrieve(ref)
            return PlanningProgram(**payload)
        except Exception as e:
            logger.warning("[post_l3:main] planning_program load failed: %s", e)
    return None


# ── PARSE ──────────────────────────────────────────────────────────────


async def parse_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """PARSE node: compile PlanningProgram -> IntentCompilationResult + specs."""
    from app.agent.parse.aggregate import compile_program_async

    retry_patch = _retry_patch(state, "parse")
    program = _load_planning_program(state)
    if program is None:
        logger.warning("[post_l3:main:parse] no planning_program; empty compile")
    result, specs, gate = await compile_program_async(
        program,
        run_id=_run_id(state),
        context_version=_context_version(state),
    )
    return {
        "intent": _dump(result),
        "specs": _dump_list(specs),
        "parse_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        **retry_patch,
    }


# ── GROUND ─────────────────────────────────────────────────────────────


async def ground_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """GROUND node: specs + context -> GroundingResult + gate."""
    from app.agent.ground.aggregate import ground_aggregate
    from app.agent.ground.gate import evaluate_ground_gate
    from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec

    retry_patch = _retry_patch(state, "ground")
    context = await _resolve_context(state)
    specs = [_to_typed(s, SpatialReferenceSpec) for s in (state.get("specs") or [])]
    result = ground_aggregate(specs, context)
    gate = evaluate_ground_gate(result)
    ref = _persist_artifact(state, "ground", "GroundingResult", result)
    return {
        "grounding_result": _dump(result),
        "ground_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "grounding_result_ref": ref,
        **retry_patch,
    }


# ── SELECT ─────────────────────────────────────────────────────────────


async def select_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """SELECT node: GroundingResult + intent + context -> SiteSelectionDecision."""
    from app.agent.select.aggregate import select_aggregate
    from app.agent.select.gate import evaluate_select_gate
    from app.modules.schema.contracts.grounding_contracts import GroundingResult
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult

    retry_patch = _retry_patch(state, "select")
    context = await _resolve_context(state)
    grounding = _to_typed(state.get("grounding_result"), GroundingResult)
    intent = _to_typed(state.get("intent"), IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    decision, briefs = select_aggregate(grounding, plan_intent, context)
    intent.typed_intent = plan_intent
    projects = list(getattr(plan_intent, "project_targets", None) or [])
    gate = evaluate_select_gate(decision, target_count=len(projects))
    ref = _persist_artifact(state, "select", "SiteSelectionDecision", decision)
    return {
        "site_selection": _dump(decision),
        "land_design_briefs": _dump_list(briefs),
        "intent": _dump(intent),
        "select_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "site_selection_ref": ref,
        **retry_patch,
    }


# ── EXECUTE ────────────────────────────────────────────────────────────


async def execute_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """EXECUTE node: run the EXECUTE subgraph -> planned state + changeset."""
    from app.agent.execute.execute_agent import build_execute_agent_graph
    from app.agent.execute.execute_state import ExecuteAgentState
    from app.agent.execute.planned_state_builder import changeset_to_planned_state
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan

    context = await _resolve_context(state)
    intent = _to_typed(state.get("intent"), IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    site_selection = _to_typed(state.get("site_selection"), SiteSelectionDecision)
    execution_plan = _to_typed(state.get("execution_plan"), ExecutionPlan)
    bundle = getattr(context, "bundle", None)
    gis_data = bundle.to_geojson_dict() if bundle is not None and hasattr(bundle, "to_geojson_dict") else {}

    exec_state = ExecuteAgentState(
        session_id=state.get("session_id", ""),
        village_name=state.get("config", {}).get("village_name", ""),
        gis_data=gis_data,
        gis_bundle=bundle,
        intent=plan_intent,
        facility_anchors=getattr(context, "village_anchors", None),
        site_selection=site_selection,
        land_design_briefs=list(state.get("land_design_briefs") or []),
        execution_plan=execution_plan,
        kg_session_ref=getattr(context, "kg_session_ref", "") or "",
        messages=list(state.get("messages") or []),
    )

    graph = build_execute_agent_graph()
    kg_obj = getattr(context, "kg", None)
    if kg_obj is not None and plan_intent is not None:
        try:
            from app.modules.kg.builder.layer3 import build_intent_layer

            build_intent_layer(kg_obj, plan_intent)
        except Exception as e:
            logger.warning("[post_l3:main:execute] build_intent_layer failed: %s", e)
    result = await graph.ainvoke(
        exec_state,
        config={"configurable": {"__pregel_checkpointer": None}},
    )

    changeset = result.get("parcel_changeset")
    if changeset is not None:
        planned_state = changeset_to_planned_state(changeset, plan_intent)
    else:
        logger.warning("[post_l3:main:execute] no parcel_changeset produced")
        planned_state = None

    refs = {
        "parcel_changeset_ref": _persist_artifact(state, "execute", "ParcelChangeSet", changeset),
        "planned_state_ref": _persist_artifact(state, "execute", "PlannedState", planned_state),
    }
    return {
        "planned_state": _jsonable(planned_state),
        "parcel_changeset": _jsonable(changeset),
        "layout_configs": _jsonable(list(result.get("layout_configs", []) or [])),
        "allocated_geojson": _jsonable(result.get("allocated_geojson", {}) or {}),
        "execution_errors": _jsonable(list(result.get("execution_errors", []) or [])),
        **refs,
    }


# ── VALIDATE ───────────────────────────────────────────────────────────


async def validate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """VALIDATE node: run validate_aggregate + gate."""
    from app.agent.validate.aggregate import validate_aggregate
    from app.agent.validate.gate import evaluate_validate_gate
    from app.modules.schema.contracts.planned_state_contracts import PlannedState
    from app.modules.schema.contracts.parcel_change_contracts import ParcelChangeSet
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult

    retry_patch = _retry_patch(state, "validate")
    context = await _resolve_context(state)
    constraint_index = getattr(context, "constraint_index", None)
    planned_state = _to_typed(state.get("planned_state"), PlannedState)
    changeset = _to_typed(state.get("parcel_changeset"), ParcelChangeSet)
    intent = _to_typed(state.get("intent"), IntentCompilationResult)
    report = validate_aggregate(
        planned_state,
        changeset,
        state.get("layout_configs"),
        intent,
        constraint_index,
        run_id=_run_id(state),
    )
    gate = evaluate_validate_gate(report)
    ref = _persist_artifact(state, "validate", "ValidationReport", report)
    return {
        "validation_report": _dump(report),
        "validate_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "validation_report_ref": ref,
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

    retry_patch = _retry_patch(state, "reconcile")
    program = _to_typed(state.get("planning_program"), PlanningProgram)
    specs = [_to_typed(s, SpatialReferenceSpec) for s in (state.get("specs") or [])]
    grounding = _to_typed(state.get("grounding_result"), GroundingResult)
    decision = _to_typed(state.get("site_selection"), SiteSelectionDecision)
    changeset = _to_typed(state.get("parcel_changeset"), ParcelChangeSet)
    planned_state = _to_typed(state.get("planned_state"), PlannedState)
    intent = _to_typed(state.get("intent"), IntentCompilationResult)
    report = reconcile_aggregate(
        program,
        specs,
        grounding,
        decision,
        changeset,
        planned_state,
        intent,
        run_id=_run_id(state),
    )
    gate = evaluate_reconcile_gate(report)
    ref = _persist_artifact(state, "reconcile", "ReconciliationReport", report)
    return {
        "reconciliation_report": _dump(report),
        "reconcile_gate": _dump(gate),
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        "reconciliation_report_ref": ref,
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

    retry_patch = _retry_patch(state, "deliver")
    context = await _resolve_context(state)
    bundle = getattr(context, "bundle", None)
    gis_data = bundle.to_geojson_dict() if bundle is not None and hasattr(bundle, "to_geojson_dict") else {}
    planned_state = _to_typed(state.get("planned_state"), PlannedState)
    validation_report = _to_typed(state.get("validation_report"), ValidationReport)
    reconciliation_report = _to_typed(state.get("reconciliation_report"), ReconciliationReport)

    validation_result = {}
    if validation_report is not None:
        validation_result = {"passed": validation_report.overall_passed}

    export_result = None
    if planned_state is not None and state.get("layout_configs"):
        try:
            export_result = export_gdb_package(
                layout_configs=state.get("layout_configs"),
                allocated_geojson=state.get("allocated_geojson") or None,
                gis_data=gis_data,
                village_name=state.get("config", {}).get("village_name", ""),
                session_id=state.get("session_id", ""),
                validation_result=validation_result,
            )
        except Exception as e:
            logger.warning("[post_l3:main:deliver] export failed: %s", e)
            export_result = None

    current_parcels = []
    if bundle is not None and hasattr(bundle, "bundle_parcels"):
        current_parcels = list(bundle.bundle_parcels())
    elif bundle is not None and hasattr(bundle, "polygons"):
        current_parcels = list(bundle.polygons.get("landuse_current") or [])

    manifest = deliver_aggregate(
        planned_state,
        validation_report,
        reconciliation_report,
        list(state.get("upstream_gates") or []),
        export_result,
        current_parcels=current_parcels,
        run_id=_run_id(state),
    )
    gate = evaluate_deliver_gate(manifest)

    render_result = []
    try:
        from app.agent.deliver.render_layers import build_render_layers

        render_result = build_render_layers(
            planned_state,
            list(state.get("layout_configs") or []),
            gis_data,
        )
    except Exception as e:
        logger.warning("[post_l3:main:deliver] render_layers failed: %s", e)
        render_result = []

    return {
        "delivery_manifest": _dump(manifest),
        "deliver_gate": _dump(gate),
        "export_result": export_result,
        "render_result": render_result,
        "upstream_gates": _accumulate_gate(state.get("upstream_gates"), _dump(gate)),
        **retry_patch,
    }


# ── HUMAN REVIEW ───────────────────────────────────────────────────────


def _collect_human_items(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract pending_requests from the most recent HUMAN gate decision."""
    items: List[Dict[str, Any]] = []
    for gate_attr in (
        "parse_gate", "ground_gate", "select_gate",
        "validate_gate", "reconcile_gate", "deliver_gate",
    ):
        gate = state.get(gate_attr)
        if gate is None:
            continue
        route = getattr(gate, "feedback_route", None)
        if route is None and isinstance(gate, dict):
            route = gate.get("feedback_route")
        if route != "HUMAN":
            continue
        pending = getattr(gate, "pending_requests", None) or []
        for pr in pending:
            if hasattr(pr, "model_dump"):
                items.append(pr.model_dump())
            elif isinstance(pr, dict):
                items.append(pr)
        break  # only process the first HUMAN gate
    return items


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


def collect_human_review_items(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Public helper: return the human-review items for the current state."""
    items = _collect_human_items(state)
    if not items:
        items = _retry_exhaustion_items(state)
    return items


__all__ = [
    "parse_node", "ground_node", "select_node", "execute_node",
    "validate_node", "reconcile_node", "deliver_node",
    "collect_human_review_items",
    "_gate_route", "_retry_patch",
]
