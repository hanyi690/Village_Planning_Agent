"""Post-L3 chain node functions.

Wave M1: each node wraps a Wave B-L subgraph aggregate and the corresponding
gate evaluator, reading inputs from PostL3ChainState and writing typed
artifacts back. Deterministic (the aggregates are deterministic); no LLM in
this module.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.agent.ground.aggregate import ground_aggregate, retrieve_evidence
from app.agent.ground.gate import evaluate_ground_gate
from app.agent.parse.aggregate import compile_program_async
from app.agent.parse.gate_node import evaluate_parse_gate
from app.agent.select_graph.aggregate import select_aggregate
from app.agent.select_graph.gate import evaluate_select_gate
from app.agent.zoning.aggregate import zoning_node
from app.modules.schema.contracts.grounding_contracts import SpatialQueryEvidence
from app.utils.logger import get_logger

from .post_l3_state import PostL3ChainState

logger = get_logger(__name__)

# Stage -> routes that indicate a retryable outcome (the node owns the counter).
_RETRY_ROUTES: dict[str, frozenset[str]] = {
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
    """Human-readable failure reason from a gate decision.

    Prefers the first pending_request's context message/detail/request_type,
    then the first evidence_request, then the feedback_route itself.
    """
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


async def _bump_retry(state: PostL3ChainState, stage: str) -> dict[str, Any]:
    """Return a retry_counts patch when the stage gate indicates a retry.

    The node owns the counter: this only fires when the previous run left a
    retryable gate decision in state, so the first run (no gate) never bumps
    and each retry bumps exactly once.
    """
    gate = getattr(state, f"{stage}_gate", None)
    if gate is None:
        return {}
    if _gate_route(gate) not in _RETRY_ROUTES.get(stage, frozenset()):
        return {}
    return {
        "retry_counts": {
            **dict(state.retry_counts or {}),
            stage: (state.retry_counts or {}).get(stage, 0) + 1,
        }
    }


def _retry_patch(state: PostL3ChainState, stage: str) -> dict[str, Any]:
    """Compose retry side-effects (counts bump + error_feedback) for a stage.

    Returns ``{}`` when the stage gate is not a retryable outcome, so callers
    can merge it into the node patch unconditionally.
    """
    gate = getattr(state, f"{stage}_gate", None)
    if gate is None:
        return {}
    if _gate_route(gate) not in _RETRY_ROUTES.get(stage, frozenset()):
        return {}
    return {
        "retry_counts": {
            **dict(state.retry_counts or {}),
            stage: (state.retry_counts or {}).get(stage, 0) + 1,
        },
        "error_feedback": {
            **dict(state.error_feedback or {}),
            stage: _gate_failure_context(gate),
        },
    }


def _accumulate_gate(gates: list[Any], gate: Any) -> list[Any]:
    return list(gates or []) + ([gate] if gate is not None else [])


def _resolve_context(state: PostL3ChainState) -> Any:
    """Return the live PlanningContext for a chain run.

    When the chain is compiled with a checkpointer, gis_agent_node strips
    ``context`` from the serialized state (PlanningContext holds non-serializable
    KG closures/adapters). The real context is kept in the session context cache
    (``build_planning_context``), so nodes fall back to it here. Direct node
    invocation (tests / no checkpointer) still passes ``state.context`` directly.
    """
    context = getattr(state, "context", None)
    if context is not None:
        return context
    if getattr(state, "session_id", ""):
        try:
            from app.services.context.planning_context import get_cached_context

            return get_cached_context(state.session_id)
        except Exception:
            return None
    return None


async def parse_node(state: PostL3ChainState) -> dict[str, Any]:
    """PARSE node: compile PlanningProgram -> IntentCompilationResult + specs."""
    retry_patch = _retry_patch(state, "parse")
    program = state.planning_program
    if program is None:
        logger.warning("[post_l3:parse] no planning_program in state; empty compile")
    run_id = state.run_id or state.session_id
    result, specs, gate = await compile_program_async(
        program,
        run_id=run_id,
        context_version=state.context_version,
    )
    return {
        "intent": result,
        "specs": specs,
        "parse_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
        **retry_patch,
    }


async def ground_node(state: PostL3ChainState) -> dict[str, Any]:
    """GROUND node: specs + context -> GroundingResult + gate.

    On an EXPLORE retry the previous ground_gate is present in state, so
    retrieve_evidence runs BEFORE re-running ground_aggregate and the new
    evidence is merged into the produced GroundingResult; the node also bumps
    retry_counts["ground"] and records error_feedback["ground"].
    """
    retry_patch = _retry_patch(state, "ground")
    context = _resolve_context(state)
    evidence: list[SpatialQueryEvidence] = []
    if retry_patch:
        gate = getattr(state, "ground_gate", None)
        requests = getattr(gate, "evidence_requests", None) or []
        evidence = await retrieve_evidence(context, requests or None)
    result = ground_aggregate(list(state.specs or []), context)
    if evidence and hasattr(result, "spatial_query_evidence"):
        result.spatial_query_evidence.extend(evidence)
        refs = [ref for e in evidence for ref in e.result_refs if ref]
        if refs:
            for candidate in (getattr(result, "candidates", None) or []):
                if hasattr(candidate, "evidence_refs"):
                    candidate.evidence_refs.extend(refs)
    gate = evaluate_ground_gate(result)
    return {
        "grounding_result": result,
        "ground_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
        **retry_patch,
    }


async def select_node(state: PostL3ChainState) -> dict[str, Any]:
    """SELECT node: GroundingResult + intent + context -> SiteSelectionDecision."""
    retry_patch = _retry_patch(state, "select")
    context = _resolve_context(state)
    decision, briefs = select_aggregate(
        state.grounding_result, state.intent, context
    )
    projects = list(getattr(state.intent, "project_targets", None) or [])
    gate = evaluate_select_gate(decision, target_count=len(projects))
    return {
        "site_selection": decision,
        "land_design_briefs": briefs,
        "select_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
        **retry_patch,
    }


async def execute_node(state: PostL3ChainState) -> dict[str, Any]:
    """EXECUTE node: run the EXECUTE subgraph -> planned state + changeset."""
    from app.agent.execute.execute_agent import build_execute_agent_graph
    from app.agent.execute.execute_state import ExecuteAgentState
    from app.agent.execute.planned_state_builder import changeset_to_planned_state

    context = _resolve_context(state)
    intent = state.intent
    bundle = getattr(context, "bundle", None)
    gis_data = bundle.to_geojson_dict() if bundle is not None and hasattr(bundle, "to_geojson_dict") else {}

    exec_state = ExecuteAgentState(
        session_id=state.session_id,
        village_name=state.village_name,
        gis_data=gis_data,
        gis_bundle=bundle,
        intent=intent,
        facility_anchors=getattr(context, "village_anchors", None),
        site_selection=state.site_selection,
        land_design_briefs=list(state.land_design_briefs or []),
        kg_session_ref=getattr(context, "kg_session_ref", "") or "",
        messages=list(state.messages),
    )

    graph = build_execute_agent_graph()
    exec_dict = exec_state.model_dump()
    exec_dict["gis_bundle"] = bundle
    exec_dict["intent"] = intent
    exec_dict["site_selection"] = state.site_selection
    result = await graph.ainvoke(exec_dict)

    changeset = result.get("parcel_changeset")
    if changeset is not None:
        planned_state = changeset_to_planned_state(changeset, intent)
    else:
        logger.warning("[post_l3:execute] no parcel_changeset produced")
        planned_state = None

    return {
        "planned_state": planned_state,
        "parcel_changeset": changeset,
        "layout_configs": list(result.get("layout_configs", []) or []),
        "allocated_geojson": result.get("allocated_geojson", {}) or {},
        "execution_errors": list(result.get("execution_errors", []) or []),
    }


async def validate_node(state: PostL3ChainState) -> dict[str, Any]:
    """VALIDATE node: run validate_aggregate + gate."""
    from app.agent.validate.aggregate import validate_aggregate
    from app.agent.validate.gate import evaluate_validate_gate

    retry_patch = _retry_patch(state, "validate")
    context = _resolve_context(state)
    constraint_index = getattr(context, "constraint_index", None)
    report = validate_aggregate(
        state.planned_state,
        state.parcel_changeset,
        state.layout_configs,
        state.intent,
        constraint_index,
        run_id=state.run_id or state.session_id,
    )
    gate = evaluate_validate_gate(report)
    return {
        "validation_report": report,
        "validate_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
        **retry_patch,
    }


async def reconcile_node(state: PostL3ChainState) -> dict[str, Any]:
    """RECONCILE node: run reconcile_aggregate + gate."""
    from app.agent.reconcile.aggregate import reconcile_aggregate
    from app.agent.reconcile.gate import evaluate_reconcile_gate

    retry_patch = _retry_patch(state, "reconcile")
    report = reconcile_aggregate(
        state.planning_program,
        list(state.specs or []),
        state.grounding_result,
        state.site_selection,
        state.parcel_changeset,
        state.planned_state,
        state.intent,
        run_id=state.run_id or state.session_id,
    )
    gate = evaluate_reconcile_gate(report)
    return {
        "reconciliation_report": report,
        "reconcile_gate": gate,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
        **retry_patch,
    }


async def deliver_node(state: PostL3ChainState) -> dict[str, Any]:
    """DELIVER node: export + deliver_aggregate + gate."""
    from app.agent.deliver.aggregate import deliver_aggregate
    from app.agent.deliver.gate import evaluate_deliver_gate
    from app.modules.spatial_ops.export_package import export_gdb_package

    retry_patch = _retry_patch(state, "deliver")
    context = _resolve_context(state)
    bundle = getattr(context, "bundle", None)
    gis_data = bundle.to_geojson_dict() if bundle is not None and hasattr(bundle, "to_geojson_dict") else {}

    validation_result = {}
    if state.validation_report is not None:
        validation_result = {
            "passed": state.validation_report.overall_passed,
        }

    export_result = None
    if state.planned_state is not None and state.layout_configs:
        try:
            export_result = export_gdb_package(
                layout_configs=state.layout_configs,
                allocated_geojson=state.allocated_geojson or None,
                gis_data=gis_data,
                village_name=state.village_name,
                session_id=state.session_id,
                validation_result=validation_result,
            )
        except Exception as e:
            logger.warning("[post_l3:deliver] export failed: %s", e)
            export_result = None

    current_parcels = []
    if bundle is not None and hasattr(bundle, "bundle_parcels"):
        current_parcels = list(bundle.bundle_parcels())
    elif bundle is not None and hasattr(bundle, "polygons"):
        current_parcels = list(bundle.polygons.get("landuse_current") or [])

    manifest = deliver_aggregate(
        state.planned_state,
        state.validation_report,
        state.reconciliation_report,
        list(state.upstream_gates or []),
        export_result,
        current_parcels=current_parcels,
        run_id=state.run_id or state.session_id,
    )
    gate = evaluate_deliver_gate(manifest)
    return {
        "delivery_manifest": manifest,
        "deliver_gate": gate,
        "export_result": export_result,
        "upstream_gates": _accumulate_gate(state.upstream_gates, gate),
        **retry_patch,
    }


def _collect_human_items(state: PostL3ChainState) -> list[dict[str, Any]]:
    """Extract pending_requests from the most recent HUMAN gate decision.

    Reads each gate in chain order, takes the first gate whose
    feedback_route == HUMAN, and dumps its pending_requests to dicts
    (JSON-serializable for the interrupt payload / checkpoint).
    """
    items: list[dict[str, Any]] = []

    for gate_attr in (
        "parse_gate", "ground_gate", "select_gate",
        "validate_gate", "reconcile_gate", "deliver_gate",
    ):
        gate = getattr(state, gate_attr, None)
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


def _retry_exhaustion_items(state: PostL3ChainState) -> list[dict[str, Any]]:
    """Synthetic review items when retries were exhausted without a HUMAN gate.

    Raised by the retry routers (human_end / RETRY_L3); surfaces the
    accumulated error_feedback so an operator sees why retries ended.
    """
    if not state.error_feedback:
        return []
    return [
        {
            "request_id": "post-l3-retry-exhausted",
            "stage": "post_l3",
            "request_type": "retry_exhausted",
            "context": {
                "message": "post-L3 retries exhausted; manual intervention required",
                "detail": dict(state.error_feedback or {}),
                "retry_counts": dict(state.retry_counts or {}),
                "max_retries": state.max_retries,
            },
        }
    ]


async def human_review_node(state: PostL3ChainState) -> dict[str, Any]:
    """Collect human-review items; if any, pause for real human review.

    Wave N P5 (HITL): on first execution the node collects the items and
    calls interrupt() to pause the graph with a checkpointer. On resume the
    second interrupt() call returns the external review decisions, which are
    written back to human_review_decisions so the chain can proceed to END.

    Retry-exhaustion flows (human_end / RETRY_L3) surface as a synthetic
    review item carrying the accumulated error_feedback.
    """
    items = _collect_human_items(state)
    if not items:
        items = _retry_exhaustion_items(state)

    if not items:
        logger.info("[post_l3:human_review] no items; chain continues to END")
        return {"human_review_items": []}

    logger.info("[post_l3:human_review] collected %d items; INTERRUPT awaiting review", len(items))
    decisions = interrupt(
        {
            "human_review_items": items,
            "error_feedback": dict(state.error_feedback or {}),
            "reason": "post_l3_human_review",
        }
    )
    logger.info("[post_l3:human_review] RESUME decisions received: %s", decisions)
    return {
        "human_review_items": items,
        "human_review_decisions": decisions,
    }


__all__ = [
    "parse_node",
    "ground_node",
    "select_node",
    "execute_node",
    "validate_node",
    "reconcile_node",
    "deliver_node",
    "human_review_node",
    "zoning_node",
    "retrieve_evidence",
    "_gate_route",
    "_gate_failure_context",
    "_bump_retry",
    "_retry_patch",
]
