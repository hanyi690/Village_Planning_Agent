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
            "site_area_targets",
            "zone_targets",
            "facilities",
            "development_axes",
            "road_targets",
            "linear_targets",
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
    from app.contracts.planning.scenario import PlanningScenario, ScenarioFinding

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
                plan_intent=plan_intent,
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
    problem = getattr(grounding, "problem", None)
    if problem is not None:
        # GROUND keeps recall geometry and provenance.  SELECT has already
        # refined every source BSM into a parcel-level SuitabilityCandidate;
        # feed those alternatives to the relation solver instead of asking it
        # to choose from the original multi-parcel union geometry.
        from app.domain.allocation.refined_candidate_catalog import (
            refine_grounded_problem,
        )

        problem = refine_grounded_problem(problem, suitability_surface)
    scenario = None
    scenario_ref = None
    if problem is not None:
        from app.domain.allocation.scenario_solver import solve_scenario
        from app.domain.relations.service import RelationEvaluationContext
        from app.domain.relations.reference_features import (
            resolve_relation_reference_features,
        )

        scenario_id = f"scenario:{_run_id(state) or 'current'}"
        networks = (
            getattr(context, "networks", None)
            or getattr(context, "network_snapshots", None)
            or {}
        )
        reference_resolution = resolve_relation_reference_features(
            context,
            list(getattr(problem, "constraint_factors", None) or []),
            scenario_id=scenario_id,
        )
        if reference_resolution.diagnostics:
            logger.info(
                "[workflow:select] external relation references unresolved: %s",
                list(reference_resolution.diagnostics),
            )
        evaluator_context = RelationEvaluationContext(
            scenario_id=scenario_id,
            metric_crs=str(
                getattr(context, "metric_crs", None)
                or getattr(context, "display_crs", None)
                or "EPSG:3857"
            ),
            networks=networks,
            demands=(
                getattr(context, "demands", None)
                or getattr(context, "demand_snapshots", None)
                or {}
            ),
            reference_features=reference_resolution.features,
            reference_diagnostics=reference_resolution.diagnostics,
            execution_trace=getattr(context, "execution_trace", None),
        )
        try:
            scenario = solve_scenario(
                problem,
                scenario_id=scenario_id,
                evaluator_context=evaluator_context,
            )
        except Exception as exc:
            logger.exception("[workflow:select] scenario solver failed closed")
            from app.domain.allocation.scenario_builder import build_planning_scenario

            scenario = build_planning_scenario(
                scenario_id=scenario_id,
                problem=problem,
                relation_satisfactions=[],
                features=[],
                findings=[ScenarioFinding(
                    code="SCENARIO_SOLVER_FAILED",
                    severity="error",
                    message=str(exc),
                )],
                metrics={"selected_candidate_count": 0.0},
                status="failed",
            )
        scenario_ref = persist_stage_artifact(
            artifact_state, "select", "PlanningScenario", scenario
        )
        if scenario_ref:
            artifact_refs["planning_scenario"] = scenario_ref
            output_refs["planning_scenario"] = scenario_ref
        decision.scenario_id = scenario.scenario_id
        decision.relation_satisfaction = list(scenario.relation_satisfactions or [])
        selected_by_target = {
            item.target_id: list(item.candidate_ids)
            for item in (scenario.target_selections or [])
        }
        candidate_by_id = {
            str(getattr(candidate, "candidate_id", "")): candidate
            for candidate in list(getattr(problem, "candidate_geometries", None) or [])
        }
        non_spatial_target_ids = {
            str(getattr(target, "target_id", "") or "")
            for field_name in (
                "site_area_targets",
                "zone_targets",
                "facilities",
                "development_axes",
                "road_targets",
                "linear_targets",
            )
            for target in list(getattr(plan_intent, field_name, None) or [])
            if not getattr(target, "requires_spatial", True)
        }
        scenario_is_executable = str(scenario.status) in {"complete", "partial"} and not any(
            str(getattr(row, "criticality", "") or "") == "hard"
            and str(getattr(row, "status", "") or "") != "satisfied"
            for row in list(scenario.relation_satisfactions or [])
        )
        for assignment in list(decision.target_assignments or []):
            target_id = str(getattr(assignment, "target_id", "") or "")
            selected_candidate_ids = list(selected_by_target.get(target_id, []))
            selected_candidates = [
                candidate_by_id[candidate_id]
                for candidate_id in selected_candidate_ids
                if candidate_id in candidate_by_id
            ]
            if scenario_is_executable and selected_candidate_ids and len(selected_candidates) == len(selected_candidate_ids):
                candidate = selected_candidates[0] if len(selected_candidates) == 1 else None
                source_bsms = [
                    bsm
                    for selected in selected_candidates
                    for bsm in (getattr(selected, "source_bsms", None) or [])
                ]
                feature_bsms = [
                    bsm
                    for selected in selected_candidates
                    for bsm in (getattr(selected, "feature_bsms", None) or [])
                ]
                source_feature_ids = [
                    value
                    for selected in selected_candidates
                    for value in (getattr(selected, "source_feature_ids", None) or [])
                ]
                entity_refs = [
                    value
                    for selected in selected_candidates
                    for value in (getattr(selected, "entity_refs", None) or [])
                ]
                relation_refs = [
                    value
                    for selected in selected_candidates
                    for value in (getattr(selected, "relation_refs", None) or [])
                ]
                evidence_refs = [
                    value
                    for selected in selected_candidates
                    for value in (getattr(selected, "evidence_refs", None) or [])
                ]
                binding = dict(getattr(assignment, "target_binding", None) or {})
                binding.update({
                    "scenario_id": scenario.scenario_id,
                    "candidate_ids": selected_candidate_ids,
                    "source_bsms": source_bsms,
                    "feature_bsms": feature_bsms,
                    "source_feature_ids": source_feature_ids,
                    "entity_refs": entity_refs,
                    "relation_refs": relation_refs,
                    "evidence_refs": evidence_refs,
                })
                if candidate is not None:
                    binding.update({
                        "candidate_id": candidate.candidate_id,
                        "candidate_geometry_wkt": str(getattr(candidate, "wkt", "") or ""),
                        "spatial_domain_kind": str(getattr(candidate, "spatial_domain_kind", "") or ""),
                        "source_area_ha": getattr(candidate, "source_area_ha", None),
                        "planning_area_ha": getattr(candidate, "planning_area_ha", None),
                        "coverage_ratio": getattr(candidate, "coverage_ratio", None),
                        "l1_snapshot_ref": str(getattr(candidate, "l1_snapshot_ref", "") or ""),
                        "bundle_snapshot_digest": str(getattr(candidate, "bundle_snapshot_digest", "") or ""),
                        "source_binding_ref": str(getattr(candidate, "source_binding_ref", "") or ""),
                    })
                assignment.target_binding = binding
                if len(feature_bsms) == 1:
                    assignment.feature_bsm = feature_bsms[0]
                if len(source_feature_ids) == 1:
                    assignment.source_feature_id = source_feature_ids[0]
                if len(entity_refs) == 1:
                    assignment.entity_ref = entity_refs[0]
                assignment.relation_refs = relation_refs
                assignment.evidence_refs = evidence_refs
                if candidate is not None:
                    assignment.l1_snapshot_ref = str(getattr(candidate, "l1_snapshot_ref", "") or "")
                    assignment.bundle_snapshot_digest = str(getattr(candidate, "bundle_snapshot_digest", "") or "")
                if source_bsms and len(selected_candidates) == 1:
                    if getattr(assignment, "target_type", "") == "zone":
                        assignment.selected_bsms = source_bsms
                    else:
                        assignment.selected_bsm = source_bsms[0]
                assignment.status = "placed"
            elif target_id not in non_spatial_target_ids:
                assignment.status = "deferred"
                assignment.reason = (
                    "scenario_hard_relation_blocked"
                    if not scenario_is_executable
                    else "scenario_candidate_binding_missing"
                )
        if not scenario_is_executable:
            decision.review_status = "pending_review"
    if problem is not None:
        decision.relation_satisfaction = list(
            getattr(decision, "relation_satisfaction", None)
            or getattr(problem, "relation_satisfaction", None)
            or []
        )
        unresolved_relations = [
            item
            for item in decision.relation_satisfaction
            if item.status in {"unknown", "deferred", "violated"}
        ]
        decision.decision_factors["relation_count"] = len(
            decision.relation_satisfaction
        )
        decision.decision_factors["relation_unverified_count"] = len(
            unresolved_relations
        )
        hard_factor_ids = {
            str(getattr(factor, "factor_id", ""))
            for factor in list(getattr(problem, "constraint_factors", None) or [])
            if bool(getattr(factor, "hard", False))
        }
        if any(
            set(getattr(item, "factor_ids", None) or []) & hard_factor_ids
            for item in unresolved_relations
        ):
            decision.review_status = "pending_review"
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
            "site_area_targets",
            "zone_targets",
            "facilities",
            "development_axes",
            "road_targets",
            "linear_targets",
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
        scenario_target_selections=(
            {
                item.target_id: list(item.candidate_ids)
                for item in (getattr(scenario, "target_selections", None) or [])
            }
            if scenario is not None
            else {}
        ),
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
