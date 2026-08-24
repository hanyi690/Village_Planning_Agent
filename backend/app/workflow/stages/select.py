"""SELECT stage service: solve the spatial portfolio and execution plan."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from app.core.settings import GIS_TIMEOUT
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


def _demo_narrow_slice_target_ids(plan_intent: Any) -> set[str]:
    """Return the explicitly typed one-target demo scope, if present."""
    return {
        str(getattr(target, "target_id", "") or "")
        for target in list(getattr(plan_intent, "site_area_targets", None) or [])
        if str(getattr(target, "target_id", "") or "")
        and any(
            str(ref).startswith("demo:narrow-slice:")
            for ref in list(getattr(target, "claim_refs", None) or [])
        )
    }


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
    """SELECT node: grounded problem -> ScenarioSet/approval-bound plan."""
    from app.domain.allocation.select_gate import evaluate_scenario_select_gate
    from app.contracts.artifacts.deferral_contracts import DeferralLedger
    from app.contracts.spatial.grounding_contracts import GroundingResult
    from app.contracts.workflow.parse_contracts import SpatialPlanningIntent
    from app.contracts.workflow.parse_result_contracts import IntentCompilationResult
    from app.contracts.workflow.repair_directive_contracts import RepairDirectiveCompilation
    from app.contracts.planning.scenario import ScenarioSet

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
    deferred_target_ids = {
        str(entry.target_id).strip()
        for entry in (getattr(deferral_ledger, "entries", None) or ())
        if str(getattr(entry, "target_id", "") or "").strip()
    }
    demo_target_ids = _demo_narrow_slice_target_ids(plan_intent)
    suitability_grounding = grounding
    if demo_target_ids and hasattr(grounding, "model_copy"):
        # Keep the complete GROUND artifact intact, but do not spend the
        # terrain/suitability pass on unrelated prose targets.  This scope is
        # only admitted by the typed demo claim; ordinary projects still use
        # the full grounded candidate set.
        scoped_candidates = [
            candidate
            for candidate in list(getattr(grounding, "candidates", None) or [])
            if str(
                getattr(candidate, "target_ref", None)
                or getattr(candidate, "project_ref", None)
                or ""
            ) in demo_target_ids
        ]
        scoped_unresolved = [
            issue
            for issue in list(getattr(grounding, "unresolved", None) or [])
            if str(getattr(issue, "related_artifact_id", None) or "") in demo_target_ids
        ]
        suitability_grounding = grounding.model_copy(
            update={
                "candidates": scoped_candidates,
                "unresolved": scoped_unresolved,
            }
        )
    try:
        async with asyncio.timeout(max(600, int(GIS_TIMEOUT) * 20)):
            from app.data.catalog import DataCatalog
            from app.infrastructure.paths import session_run_dir

            suitability_surface = await asyncio.to_thread(
                build_suitability_surface,
                suitability_grounding,
                context,
                plan_intent=plan_intent,
                catalog=DataCatalog(),
                cache_dir=session_run_dir(_run_id(state)) / "terrain-evidence",
            )
    except TimeoutError as exc:
        logger.error("[workflow:select] candidate preparation timeout; failing closed")
        raise RuntimeError(
            "SELECT_TIMEOUT: candidate selection exceeded its cancellation boundary"
        ) from exc
    intent.typed_intent = plan_intent
    demand_portfolio = derive_demand_portfolio(
        plan_intent,
        claims=list(getattr(intent, "claims", None) or []),
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

        if deferred_target_ids:
            from app.domain.ground.scoped_problem import scope_grounded_problem

            grounding_ref = (artifact_refs.get("grounding_result") or {})
            problem = scope_grounded_problem(
                problem,
                deferred_target_ids,
                source_refs=(
                    f"artifact:grounding_result:{_ref_digest(grounding_ref)}",
                    f"artifact:deferral_ledger:{_ref_digest((artifact_refs.get('deferral_ledger') or {}))}",
                ),
                reason="explicit DeferralLedger target scope",
            )
        problem = refine_grounded_problem(problem, suitability_surface)
        # The opt-in demo is deliberately a one-target acceptance slice.  L3
        # still produces the complete program, but the fixture must not let
        # unrelated prose targets enter the executable scenario and create a
        # false "missing final feature" relation finding.  This is a typed
        # scope decision derived from the demo claim, not a general fallback.
        if demo_target_ids:
            all_target_ids = {
                str(item.target_id)
                for item in list(getattr(problem, "target_domains", None) or [])
                if str(getattr(item, "target_id", "") or "")
            }
            demo_deferred = sorted(all_target_ids - demo_target_ids)
            if demo_deferred:
                from app.domain.ground.scoped_problem import scope_grounded_problem

                problem = scope_grounded_problem(
                    problem,
                    demo_deferred,
                    source_refs=("demo:narrow_slice_scope",),
                    reason="explicit demo narrow-slice target scope",
                )
        if not deferred_target_ids:
            # The first partial SELECT attempt must still publish the exact
            # refined GroundedPlanningProblem consumed by the gate.  Without
            # this ref the gate could appear to describe a problem that was
            # never persisted, making a later HUMAN deferral unverifiable.
            grounded_ref = persist_stage_artifact(
                artifact_state,
                "select",
                "GroundedPlanningProblem",
                problem,
            )
            if grounded_ref:
                artifact_refs["scoped_grounding_problem"] = grounded_ref
                output_refs["scoped_grounding_problem"] = grounded_ref
        if deferred_target_ids:
            scoped_ref = persist_stage_artifact(
                artifact_state,
                "select",
                "GroundedPlanningProblem",
                problem,
            )
            if scoped_ref:
                artifact_refs["scoped_grounding_problem"] = scoped_ref
                output_refs["scoped_grounding_problem"] = scoped_ref
    scenario = None
    scenario_set = None
    scenario_set_ref = None
    scenario_ref = None
    approved_input_ref = None
    approved_input_candidate = None
    approval_candidate_kwargs = None
    if problem is not None:
        from app.domain.allocation.scenario_optimizer import optimize_scenarios
        from app.domain.relations.service import RelationEvaluationContext
        from app.domain.relations.reference_features import (
            resolve_relation_reference_features,
        )

        scenario_id = f"scenario-set:{_run_id(state) or 'current'}"
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
            scenario_set = optimize_scenarios(
                problem,
                set_id=scenario_id,
                evaluator_context=evaluator_context,
                baseline_ref=str(getattr(problem, "baseline_ref", "") or ""),
                max_scenarios=int(
                    (state.get("config") or {}).get("max_scenarios", 8)
                ),
            )
            # Persist a provisional ScenarioSet member when no feasible
            # recommendation exists. It is never treated as approval; its
            # status/findings remain the explicit partial-delivery boundary.
            scenario = scenario_set.recommended or (
                scenario_set.scenarios[0] if scenario_set.scenarios else None
            )
        except Exception as exc:
            logger.error(
                "[workflow:select] scenario solver failed closed (exception_type=%s)",
                type(exc).__name__,
            )
            from app.contracts.planning.scenario import SolverCertificate

            scenario_set = ScenarioSet(
                set_id=scenario_id,
                problem_fingerprint=str(getattr(problem, "fingerprint", "") or "unknown"),
                scenarios=[],
                recommendation_policy="lexicographic_relation_then_suitability",
                solver_certificate=SolverCertificate(
                    problem_fingerprint=str(getattr(problem, "fingerprint", "") or "unknown"),
                    model_digest="select-exception",
                    solver_version="scenario-optimizer-v1",
                    status="unknown",
                    termination_reason="scenario_optimizer_failed",
                    conflict_explanations=[
                        f"SCENARIO_OPTIMIZER_FAILED:{type(exc).__name__}",
                    ],
                ),
                infeasibility_explanations=["scenario_optimizer_failed"],
            )
        scenario_set_ref = persist_stage_artifact(
            artifact_state, "select", "ScenarioSet", scenario_set
        )
        if scenario_set_ref:
            artifact_refs["scenario_set"] = scenario_set_ref
            output_refs["scenario_set"] = scenario_set_ref
        if scenario is not None:
            scenario_ref = persist_stage_artifact(
                artifact_state, "select", "PlanningScenario", scenario
            )
            if scenario_ref:
                artifact_refs["planning_scenario"] = scenario_ref
                output_refs["planning_scenario"] = scenario_ref
            approval_status = (
                "auto" if str(scenario.status) == "complete" else "provisional"
            )
            from app.domain.allocation.approval_input import (
                build_approved_execution_input,
            )

            context_ref = dict(state.get("context_ref") or {})
            bundle_snapshot_digest = str(
                context_ref.get("snapshot_digest")
                or context_ref.get("bundle_snapshot_digest")
                or getattr(getattr(context, "data_snapshot", None), "digest", "")
                or ""
            )
            approval_candidate_kwargs = {
                "scenario_set": scenario_set,
                "scenario": scenario,
                "scenario_set_ref": scenario_set_ref,
                "scenario_ref": scenario_ref,
                "planning_program_ref": artifact_refs.get("planning_program"),
                "grounding_problem_ref": str(getattr(problem, "fingerprint", "") or ""),
                "context_ref": state.get("context_ref"),
                "bundle_snapshot_digest": bundle_snapshot_digest,
                "approval_id": f"approval:{scenario.scenario_id}",
                "approval_status": approval_status,
                "approved_by": ("system:auto-select" if approval_status == "auto" else ""),
                "approval_reason": (
                    "complete ScenarioSet recommendation"
                    if approval_status == "auto"
                    else "explicit human approval"
                ),
            }
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
    from app.domain.materialization.approved_plan_builder import (
        bind_approved_execution_plan,
        build_execution_plan_draft,
    )
    execution_plan = None
    if scenario is not None and str(getattr(scenario, "status", "")) == "complete":
        execution_plan = build_execution_plan_draft(
            scenario_set,
            scenario,
            plan_intent,
            problem,
            run_id=_run_id(state),
            context_version=_context_version(state),
            context_fingerprint=str(state.get("context_fingerprint") or ""),
        )
    if approval_candidate_kwargs is not None and execution_plan is not None:
        approved_input_candidate = build_approved_execution_input(
            **approval_candidate_kwargs,
            execution_plan=execution_plan,
        )
        if approved_input_candidate is not None:
            execution_plan = bind_approved_execution_plan(
                execution_plan,
                approved_input_candidate,
                scenario_set,
                scenario,
            )
            approved_input_ref = persist_stage_artifact(
                artifact_state,
                "select",
                "ApprovedExecutionInput",
                approved_input_candidate,
            )
            if approved_input_ref:
                artifact_refs["approved_execution_input"] = approved_input_ref
                output_refs["approved_execution_input"] = approved_input_ref
    gate = evaluate_scenario_select_gate(
        scenario_set,
        scenario,
        problem,
        approved_input=approved_input_candidate,
        input_artifact_refs=artifact_refs,
        previous_gate=state.get("select_gate"),
        context_version=_context_version(state),
    )
    if execution_plan is not None:
        plan_ref = persist_stage_artifact(
            artifact_state, "select", "ExecutionPlan", execution_plan
        )
        if plan_ref:
            output_refs["execution_plan"] = plan_ref
    context_patch = _adopt_context(state, context)
    # A scoped re-solve is a one-shot routing request.  Clear the marker after
    # SELECT has materialized the child problem/set; a later unrelated HUMAN
    # decision must not re-enter SELECT indefinitely.
    context_patch["scoped_replan_required"] = False
    return stage_completion_patch(
        state,
        "select",
        output_refs=output_refs,
        gate=gate,
        context_patch=context_patch,
        retry_patch=retry_patch,
    )


__all__ = ["select_node"]
