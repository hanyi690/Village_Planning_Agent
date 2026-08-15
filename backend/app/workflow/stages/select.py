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


def _ref_digest(ref: Any) -> str:
    if isinstance(ref, dict):
        return str(ref.get("digest") or ref.get("descriptor_digest") or "")
    return str(getattr(ref, "digest", "") or getattr(ref, "descriptor_digest", "") or "")


def _apply_repair_directives(plan_intent: Any, compilation: Any) -> Any:
    """Apply only closed SELECT directives to an isolated intent revision."""
    if compilation is None or str(getattr(compilation, "status", "")) != "ready":
        return plan_intent
    revised = plan_intent.model_copy(deep=True)
    targets = {
        str(getattr(target, "target_id", "")): target
        for field_name in (
            "project_targets",
            "zone_targets",
            "facilities",
            "development_axes",
            "road_targets",
        )
        for target in list(getattr(revised, field_name, None) or [])
        if str(getattr(target, "target_id", ""))
    }
    for directive in list(getattr(compilation, "directives", None) or []):
        directive_type = str(getattr(directive, "directive_type", ""))
        if directive_type not in {"exclude_bsms", "reallocate"}:
            continue
        target = targets.get(str(getattr(directive, "target_id", "")))
        if target is None:
            continue
        excluded = set(getattr(directive, "exclude_bsms", None) or [])
        excluded.update(getattr(directive, "affected_bsms", None) or [])
        if hasattr(target, "excluded_bsms"):
            target.excluded_bsms = sorted({
                *list(getattr(target, "excluded_bsms", None) or []),
                *excluded,
            })
        if hasattr(target, "candidate_bsms"):
            target.candidate_bsms = [
                bsm
                for bsm in list(getattr(target, "candidate_bsms", None) or [])
                if bsm not in excluded
            ]
        if hasattr(target, "path_bsms"):
            target.path_bsms = [
                bsm
                for bsm in list(getattr(target, "path_bsms", None) or [])
                if bsm not in excluded
            ]
    return revised


async def select_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """SELECT node: GroundingResult + intent + context -> SiteSelectionDecision."""
    from app.domain.materialization.plan_builder import build_execution_plan
    from app.domain.allocation.select_service import select_aggregate
    from app.domain.allocation.global_zone_select import allocate_zones_for_select
    from app.domain.allocation.global_site_select import allocate_non_zone_for_select
    from app.domain.allocation.select_gate import evaluate_select_gate
    from app.contracts.artifacts.deferral_contracts import DeferralLedger
    from app.contracts.spatial.grounding_contracts import GroundingResult
    from app.contracts.workflow.parse_contracts import SpatialPlanningIntent
    from app.contracts.workflow.parse_result_contracts import IntentCompilationResult
    from app.contracts.workflow.repair_directive_contracts import RepairDirectiveCompilation

    retry_patch = _retry_patch(state, "select")
    context = await _require_context(state)
    grounding = _load_ref_artifact(state, "grounding_result", GroundingResult)
    intent = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
    plan_intent = _to_typed(
        getattr(intent, "typed_intent", None) or intent,
        SpatialPlanningIntent,
    )
    repair_directives = _load_ref_artifact(
        state,
        "repair_directives",
        RepairDirectiveCompilation,
    )
    plan_intent = _apply_repair_directives(plan_intent, repair_directives)
    deferral_ledger = _load_ref_artifact(state, "deferral_ledger", DeferralLedger)
    try:
        async with asyncio.timeout(max(600, int(GIS_TIMEOUT) * 20)):
            from app.data.catalog import DataCatalog
            from app.infrastructure.paths import session_run_dir

            suitability_surface = await asyncio.to_thread(
                build_suitability_surface,
                grounding,
                context,
                catalog=DataCatalog(),
                cache_dir=session_run_dir(_run_id(state)) / "terrain-evidence",
            )
            zone_allocation = await asyncio.to_thread(
                allocate_zones_for_select,
                plan_intent,
                suitability_surface,
                context,
                provenance_refs=[
                    _ref_digest((state.get("artifact_refs") or {}).get("grounding_result")),
                    _ref_digest((state.get("artifact_refs") or {}).get("target_projection")),
                ],
            )
            site_allocation = await asyncio.to_thread(
                allocate_non_zone_for_select,
                plan_intent,
                suitability_surface,
                context,
                provenance_refs=[
                    _ref_digest((state.get("artifact_refs") or {}).get("grounding_result")),
                    _ref_digest((state.get("artifact_refs") or {}).get("target_projection")),
                ],
            )
            decision, briefs = await asyncio.to_thread(
                select_aggregate,
                grounding,
                plan_intent,
                context,
                suitability_surface,
                zone_allocation,
                site_allocation,
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
    zone_allocation_ref = persist_stage_artifact(
        artifact_state,
        "select",
        "GlobalZoneAllocationResult",
        zone_allocation,
    )
    if zone_allocation_ref:
        artifact_refs["global_zone_allocation"] = zone_allocation_ref
        output_refs["global_zone_allocation"] = zone_allocation_ref
    site_allocation_ref = persist_stage_artifact(
        artifact_state,
        "select",
        "GlobalSiteAllocationResult",
        site_allocation,
    )
    if site_allocation_ref:
        artifact_refs["global_site_allocation"] = site_allocation_ref
        output_refs["global_site_allocation"] = site_allocation_ref
    portfolio_ref = persist_stage_artifact(
        artifact_state, "select", "PortfolioDecision", portfolio_decision
    )
    if portfolio_ref:
        artifact_refs["portfolio_decision"] = portfolio_ref
        output_refs["portfolio_decision"] = portfolio_ref
    spatial_targets = [
        target
        for field_name in (
            "project_targets",
            "zone_targets",
            "facilities",
            "development_axes",
            "road_targets",
        )
        for target in (getattr(plan_intent, field_name, None) or [])
        if getattr(target, "requires_spatial", True)
    ]
    gate = evaluate_select_gate(
        decision,
        target_count=len(spatial_targets),
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
        portfolio_decision_ref=_ref_digest(portfolio_ref),
        global_zone_allocation_ref=_ref_digest(zone_allocation_ref),
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
