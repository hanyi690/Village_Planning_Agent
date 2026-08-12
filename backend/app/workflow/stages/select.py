"""SELECT stage service: solve the spatial portfolio and execution plan."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from app.core.settings import GIS_TIMEOUT
from app.domain.allocation import build_portfolio_decision
from app.domain.demand import derive_demand_portfolio
from app.domain.suitability import build_suitability_surface
from app.infrastructure.logging import get_logger
from app.workflow.stage_adapter import persist_stage_artifact
from app.workflow.stages.support import (
    _adopt_context,
    _context_version,
    _load_ref_artifact,
    _require_context,
    _retry_patch,
    _run_id,
    stage_completion_patch,
)

logger = get_logger(__name__)


def _to_typed(data: Any, cls: type) -> Any:
    if data is None or isinstance(data, cls):
        return data
    if isinstance(data, dict):
        try:
            return cls(**data)
        except Exception:
            return data
    return data


async def select_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """SELECT node: GroundingResult + intent + context -> SiteSelectionDecision."""
    from app.domain.materialization.plan_builder import build_execution_plan
    from app.domain.allocation.select_service import select_aggregate
    from app.domain.allocation.select_gate import evaluate_select_gate
    from app.contracts.artifacts.deferral_contracts import DeferralLedger
    from app.contracts.spatial.grounding_contracts import GroundingResult
    from app.contracts.workflow.parse_contracts import SpatialPlanningIntent
    from app.contracts.workflow.parse_result_contracts import IntentCompilationResult

    retry_patch = _retry_patch(state, "select")
    context = await _require_context(state)
    grounding = _load_ref_artifact(state, "grounding_result", GroundingResult)
    intent = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
    plan_intent = _to_typed(
        getattr(intent, "typed_intent", None) or intent,
        SpatialPlanningIntent,
    )
    deferral_ledger = _load_ref_artifact(state, "deferral_ledger", DeferralLedger)
    try:
        async with asyncio.timeout(max(30, int(GIS_TIMEOUT) * 4)):
            decision, briefs = await asyncio.to_thread(
                select_aggregate, grounding, plan_intent, context
            )
    except TimeoutError as exc:
        logger.error("[workflow:select] aggregate timeout; failing closed")
        raise RuntimeError(
            "SELECT_TIMEOUT: candidate selection exceeded its cancellation boundary"
        ) from exc
    intent.typed_intent = plan_intent
    demand_portfolio = derive_demand_portfolio(
        plan_intent,
        claims=list(getattr(intent, "claims", None) or []),
    )
    suitability_surface = build_suitability_surface(grounding)
    portfolio_decision = build_portfolio_decision(
        demand_portfolio,
        suitability_surface,
        decision,
    )
    artifact_refs = dict(state.get("artifact_refs") or {})
    output_refs: Dict[str, Any] = {}
    artifact_state = dict(state)
    artifact_state["artifact_refs"] = artifact_refs
    demand_ref = persist_stage_artifact(
        artifact_state, "select", "DemandPortfolio", demand_portfolio
    )
    if demand_ref:
        artifact_refs["demand_portfolio"] = demand_ref
        output_refs["demand_portfolio"] = demand_ref
    suitability_ref = persist_stage_artifact(
        artifact_state, "select", "SuitabilitySurface", suitability_surface
    )
    if suitability_ref:
        artifact_refs["suitability_surface"] = suitability_ref
        output_refs["suitability_surface"] = suitability_ref
    portfolio_ref = persist_stage_artifact(
        artifact_state, "select", "PortfolioDecision", portfolio_decision
    )
    if portfolio_ref:
        artifact_refs["portfolio_decision"] = portfolio_ref
        output_refs["portfolio_decision"] = portfolio_ref
    spatial_projects = [
        project
        for project in (getattr(plan_intent, "project_targets", None) or [])
        if getattr(project, "requires_spatial", True)
    ]
    gate = evaluate_select_gate(
        decision,
        target_count=len(spatial_projects),
        input_artifact_refs=artifact_refs,
        previous_gate=state.get("select_gate"),
        portfolio_decision=portfolio_decision,
    )
    execution_plan = build_execution_plan(
        intent,
        decision,
        briefs,
        run_id=_run_id(state),
        context_version=_context_version(state),
        deferral_ledger=deferral_ledger,
        portfolio_decision_ref=str((portfolio_ref or {}).get("digest") or ""),
    )
    ref = persist_stage_artifact(
        artifact_state, "select", "SiteSelectionDecision", decision
    )
    if ref:
        artifact_refs["site_selection"] = ref
        output_refs["site_selection"] = ref
    plan_ref = persist_stage_artifact(
        artifact_state, "select", "ExecutionPlan", execution_plan
    )
    if plan_ref:
        output_refs["execution_plan"] = plan_ref
    return stage_completion_patch(
        state,
        "select",
        output_refs=output_refs,
        gate=gate,
        context_patch=_adopt_context(state, context),
        retry_patch=retry_patch,
    )


__all__ = ["select_node"]
