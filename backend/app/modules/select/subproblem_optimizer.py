"""Bounded execution and deterministic merge for typed solver subproblems.

This module is an additive composition entry point.  The existing
``optimize_scenarios`` facade remains the single-problem route; this adapter
only slices a closed GROUND problem, delegates each ready slice to that
facade, and combines its formal results under the parent problem fingerprint.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Sequence
from typing import Any

from app.contracts.select.scenario import (
    ObjectiveDefinition,
    PlanningScenario,
    ScenarioFinding,
    ScenarioFeature,
    ScenarioSet,
    ScenarioTargetSelection,
)
from app.contracts.select.solver import SolverConfig
from app.contracts.select.solver_readiness import SolverReadiness
from app.contracts.ground.grounded_problem import GroundedPlanningProblem
from app.spatial.relations.service import RelationEvaluationContext

from .scenario_optimizer import (
    _build_solver_certificate,
    _canonical_objective_definitions,
    _unsupported_backend_result,
    optimize_scenarios,
)
from .solver_portfolio import build_solver_problem_view
from .subproblem_compiler import compile_solver_subproblems


def _target_refs_for_subproblem(subproblem: Any) -> set[str]:
    return {
        str(ref).strip()
        for ref in getattr(subproblem, "target_refs", ())
        if str(ref).strip()
    }


def _factor_touches_target(factor: Any, target_ids: set[str]) -> bool:
    return bool(
        {
            str(getattr(factor, "subject_ref", "") or "").strip(),
            str(getattr(factor, "object_ref", "") or "").strip(),
        }
        & target_ids
    )


def _slice_problem(
    problem: GroundedPlanningProblem,
    subproblem: Any,
) -> GroundedPlanningProblem:
    """Build a typed child boundary without changing source candidate facts."""

    target_ids = _target_refs_for_subproblem(subproblem)
    all_target_ids = {
        item.target_id
        for item in [*problem.target_domains, *problem.candidate_domains]
        if str(getattr(item, "target_id", "") or "").strip()
    }
    candidate_ids = {
        candidate_id
        for values in getattr(subproblem, "candidate_ids_by_target", {}).values()
        for candidate_id in values
    }
    payload = problem.model_dump(mode="python")
    payload.pop("fingerprint", None)
    payload.pop("candidate_completeness", None)
    payload["target_domains"] = [
        item.model_dump(mode="python")
        for item in problem.target_domains
        if item.target_id in target_ids
    ]
    payload["candidate_domains"] = [
        item.model_dump(mode="python")
        for item in problem.candidate_domains
        if item.target_id in target_ids
    ]
    payload["candidate_geometries"] = [
        item.model_dump(mode="python")
        for item in problem.candidate_geometries
        if item.target_id in target_ids and item.candidate_id in candidate_ids
    ]
    payload["bindings"] = [
        item.model_dump(mode="python")
        for item in problem.bindings
        if item.target_id in target_ids
    ]
    payload["constraint_factors"] = [
        item.model_dump(mode="python")
        for item in problem.constraint_factors
        if _factor_touches_target(item, target_ids)
        and not (
            str(getattr(item, "subject_ref", "") or "").strip() in all_target_ids
            and str(getattr(item, "object_ref", "") or "").strip() in all_target_ids
            and str(getattr(item, "object_ref_kind", "target") or "target") == "target"
            and not {
                str(getattr(item, "subject_ref", "") or "").strip(),
                str(getattr(item, "object_ref", "") or "").strip(),
            }.issubset(target_ids)
        )
    ]
    payload["relation_satisfaction"] = [
        item.model_dump(mode="python")
        for item in problem.relation_satisfaction
        if (
            str(getattr(item, "subject_ref", "") or "").strip() in target_ids
            or str(getattr(item, "object_ref", "") or "").strip() in target_ids
        )
    ]
    payload["unresolved"] = [
        item.model_dump(mode="python")
        for item in problem.unresolved
        if not item.target_id or item.target_id in target_ids
    ]
    payload["deferred"] = [
        item.model_dump(mode="python")
        for item in problem.deferred
        if not item.target_id or item.target_id in target_ids
    ]
    payload["deferred_target_ids"] = [
        target_id for target_id in problem.deferred_target_ids if target_id in target_ids
    ]
    payload["scope_source_refs"] = list(problem.scope_source_refs)
    if subproblem.problem_kind == "parcel_assignment":
        shared_resource_refs = list(problem.shared_resource_refs)
        if problem.parcel_resource_pool is not None:
            shared_resource_refs.append(problem.parcel_resource_pool.pool_id)
        payload["shared_resource_refs"] = sorted(set(shared_resource_refs))
    else:
        payload["shared_resource_refs"] = []
    if subproblem.problem_kind == "parcel_assignment" and problem.parcel_resource_pool is not None:
        candidate_bsms = {
            str(bsm).strip()
            for item in payload["candidate_geometries"]
            for bsm in list(item.get("source_bsms") or [])
            if str(bsm).strip()
        }
        pool_payload = problem.parcel_resource_pool.model_dump(mode="python")
        pool_payload["resources"] = [
            resource
            for resource in pool_payload.get("resources", [])
            if not candidate_bsms or resource.get("bsm") in candidate_bsms
        ]
        payload["parcel_resource_pool"] = pool_payload
    else:
        payload["parcel_resource_pool"] = None
    payload["network_refs"] = (
        list(problem.network_refs)
        if subproblem.problem_kind in {"coverage", "network_path"}
        else []
    )
    payload["solver_kind"] = subproblem.problem_kind
    payload["solver_kind_reasons"] = [
        f"typed_subproblem:{subproblem.subproblem_id}",
        f"parent_problem:{problem.fingerprint}",
    ]
    payload["scope_policy"] = "full"
    payload["parent_problem_fingerprint"] = problem.fingerprint
    payload["deferred_target_ids"] = [
        target_id for target_id in problem.deferred_target_ids if target_id in target_ids
    ]
    return GroundedPlanningProblem(**payload)


def _unsupported_composition(
    problem: GroundedPlanningProblem,
    *,
    set_id: str,
    baseline_ref: str,
    evaluator_context: RelationEvaluationContext,
    reason_codes: Sequence[str],
    required_input_refs: Sequence[str],
    objective_definitions: Sequence[ObjectiveDefinition],
    deterministic_seed: int,
    search_limit: int,
    max_scenarios: int,
) -> ScenarioSet:
    view = build_solver_problem_view(problem, evaluator_context=evaluator_context)
    return _unsupported_backend_result(
        problem,
        set_id=set_id,
        baseline_ref=baseline_ref,
        view=view,
        reason_codes=list(reason_codes),
        required_input_refs=sorted({*view.required_input_refs, *required_input_refs}),
        objective_definitions=objective_definitions,
        deterministic_seed=deterministic_seed,
        search_limit=search_limit,
        max_scenarios=max_scenarios,
    )


def _infeasible_composition(
    problem: GroundedPlanningProblem,
    *,
    set_id: str,
    baseline_ref: str,
    child_sets: Sequence[ScenarioSet],
    reason_codes: Sequence[str],
    required_input_refs: Sequence[str],
    objective_definitions: Sequence[ObjectiveDefinition],
    deterministic_seed: int,
    search_limit: int,
    max_scenarios: int,
) -> ScenarioSet:
    """Return a formal parent-level infeasibility proof.

    A child solver that searched a complete typed input and found no valid
    assignment is not an unsupported route.  Preserve that distinction so
    SELECT reports a real capacity/overlap infeasibility rather than a
    compatibility-style ``unknown`` result.
    """

    child_certificate_refs = sorted(
        item.solver_certificate.fingerprint for item in child_sets
    )
    refs = sorted({
        *required_input_refs,
        *child_certificate_refs,
    })
    route = {
        "backend_id": "deterministic_subproblem_merge",
        "backend_version": "1.0",
        "problem_kind": "bounded_multiobjective",
        "input_digest": hashlib.sha256(
            json.dumps(
                {
                    "problem": problem.fingerprint,
                    "child_certificates": child_certificate_refs,
                    "reason_codes": sorted(set(reason_codes)),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "required_input_refs": refs,
        "deterministic_settings": {
            "deterministic_seed": deterministic_seed,
            "search_limit": search_limit,
            "max_scenarios": max_scenarios,
        },
        "solver_config": SolverConfig(
            deterministic_seed=deterministic_seed,
            search_limit=search_limit,
            max_scenarios=max_scenarios,
            objective_definitions=list(objective_definitions),
            backend_version="1.0",
        ).model_dump(mode="json"),
    }
    explanations = sorted({str(code) for code in reason_codes if str(code).strip()})
    certificate = _build_solver_certificate(
        problem=problem,
        model_digest=route["input_digest"],
        deterministic_seed=deterministic_seed,
        search_limit=search_limit,
        status="infeasible",
        termination_reason="one or more coordinated solver subproblems are formally infeasible",
        conflict_explanations=explanations,
        backend_route=route,
        solver_invoked=True,
        input_closed=True,
        enumeration_complete=True,
    )
    return ScenarioSet(
        set_id=set_id,
        problem_fingerprint=problem.fingerprint,
        baseline_ref=baseline_ref or problem.baseline_ref,
        recommendation_policy="deterministic_subproblem_merge",
        objective_definitions=list(objective_definitions),
        infeasibility_explanations=explanations,
        solver_certificate=certificate,
    )


def _cross_subproblem_resource_conflicts(
    problem: GroundedPlanningProblem,
    subproblems: Sequence[Any],
) -> list[tuple[str, tuple[str, ...]]]:
    """Find typed resource identities shared by independent target slices.

    Child solvers intentionally do not see cross-target constraints.  Any
    remaining repeated resource after typed parcel coordination therefore
    indicates a cross-kind coordination boundary that is not executable.
    """

    geometries = {
        str(item.candidate_id): item
        for item in problem.candidate_geometries
        if str(item.candidate_id).strip()
    }
    pool = problem.parcel_resource_pool
    resource_by_bsm = {
        str(resource.bsm).strip(): resource
        for resource in (pool.resources if pool is not None else [])
        if str(resource.bsm).strip()
    }
    global_refs = {
        str(ref).strip()
        for ref in problem.shared_resource_refs
        if str(ref).strip()
    }
    owners: dict[str, dict[str, set[str]]] = {}
    for subproblem in subproblems:
        target_ids = _target_refs_for_subproblem(subproblem)
        if not target_ids:
            continue
        refs: set[str] = set()
        for candidate_ids in getattr(subproblem, "candidate_ids_by_target", {}).values():
            for candidate_id in candidate_ids:
                candidate = geometries.get(str(candidate_id))
                if candidate is None:
                    continue
                parcel_like = (
                    subproblem.problem_kind == "parcel_assignment"
                    or candidate.materialization_role
                    in {"site_footprint", "land_use_assignment"}
                )
                if not parcel_like:
                    continue
                candidate_bsms = {
                    str(bsm).strip()
                    for bsm in candidate.source_bsms
                    if str(bsm).strip()
                }
                refs.update(candidate_bsms)
                for bsm in candidate_bsms:
                    resource = resource_by_bsm.get(bsm)
                    if resource is not None:
                        refs.update(
                            str(ref).strip()
                            for ref in (resource.resource_id, resource.geometry_ref)
                            if str(ref).strip()
                        )
                # A global ref is evidence of ownership only when it matches
                # this candidate's own typed resource identity.
                refs.update(global_refs.intersection(refs))
        for ref in refs:
            owners.setdefault(ref, {}).setdefault(subproblem.subproblem_id, set()).update(target_ids)
    return sorted(
        (ref, tuple(sorted({target_id for target_ids in by_subproblem.values() for target_id in target_ids})))
        for ref, by_subproblem in owners.items()
        if len(by_subproblem) > 1
    )


def _merged_scenario_id(set_id: str, child_ids: Sequence[str]) -> str:
    raw = json.dumps(sorted(child_ids), ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{set_id}:scenario:{digest}"


def _merge_product(
    problem: GroundedPlanningProblem,
    child_scenarios: Sequence[PlanningScenario],
    *,
    set_id: str,
    objective_definitions: Sequence[ObjectiveDefinition],
    force_partial: bool = False,
    extra_findings: Sequence[ScenarioFinding] = (),
) -> PlanningScenario:
    scenario_id = _merged_scenario_id(
        set_id,
        [item.scenario_id for item in child_scenarios],
    )
    selections: dict[str, ScenarioTargetSelection] = {}
    features: list[ScenarioFeature] = []
    relations: dict[str, Any] = {}
    metrics: dict[str, float] = {}
    objective_vector: dict[str, float] = {
        definition.objective_id: 0.0
        for definition in objective_definitions
    }
    findings: list[Any] = list(extra_findings)
    for child in child_scenarios:
        for selection in child.target_selections:
            if selection.target_id in selections:
                raise ValueError(f"duplicate target in solver subproblem merge: {selection.target_id}")
            selections[selection.target_id] = selection
        for feature in child.feature_intents:
            feature_payload = feature.model_dump(mode="python")
            feature_payload["scenario_id"] = scenario_id
            feature_payload["feature_id"] = (
                f"feature:{scenario_id}:{feature.target_id}:{feature.candidate_id}"
            )
            features.append(ScenarioFeature(**feature_payload))
        for relation in child.relation_satisfactions:
            existing = relations.get(relation.relation_id)
            if existing is not None and existing.model_dump(mode="json") != relation.model_dump(mode="json"):
                raise ValueError(f"conflicting relation in solver subproblem merge: {relation.relation_id}")
            relations[relation.relation_id] = relation
        for key, value in child.metrics.items():
            metrics[key] = metrics.get(key, 0.0) + float(value)
        for definition in objective_definitions:
            objective_vector[definition.objective_id] += float(
                child.objective_vector.get(definition.objective_id, 0.0)
            )
        findings.extend(child.findings)
    status = (
        "partial"
        if force_partial
        else ("complete" if all(item.status == "complete" for item in child_scenarios) else "partial")
    )
    return PlanningScenario(
        scenario_id=scenario_id,
        baseline_ref=problem.baseline_ref,
        problem_fingerprint=problem.fingerprint,
        target_selections=list(selections.values()),
        feature_intents=features,
        relation_satisfactions=list(relations.values()),
        metrics=metrics,
        objective_vector=objective_vector,
        findings=findings,
        status=status,
    )


def _merge_scenario_sets(
    problem: GroundedPlanningProblem,
    child_sets: Sequence[ScenarioSet],
    *,
    plan: Any,
    set_id: str,
    baseline_ref: str,
    objective_definitions: Sequence[ObjectiveDefinition],
    deterministic_seed: int,
    search_limit: int,
    max_scenarios: int,
    blocking_subproblems: Sequence[Any] = (),
) -> ScenarioSet:
    choices = [
        sorted(
            child_set.feasible
            or list(child_set.scenarios),
            key=lambda item: item.scenario_id,
        )
        for child_set in child_sets
    ]
    if any(not values for values in choices):
        raise ValueError("solver subproblem has no formal feasible scenario")
    total = 1
    for values in choices:
        total *= len(values)
    # ``max_scenarios`` is an output/materialization bound, not merely a
    # preference.  The parent product must never expand to ``search_limit``
    # rows just because each child was independently bounded.
    materialization_limit = min(search_limit, max_scenarios)
    output: list[PlanningScenario] = []
    blocked_findings = [
        ScenarioFinding(
            code=(
                "TOPOLOGY_SUBPROBLEM_BLOCKED"
                if item.problem_kind == "topology_layout"
                else "SOLVER_SUBPROBLEM_BLOCKED"
            ),
            severity="error",
            message=(
                "Typed solver prerequisite is retained as a blocked input: "
                + item.subproblem_id
            ),
            relation_id=(item.relation_refs[0] if item.relation_refs else item.subproblem_id),
            target_id=(item.target_refs[0] if item.target_refs else ""),
        )
        for item in blocking_subproblems
    ]
    for product in itertools.product(*choices):
        if len(output) >= materialization_limit:
            break
        output.append(
            _merge_product(
                problem,
                product,
                set_id=set_id,
                objective_definitions=objective_definitions,
                force_partial=bool(blocking_subproblems),
                extra_findings=blocked_findings,
            )
        )
    output = sorted(output, key=lambda item: item.scenario_id)
    if not output:
        raise ValueError("solver subproblem merge produced no scenarios")
    feasible_ids = [item.scenario_id for item in output if item.status == "complete"]
    if not blocking_subproblems and len(feasible_ids) != len(output):
        raise ValueError("solver subproblem merge contains non-complete formal scenarios")
    recommended_id = feasible_ids[0] if feasible_ids else ""
    vectors = {
        item.scenario_id: dict(item.objective_vector)
        for item in output
    }
    child_certificate_refs = [
        child_set.solver_certificate.fingerprint
        for child_set in child_sets
    ]
    required_refs = sorted({
        plan.fingerprint,
        *child_certificate_refs,
        *[
            ref
            for subproblem in plan.subproblems
            for ref in subproblem.required_input_refs
        ],
    })
    route = {
        "backend_id": "deterministic_subproblem_merge",
        "backend_version": "1.0",
        "problem_kind": "bounded_multiobjective",
        "input_digest": hashlib.sha256(
            json.dumps(
                {
                    "plan": plan.fingerprint,
                    "child_certificates": child_certificate_refs,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "required_input_refs": required_refs,
        "deterministic_settings": {
            "deterministic_seed": deterministic_seed,
            "search_limit": search_limit,
            "max_scenarios": max_scenarios,
        },
        "solver_config": SolverConfig(
            deterministic_seed=deterministic_seed,
            search_limit=search_limit,
            max_scenarios=max_scenarios,
            objective_definitions=list(objective_definitions),
            backend_version="1.0",
        ).model_dump(mode="json"),
    }
    bounded = total > materialization_limit
    status = (
        "unknown"
        if blocking_subproblems
        else ("bounded" if bounded else "feasible")
    )
    if status == "bounded":
        output = [
            PlanningScenario.model_validate(
                {
                    **item.model_dump(mode="json"),
                    "status": "partial",
                    "fingerprint": "",
                }
            )
            if item.status == "complete"
            else item
            for item in output
        ]
        feasible_ids = []
        recommended_id = ""
    certificate = _build_solver_certificate(
        problem=problem,
        model_digest=route["input_digest"],
        deterministic_seed=deterministic_seed,
        search_limit=search_limit,
        status=status,
        termination_reason=(
            "one or more typed solver subproblems are blocked; target alternatives are provisional"
            if blocking_subproblems
            else (
                f"SUBPROBLEM_PRODUCT_BOUND: evaluated {len(output)} of {total} combinations"
                if bounded
                else "all formal subproblem combinations merged"
            )
        ),
        combinations_inspected=len(output),
        feasible_scenario_count=len(feasible_ids),
        backend_route=route,
        solver_invoked=bool(child_sets),
        input_closed=not bool(blocking_subproblems),
        enumeration_complete=not blocking_subproblems and not bounded,
        selected_candidate_ids=(
            {
                item.target_id: list(item.candidate_ids)
                for item in output[0].target_selections
            }
            if recommended_id
            else {}
        ),
    )
    return ScenarioSet(
        set_id=set_id,
        problem_fingerprint=problem.fingerprint,
        baseline_ref=baseline_ref or problem.baseline_ref,
        scenarios=output,
        feasible_scenario_ids=feasible_ids,
        pareto_scenario_ids=feasible_ids,
        recommended_scenario_id=recommended_id,
        recommendation_policy="deterministic_subproblem_merge",
        objective_definitions=list(objective_definitions),
        objective_vectors=vectors,
        solver_certificate=certificate,
        infeasibility_explanations=(
            [
                "SOLVER_SUBPROBLEM_BLOCKED: target alternatives retained provisionally",
                *[item.subproblem_id for item in blocking_subproblems],
            ]
            if blocking_subproblems
            else []
        ),
    )


def optimize_solver_subproblems(
    problem: GroundedPlanningProblem,
    *,
    set_id: str,
    evaluator_context: RelationEvaluationContext,
    baseline_ref: str = "",
    max_scenarios: int = 8,
    search_limit: int = 20_000,
    deterministic_seed: int = 0,
    objective_definitions: Sequence[ObjectiveDefinition] | None = None,
    readiness: SolverReadiness | None = None,
) -> ScenarioSet:
    """Solve ready target subproblems and merge their formal alternatives."""

    definitions = _canonical_objective_definitions(objective_definitions)
    plan = compile_solver_subproblems(problem, readiness=readiness)
    if not plan.subproblems:
        return _unsupported_composition(
            problem,
            set_id=set_id,
            baseline_ref=baseline_ref,
            evaluator_context=evaluator_context,
            reason_codes=["NO_SOLVER_SUBPROBLEMS"],
            required_input_refs=[plan.fingerprint],
            objective_definitions=definitions,
            deterministic_seed=deterministic_seed,
            search_limit=search_limit,
            max_scenarios=max_scenarios,
        )
    topology = [item for item in plan.subproblems if item.problem_kind == "topology_layout"]
    if topology:
        return optimize_scenarios(
            problem,
            set_id=set_id,
            evaluator_context=evaluator_context,
            baseline_ref=baseline_ref or problem.baseline_ref,
            max_scenarios=max_scenarios,
            search_limit=search_limit,
            deterministic_seed=deterministic_seed,
            objective_definitions=definitions,
        )
    blocked = [
        item
        for item in plan.subproblems
        if item.status != "ready" and item.problem_kind != "topology_layout"
    ]
    target_subproblems = [
        item
        for item in plan.subproblems
        if item.problem_kind != "topology_layout"
    ]
    resource_conflicts = _cross_subproblem_resource_conflicts(
        problem,
        target_subproblems,
    )
    if resource_conflicts:
        conflict_refs = [
            f"resource:{ref}:targets:{','.join(target_ids)}"
            for ref, target_ids in resource_conflicts
        ]
        return _unsupported_composition(
            problem,
            set_id=set_id,
            baseline_ref=baseline_ref,
            evaluator_context=evaluator_context,
            reason_codes=[
            "CROSS_SOLVER_KIND_RESOURCE_COORDINATION_REQUIRED",
                *conflict_refs,
            ],
            required_input_refs=[plan.fingerprint, *conflict_refs],
            objective_definitions=definitions,
            deterministic_seed=deterministic_seed,
            search_limit=search_limit,
            max_scenarios=max_scenarios,
        )
    blockers: list[Any] = [*blocked, *topology]
    child_sets: list[ScenarioSet] = []
    infeasible_children: list[tuple[Any, ScenarioSet]] = []
    for subproblem in target_subproblems:
        if subproblem.status != "ready":
            continue
        child_problem = _slice_problem(problem, subproblem)
        child_set = optimize_scenarios(
            child_problem,
            set_id=f"{set_id}:{subproblem.subproblem_id}",
            evaluator_context=evaluator_context,
            baseline_ref=baseline_ref or problem.baseline_ref,
            max_scenarios=search_limit,
            search_limit=search_limit,
            deterministic_seed=deterministic_seed,
            objective_definitions=definitions,
        )
        if not child_set.feasible:
            if child_set.scenarios and child_set.solver_certificate.status in {"bounded", "unknown"}:
                child_sets.append(child_set)
                continue
            if child_set.solver_certificate.status == "infeasible":
                infeasible_children.append((subproblem, child_set))
            else:
                blockers.append(subproblem)
            continue
        child_sets.append(child_set)
    if infeasible_children:
        # A child can be formally infeasible only for its own closed slice.
        # Until the parent model is closed, do not promote that local result
        # to a global infeasibility claim; retain the evidence on an unknown
        # route and let the missing parent inputs be resolved first.
        if not problem.can_solve:
            return _unsupported_composition(
                problem,
                set_id=set_id,
                baseline_ref=baseline_ref,
                evaluator_context=evaluator_context,
                reason_codes=[
                    "SUBPROBLEM_INFEASIBLE_WITH_INCOMPLETE_PARENT",
                    *[
                        f"{subproblem.subproblem_id}:{explanation}"
                        for subproblem, child_set in infeasible_children
                        for explanation in child_set.infeasibility_explanations
                    ],
                ],
                required_input_refs=[
                    plan.fingerprint,
                    *[
                        ref
                        for subproblem, _child_set in infeasible_children
                        for ref in subproblem.required_input_refs
                    ],
                ],
                objective_definitions=definitions,
                deterministic_seed=deterministic_seed,
                search_limit=search_limit,
                max_scenarios=max_scenarios,
            )
        return _infeasible_composition(
            problem,
            set_id=set_id,
            baseline_ref=baseline_ref,
            child_sets=[child_set for _subproblem, child_set in infeasible_children],
            reason_codes=[
                "SUBPROBLEM_INFEASIBLE",
                *[
                    f"{subproblem.subproblem_id}:{explanation}"
                    for subproblem, child_set in infeasible_children
                    for explanation in child_set.infeasibility_explanations
                ],
            ],
            required_input_refs=[
                plan.fingerprint,
                *[
                    ref
                    for subproblem, _child_set in infeasible_children
                    for ref in subproblem.required_input_refs
                ],
            ],
            objective_definitions=definitions,
            deterministic_seed=deterministic_seed,
            search_limit=search_limit,
            max_scenarios=max_scenarios,
        )
    if blockers and child_sets:
        try:
            return _merge_scenario_sets(
                problem,
                child_sets,
                plan=plan,
                set_id=set_id,
                baseline_ref=baseline_ref,
                objective_definitions=definitions,
                deterministic_seed=deterministic_seed,
                search_limit=search_limit,
                max_scenarios=max_scenarios,
                blocking_subproblems=blockers,
            )
        except ValueError as exc:
            return _unsupported_composition(
                problem,
                set_id=set_id,
                baseline_ref=baseline_ref,
                evaluator_context=evaluator_context,
                reason_codes=["SUBPROBLEM_MERGE_FAILED", str(exc)],
                required_input_refs=[plan.fingerprint],
                objective_definitions=definitions,
                deterministic_seed=deterministic_seed,
                search_limit=search_limit,
                max_scenarios=max_scenarios,
            )
    if not child_sets:
        reasons = [
            "SOLVER_SUBPROBLEM_BLOCKED",
            *[
                diagnostic
                for item in blockers
                for diagnostic in item.diagnostics
            ],
        ]
        return _unsupported_composition(
            problem,
            set_id=set_id,
            baseline_ref=baseline_ref,
            evaluator_context=evaluator_context,
            reason_codes=[reason for reason in reasons if reason],
            required_input_refs=[
                plan.fingerprint,
                *[ref for item in blockers for ref in item.required_input_refs],
            ],
            objective_definitions=definitions,
            deterministic_seed=deterministic_seed,
            search_limit=search_limit,
            max_scenarios=max_scenarios,
        )
    try:
        return _merge_scenario_sets(
            problem,
            child_sets,
            plan=plan,
            set_id=set_id,
            baseline_ref=baseline_ref,
            objective_definitions=definitions,
            deterministic_seed=deterministic_seed,
            search_limit=search_limit,
            max_scenarios=max_scenarios,
            blocking_subproblems=blockers,
        )
    except ValueError as exc:
        return _unsupported_composition(
            problem,
            set_id=set_id,
            baseline_ref=baseline_ref,
            evaluator_context=evaluator_context,
            reason_codes=["SUBPROBLEM_MERGE_FAILED", str(exc)],
            required_input_refs=[plan.fingerprint],
            objective_definitions=definitions,
            deterministic_seed=deterministic_seed,
            search_limit=search_limit,
            max_scenarios=max_scenarios,
        )


__all__ = ["optimize_solver_subproblems"]
