"""SELECT stage service: solve the spatial portfolio and execution plan."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from app.core.settings import GIS_TIMEOUT
from app.modules.select.approval_input import build_approved_execution_input
from app.modules.l2.demand import derive_demand_portfolio
from app.modules.l2.suitability import build_suitability_surface
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


def _scenario_card(scenario: Any) -> dict[str, Any]:
    """Project one scenario into the bounded SELECT reasoning context."""

    return {
        "scenario_id": str(getattr(scenario, "scenario_id", "") or ""),
        "status": str(getattr(scenario, "status", "") or ""),
        "target_selections": "; ".join(
            f"{getattr(selection, 'target_id', '')}:{getattr(selection, 'selection_mode', '')}:"
            f"{','.join(str(value) for value in list(getattr(selection, 'candidate_ids', None) or [])[:16])}:"
            f"resources={','.join(str(value) for value in list(getattr(selection, 'resource_refs', None) or [])[:8])}:"
            f"representations={','.join(str(value) for value in list(getattr(selection, 'representation_refs', None) or [])[:8])}"
            for selection in list(getattr(scenario, "target_selections", None) or [])[:32]
        ),
        "objective_vector": "; ".join(
            f"{key}={value}"
            for key, value in list((getattr(scenario, "objective_vector", None) or {}).items())[:16]
        ),
        "metrics": "; ".join(
            f"{key}={value}"
            for key, value in list((getattr(scenario, "metrics", None) or {}).items())[:16]
        ),
        "findings": "; ".join(
            f"{getattr(finding, 'code', '')}:{getattr(finding, 'severity', '')}:"
            f"{getattr(finding, 'target_id', '')}:{getattr(finding, 'relation_id', '')}"
            for finding in list(getattr(scenario, "findings", None) or [])[:24]
        ),
    }


async def _reason_select_scenario(
    scenario_set: Any,
    *,
    llm: Any | None = None,
) -> dict[str, Any] | None:
    """Ask one closed-set question about solver-produced scenario cards.

    This is advisory reasoning only.  The solver certificate and SELECT gate
    remain authoritative, so a provider failure cannot manufacture or remove a
    scenario.  The prompt contains no geometry, report body or raw evidence.
    """

    from app.core.llm_config import get_llm_settings
    from app.contracts.ground.spatial_reference_contracts import (
        CandidateSelectionProposal,
        render_candidate_selection_contract,
        spatial_candidate_input_digest,
        validate_spatial_candidate_proposal,
    )
    from app.contracts.llm.closed_set_contracts import CandidateDescriptor
    from app.infrastructure.structured_runtime.facade import (
        LLMCallSpec,
        create_flash_model,
        run_structured,
    )
    from app.infrastructure.context_runtime import build_bounded_table

    settings = get_llm_settings()
    if settings.disable_llm:
        return None
    scenarios = list(getattr(scenario_set, "scenarios", None) or [])
    if not scenarios:
        return None
    descriptors = [
        CandidateDescriptor(
            candidate_id=str(getattr(scenario, "scenario_id", "") or ""),
            kind="planning_scenario",
            label=str(getattr(scenario, "status", "") or ""),
            metadata=_scenario_card(scenario),
        )
        for scenario in scenarios
        if str(getattr(scenario, "scenario_id", "") or "").strip()
    ]
    if not descriptors:
        return None
    decision_id = f"select:scenario-set:{getattr(scenario_set, 'set_id', '')}"
    query_text = "；".join((
        f"set_id={getattr(scenario_set, 'set_id', '') or ''}",
        f"problem_fingerprint={getattr(scenario_set, 'problem_fingerprint', '') or ''}",
        f"recommendation_policy={getattr(scenario_set, 'recommendation_policy', '') or ''}",
    ))
    input_digest = spatial_candidate_input_digest(
        decision_id=decision_id,
        query_text=query_text,
        candidates=descriptors,
    )
    _, scenario_table = build_bounded_table(
        (
            "candidate_id",
            "status",
            "target_selections",
            "objective_vector",
            "metrics",
            "findings",
        ),
        [
            {
                "candidate_id": item.candidate_id,
                "status": item.label,
                "target_selections": item.metadata.get("target_selections", []),
                "objective_vector": item.metadata.get("objective_vector", {}),
                "metrics": item.metadata.get("metrics", {}),
                "findings": item.metadata.get("findings", []),
            }
            for item in descriptors
        ],
        max_rows=32,
        max_chars=6200,
    )
    prompt = "\n".join((
        render_candidate_selection_contract(item.candidate_id for item in descriptors),
        "这是 SELECT 的场景卡 advisory reasoning。只能从 solver 已生成的场景闭集中选择；"
        "不得生成候选、改写约束、改变指标或输出 geometry。solver certificate 和 gate 才是最终权威。",
        f"场景集合语义={query_text}",
        f"input_digest={input_digest}",
        "场景卡（Context Runtime 有界结构化表格）：",
        scenario_table,
    ))
    try:
        if llm is None:
            llm = create_flash_model(max_tokens=512, temperature=0.1)
        response = await run_structured(
            LLMCallSpec(
                stage="SELECT",
                contract_key="select.scenario_selection",
                response_model=CandidateSelectionProposal,
                call_type="closed_set",
                max_retries=0,
                timeout_s=settings.request_timeout_seconds(),
                max_tokens=512,
                incomplete_output_max_tokens=2048,
                max_concurrent=settings.provider_concurrency(),
                semaphore_scope="select",
                temperature=0.1,
                allow_content_json=True,
                timeout_includes_queue=False,
            ),
            [{"role": "user", "content": prompt}],
            context={
                "scenario_set_id": str(getattr(scenario_set, "set_id", "") or ""),
                "scenario_count": len(descriptors),
            },
            llm=llm,
        )
        decision = validate_spatial_candidate_proposal(
            decision_id=decision_id,
            query_text=query_text,
            candidates=descriptors,
            proposal=response,
        )
        return {
            "decision_id": decision_id,
            "status": decision.status,
            "selected_candidate_id": decision.selected_candidate_id or "",
            "candidate_set_digest": decision.candidate_set_digest,
            "input_digest": input_digest,
            "reason": decision.reason,
        }
    except Exception as exc:
        logger.warning("[workflow:select] scenario reasoning failed: %s", type(exc).__name__)
        return None


def _to_typed(data: Any, cls: type) -> Any:
    if data is None or isinstance(data, cls):
        return data
    if isinstance(data, dict):
        try:
            return cls(**data)
        except Exception:
            return data
    return data


def _complete_select_stage(
    state: Dict[str, Any],
    *,
    output_refs: Dict[str, Any],
    gate: Any,
    context_patch: Dict[str, Any],
    retry_patch: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return stage_completion_patch(
        state,
        "select",
        output_refs=output_refs,
        gate=gate,
        context_patch=context_patch,
        retry_patch=retry_patch,
    )


def _ref_digest(ref: Any) -> str:
    if isinstance(ref, dict):
        return str(ref.get("digest") or ref.get("descriptor_digest") or "")
    return str(getattr(ref, "digest", "") or getattr(ref, "descriptor_digest", "") or "")


def _bind_master_certificate_and_digest(
    certificate_payload: dict[str, Any],
    master_payload: dict[str, Any],
) -> None:
    """Bind the final master proof before strict ScenarioSet validation."""

    from app.contracts.select.scenario import (
        BackendCertificatePayload,
        derive_solver_model_digest,
    )

    certificate_payload["master_certificate"] = master_payload
    backend_payload = certificate_payload.get("backend_certificate")
    if not isinstance(backend_payload, dict):
        return
    backend_payload["master_certificate"] = master_payload
    backend_proof = BackendCertificatePayload.model_validate(backend_payload)
    certificate_payload["model_digest"] = derive_solver_model_digest(
        backend_proof,
        deterministic_seed=int(certificate_payload["deterministic_seed"]),
        search_limit=int(certificate_payload["search_limit"]),
    )


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
    from app.workflow.stages.support import require_upstream_gates

    require_upstream_gates(
        dict(state),
        (
            "data", "kg", "evidence", "l1", "l2", "l3",
            "target_projection", "ground",
        ),
    )
    from app.modules.select.select_gate import evaluate_scenario_select_gate
    from app.contracts.delivery.deferral_contracts import DeferralLedger
    from app.contracts.ground.grounding_contracts import GroundingResult
    from app.contracts.target_projection.parse_contracts import SpatialPlanningIntent
    from app.contracts.target_projection.parse_result_contracts import IntentCompilationResult
    from app.contracts.workflow.repair_directive_contracts import RepairDirectiveCompilation
    from app.contracts.select.scenario import ScenarioSet
    from app.contracts.target_projection.task_graph import PlanningTaskGraph

    retry_patch = _retry_patch(state, "select")
    context = await _require_context(state)
    grounding = _load_ref_artifact(state, "grounding_result", GroundingResult)
    intent = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
    task_graph = _load_ref_artifact(state, "planning_task_graph", PlanningTaskGraph)
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
    artifact_refs = dict(state.get("artifact_refs") or {})
    output_refs: Dict[str, Any] = {}
    artifact_state = dict(state)
    artifact_state["artifact_refs"] = artifact_refs

    problem = getattr(grounding, "problem", None)
    if problem is not None and deferred_target_ids:
        from app.modules.ground.problem_builder import scope_grounded_problem

        grounding_ref = artifact_refs.get("grounding_result") or {}
        problem = scope_grounded_problem(
            problem,
            deferred_target_ids,
            source_refs=(
                f"artifact:grounding_result:{_ref_digest(grounding_ref)}",
                f"artifact:deferral_ledger:{_ref_digest((artifact_refs.get('deferral_ledger') or {}))}",
            ),
            reason="explicit DeferralLedger target scope",
        )
    demand_portfolio = derive_demand_portfolio(
        plan_intent,
        claims=list(getattr(intent, "claims", None) or []),
    )
    preflight_problem = problem
    from app.modules.select.solver_readiness import build_solver_readiness

    readiness = build_solver_readiness(
        preflight_problem,
        demand_portfolio=demand_portfolio,
        context=context,
        task_graph=task_graph,
    )
    readiness_ref = persist_stage_artifact(
        artifact_state,
        "select",
        "SolverReadiness",
        readiness,
    )
    if readiness_ref:
        artifact_refs["solver_readiness"] = readiness_ref
        output_refs["solver_readiness"] = readiness_ref
    if not readiness.ready:
        if preflight_problem is not None:
            problem_ref = persist_stage_artifact(
                artifact_state,
                "select",
                "GroundedPlanningProblem",
                preflight_problem,
            )
            if problem_ref:
                artifact_refs["scoped_grounding_problem"] = problem_ref
                output_refs["scoped_grounding_problem"] = problem_ref
        demand_ref = persist_stage_artifact(
            artifact_state,
            "select",
            "DemandPortfolio",
            demand_portfolio,
        )
        if demand_ref:
            artifact_refs["demand_portfolio"] = demand_ref
            output_refs["demand_portfolio"] = demand_ref
        gate = evaluate_scenario_select_gate(
            None,
            None,
            preflight_problem,
            input_artifact_refs=artifact_refs,
            previous_gate=state.get("select_gate"),
            context_version=_context_version(state),
            planning_task_graph=task_graph,
            readiness=readiness,
        )
        context_patch = _adopt_context(state, context)
        context_patch["scoped_replan_required"] = False
        return _complete_select_stage(
            state,
            output_refs=output_refs,
            gate=gate,
            context_patch=context_patch,
            retry_patch=retry_patch,
        )

    suitability_grounding = grounding
    try:
        async with asyncio.timeout(max(600, int(GIS_TIMEOUT) * 20)):
            from app.infrastructure.paths import session_run_dir

            suitability_surface = await asyncio.to_thread(
                build_suitability_surface,
                suitability_grounding,
                context,
                plan_intent=plan_intent,
                # DATA is the only source authority.  Passing a newly
                # constructed legacy DataCatalog here used to discard the
                # session's normalized uploads and made terrain/source
                # resolution depend on Bundle layer names.  The terrain
                # resolver accepts both the generic catalog and the narrow
                # compatibility adapter when a legacy context is explicitly
                # in use.
                catalog=getattr(context, "data_resource_catalog", None),
                cache_dir=session_run_dir(_run_id(state)) / "terrain-evidence",
            )
    except TimeoutError as exc:
        logger.error("[workflow:select] candidate preparation timeout; failing closed")
        raise RuntimeError(
            "SELECT_TIMEOUT: candidate selection exceeded its cancellation boundary"
        ) from exc
    intent.typed_intent = plan_intent
    if task_graph is not None:
        status_counts = {
            status: sum(1 for task in task_graph.tasks if task.status == status)
            for status in sorted({task.status for task in task_graph.tasks})
        }
        logger.info("[workflow:select] consumed planning task graph statuses=%s", status_counts)
        if artifact_refs.get("planning_task_graph"):
            output_refs["planning_task_graph"] = artifact_refs["planning_task_graph"]
    if problem is not None:
        # GROUND keeps recall geometry and provenance.  SELECT has already
        # refined every source BSM into a parcel-level SuitabilityCandidate;
        # feed those alternatives to the relation solver instead of asking it
        # to choose from the original multi-parcel union geometry.
        from app.modules.select.refined_candidate_catalog import (
            refine_grounded_problem,
        )

        problem = refine_grounded_problem(problem, suitability_surface)
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
    solver_subproblem_plan = None
    use_solver_subproblem_merge = False
    select_reasoning = None
    if problem is not None:
        from app.modules.select.scenario_optimizer import optimize_scenarios
        from app.modules.select.subproblem_compiler import (
            compile_solver_subproblems,
        )
        from app.spatial.relations.service import RelationEvaluationContext
        from app.spatial.relations.reference_features import (
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
        solver_subproblem_plan = compile_solver_subproblems(
            problem,
            readiness=readiness,
        )
        target_subproblems = [
            item
            for item in solver_subproblem_plan.subproblems
            if str(item.subproblem_id).startswith("target:")
        ]
        target_problem_kinds = {
            str(item.problem_kind)
            for item in target_subproblems
            if str(item.problem_kind)
        }
        use_solver_subproblem_merge = (
            len(target_subproblems) > 1 and len(target_problem_kinds) > 1
        )
        if use_solver_subproblem_merge:
            plan_ref = persist_stage_artifact(
                artifact_state,
                "select",
                "SolverSubproblemPlan",
                solver_subproblem_plan,
            )
            if plan_ref:
                artifact_refs["solver_subproblem_plan"] = plan_ref
                output_refs["solver_subproblem_plan"] = plan_ref
        try:
            scenario_kwargs = {
                "set_id": scenario_id,
                "evaluator_context": evaluator_context,
                "baseline_ref": str(getattr(problem, "baseline_ref", "") or ""),
                "max_scenarios": int(
                    (state.get("config") or {}).get("max_scenarios", 8)
                ),
            }
            if use_solver_subproblem_merge:
                from app.modules.select.subproblem_optimizer import (
                    optimize_solver_subproblems,
                )

                scenario_set = optimize_solver_subproblems(
                    problem,
                    readiness=readiness,
                    **scenario_kwargs,
                )
            else:
                scenario_set = optimize_scenarios(problem, **scenario_kwargs)
            # Retain a diagnostic ScenarioSet member when no feasible
            # recommendation exists. It is never treated as approval; its
            # status and findings remain a non-executable boundary.
            scenario = scenario_set.recommended or (
                scenario_set.scenarios[0] if scenario_set.scenarios else None
            )
        except Exception as exc:
            logger.error(
                "[workflow:select] scenario solver failed closed (exception_type=%s)",
                type(exc).__name__,
            )
            from app.contracts.select.scenario import SolverCertificate

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
        if scenario_set is not None:
            from app.modules.select.master_coordinator import coordinate_master_plan

            recommended_candidate_ids = {
                candidate_id
                for selection in list(getattr(scenario_set.recommended, "target_selections", None) or [])
                for candidate_id in selection.candidate_ids
            }
            master_certificate = coordinate_master_plan(
                problem,
                solver_subproblem_plan,
                evaluator_context,
                allowed_candidate_ids=recommended_candidate_ids or None,
            )
            scenario_payload = scenario_set.model_dump(mode="json")
            certificate_payload = scenario_payload["solver_certificate"]
            master_payload = master_certificate.model_dump(mode="json")
            if master_certificate.status != "feasible":
                for scenario_row in scenario_payload.get("scenarios", []):
                    scenario_row["status"] = "partial"
                scenario_payload.update(
                    feasible_scenario_ids=[],
                    pareto_scenario_ids=[],
                    recommended_scenario_id="",
                    objective_vectors={},
                )
                certificate_payload["status"] = "unknown"
                certificate_payload["termination_reason"] = (
                    "master coordination did not produce a feasible global selection"
                )
                certificate_payload["feasible_scenario_count"] = 0
            _bind_master_certificate_and_digest(certificate_payload, master_payload)
            scenario_payload["fingerprint"] = ""
            scenario_set = ScenarioSet.model_validate(scenario_payload)
            scenario_set = scenario_set.bind_solver_readiness(readiness)
            scenario = scenario_set.recommended or (
                scenario_set.scenarios[0] if scenario_set.scenarios else None
            )
        if scenario_set is not None:
            select_reasoning = await _reason_select_scenario(scenario_set)
            if select_reasoning is not None:
                logger.info(
                    "[workflow:select] advisory scenario reasoning status=%s selected=%s",
                    select_reasoning.get("status", ""),
                    select_reasoning.get("selected_candidate_id", ""),
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
            if str(scenario.status) == "complete":
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
                    "approval_status": "auto",
                    "approved_by": "system:auto-select",
                    "approval_reason": "complete ScenarioSet recommendation",
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
    from app.modules.execute.approved_plan_builder import (
        bind_approved_execution_plan,
        build_execution_plan_draft,
    )
    execution_plan = None
    selection_decision_set = None
    selection_decision_set_ref = None
    if scenario is not None and str(getattr(scenario, "status", "")) == "complete":
        from app.modules.select.resource_binding import (
            SelectionBindingError,
            build_selection_decision_set,
        )

        try:
            selection_decision_set = build_selection_decision_set(
                scenario,
                problem,
                getattr(context, "data_resource_catalog", None),
            )
            selection_decision_set_ref = persist_stage_artifact(
                artifact_state,
                "select",
                "SelectionDecisionSet",
                selection_decision_set,
                artifact_key="selection_decisions",
            )
            if selection_decision_set_ref:
                artifact_refs["selection_decisions"] = selection_decision_set_ref
                output_refs["selection_decisions"] = selection_decision_set_ref
            execution_plan = build_execution_plan_draft(
                scenario_set,
                scenario,
                plan_intent,
                problem,
                selection_decision_set=selection_decision_set,
                run_id=_run_id(state),
                context_version=_context_version(state),
                context_fingerprint=str(state.get("context_fingerprint") or ""),
            )
        except SelectionBindingError as exc:
            logger.warning(
                "[workflow:select] resource binding failed closed codes=%s",
                sorted({str(item.get("code") or "") for item in exc.diagnostics}),
            )
            diagnostic_ref = persist_stage_artifact(
                artifact_state,
                "select",
                "SelectionBindingDiagnostics",
                {"diagnostics": exc.diagnostics},
                artifact_key="selection_binding_diagnostics",
            )
            if diagnostic_ref:
                artifact_refs["selection_binding_diagnostics"] = diagnostic_ref
                output_refs["selection_binding_diagnostics"] = diagnostic_ref
        except ValueError as exc:
            diagnostic_ref = persist_stage_artifact(
                artifact_state,
                "select",
                "SelectionBindingDiagnostics",
                {
                    "diagnostics": [{
                        "code": "selection_execution_plan_binding_invalid",
                        "exception_type": type(exc).__name__,
                    }]
                },
                artifact_key="selection_binding_diagnostics",
            )
            if diagnostic_ref:
                artifact_refs["selection_binding_diagnostics"] = diagnostic_ref
                output_refs["selection_binding_diagnostics"] = diagnostic_ref
    if approval_candidate_kwargs is not None and execution_plan is not None:
        approved_input_candidate = build_approved_execution_input(
            **approval_candidate_kwargs,
            execution_plan=execution_plan,
            selection_decision_set_ref=selection_decision_set_ref,
            selection_decision_set_digest=(
                selection_decision_set.decision_set_digest
                if selection_decision_set is not None
                else ""
            ),
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
        solver_subproblem_plan=solver_subproblem_plan,
        planning_task_graph=task_graph,
        readiness=readiness,
        selection_decision_set=selection_decision_set,
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
    return _complete_select_stage(
        state,
        output_refs=output_refs,
        gate=gate,
        context_patch=context_patch,
        retry_patch=retry_patch,
    )


__all__ = ["select_node"]
