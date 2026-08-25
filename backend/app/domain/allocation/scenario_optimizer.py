"""Authoritative multi-scenario SELECT optimizer over a closed problem.

This module owns the planning product: bounded enumeration, objective
vectors, Pareto filtering, recommendation policy and the SolverCertificate.
It never creates geometry or changes candidate membership.  Shared candidate
and relation-search primitives live in ``scenario_solver`` as private helpers;
there is no public single-scenario solver entry point.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, Callable

from app.contracts.planning.scenario import (
    BackendCertificatePayload,
    ObjectiveDefinition,
    PlanningScenario,
    ScenarioFinding,
    ScenarioSet,
    ScenarioTargetSelection,
    SolverConflictGroup,
    SolverCertificate,
    derive_backend_selection_digest,
    derive_solver_model_digest,
)
from app.contracts.spatial.grounded_problem import GroundedPlanningProblem
from app.domain.relations.service import RelationEvaluationContext
from app.domain.network.snapshot import network_readiness

from .scenario_builder import build_planning_scenario, build_scenario_features
from .scenario_solver import (
    _SEARCH_LIMIT,
    _bounded_choice_product,
    _candidate_score,
    _candidate_is_selectable,
    _choices_with_diagnostics,
    _evaluate_assignment,
    _finding,
    _prune_spatial_conflicts,
)
from .network_subproblem import derive_network_cuts
from .relation_terms import hard_relation_blocked, relation_objective


def _scenario_id(set_id: str, selected: dict[str, tuple[str, ...]]) -> str:
    raw = json.dumps(
        {key: list(value) for key, value in sorted(selected.items())},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{set_id}:scenario:{digest}"


_DEFAULT_OBJECTIVE_DEFINITIONS = (
    ObjectiveDefinition(
        objective_id="relation_satisfaction",
        evaluator_key="relation_satisfaction",
        description="hard/soft relation satisfaction",
    ),
    ObjectiveDefinition(
        objective_id="candidate_suitability",
        evaluator_key="candidate_suitability",
        description="grounded candidate suitability",
    ),
    ObjectiveDefinition(
        objective_id="hard_constraint_coverage",
        evaluator_key="hard_constraint_coverage",
        description="hard relation coverage",
    ),
)


def _canonical_objective_definitions(
    definitions: Sequence[ObjectiveDefinition] | None,
) -> tuple[ObjectiveDefinition, ...]:
    selected = list(
        _DEFAULT_OBJECTIVE_DEFINITIONS if definitions is None else definitions
    )
    ids = [item.objective_id for item in selected]
    if len(ids) != len(set(ids)):
        raise ValueError("objective definitions must have unique objective IDs")
    return tuple(selected)


def _digest_objective_definitions(
    definitions: Sequence[ObjectiveDefinition],
) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in definitions]


def _choice_model_payload(problem: GroundedPlanningProblem) -> list[dict[str, Any]]:
    """Return the closed selection semantics included in the model digest."""
    return [
        {
            "target_id": domain.target_id,
            "candidate_ids": sorted(domain.candidate_ids),
            "selection_mode": domain.selection_mode,
            "min_selected": domain.min_selected,
            "max_selected": domain.max_selected,
        }
        for domain in sorted(problem.candidate_domains, key=lambda item: item.target_id)
    ]


def _grounding_explanations(problem: GroundedPlanningProblem) -> list[str]:
    completeness = problem.candidate_completeness
    explanations = list(completeness.reasons)
    for label, target_ids in (
        ("missing candidate target", completeness.missing_candidate_target_ids),
        ("missing geometry target", completeness.missing_geometry_target_ids),
        ("unresolved target", completeness.unresolved_target_ids),
        ("candidate-only target", completeness.candidate_only_target_ids),
        ("ambiguous candidate target", completeness.ambiguous_target_ids),
        ("degraded geometry target", completeness.degraded_geometry_target_ids),
    ):
        explanations.extend(f"{label}: {target_id}" for target_id in target_ids)
    return list(dict.fromkeys(explanations))


def _solver_assumption_groups(
    problem: GroundedPlanningProblem,
    *,
    explanation: str,
) -> tuple[list[str], list[SolverConflictGroup]]:
    """Build replayable typed assumptions for a complete-model proof.

    These are deliberately derived from the closed GROUND model rather than
    from diagnostic text.  A backend may return a sufficient core (not
    necessarily a minimal core), but every member must still be a real model
    reference that an independent verifier can replay.
    """

    groups: list[SolverConflictGroup] = []
    for domain in sorted(problem.candidate_domains, key=lambda item: item.target_id):
        refs = [
            f"target:{domain.target_id}",
            *list(domain.candidate_geometry_refs),
            *list(domain.candidate_ids),
        ]
        groups.append(SolverConflictGroup(
            group_id=f"selection_domain:{domain.target_id}",
            assumption_refs=refs,
            explanation=(
                f"the complete candidate domain for {domain.target_id} was exhausted"
            ),
        ))
    for factor in sorted(
        problem.constraint_factors,
        key=lambda item: str(getattr(item, "factor_id", "")),
    ):
        factor_id = str(getattr(factor, "factor_id", "") or "").strip()
        if not factor_id:
            continue
        groups.append(SolverConflictGroup(
            group_id=f"constraint:{factor_id}",
            assumption_refs=[
                factor_id,
                *list(getattr(factor, "evidence_refs", None) or []),
            ],
            explanation=(
                f"constraint {factor_id} rejected every enumerated assignment"
            ),
        ))
    pool = getattr(problem, "parcel_resource_pool", None)
    if pool is not None:
        pool_refs = [str(getattr(pool, "pool_id", "") or "").strip()]
        pool_refs.extend(
            str(getattr(resource, field, "") or "").strip()
            for resource in list(getattr(pool, "resources", None) or [])
            for field in ("resource_id", "bsm", "geometry_ref")
        )
        groups.append(SolverConflictGroup(
            group_id=f"resource_pool:{pool.pool_id}",
            assumption_refs=pool_refs,
            explanation="shared resource capacity rejected every enumerated assignment",
        ))
    groups = [
        group
        for group in groups
        if group.assumption_refs
    ]
    assumptions = sorted({
        ref
        for group in groups
        for ref in group.assumption_refs
        if str(ref).strip()
    })
    if not groups:
        fallback = f"model:{problem.fingerprint}"
        assumptions = [fallback]
        groups = [SolverConflictGroup(
            group_id="complete_model",
            assumption_refs=[fallback],
            explanation=explanation or "the complete typed model has no feasible assignment",
        )]
    return assumptions, groups


def _selection_domain_is_uncertain(problem: GroundedPlanningProblem) -> bool:
    """Detect candidate rows that are not closed enough for an unsat claim."""

    geometries = {
        item.candidate_id: item
        for item in problem.candidate_geometries
    }
    for domain in problem.candidate_domains:
        candidates = [
            geometries[candidate_id]
            for candidate_id in domain.candidate_ids
            if candidate_id in geometries
        ]
        if not candidates or any(_candidate_is_selectable(item) for item in candidates):
            continue
        for candidate in candidates:
            hard_status = str(
                getattr(candidate, "hard_constraint_status", "pending")
                or "pending"
            )
            if hard_status in {"pending", "deferred", "unknown"}:
                return True
            if not bool(getattr(candidate, "is_executable", False)):
                return True
            if str(getattr(candidate, "role", "") or "") == "scope_geometry":
                return True
            if str(getattr(candidate, "uncertainty_reason", "") or "").strip():
                return True
    return False


def _recommendation_policy(
    definitions: Sequence[ObjectiveDefinition],
) -> str:
    if not definitions:
        return "lexicographic:none"
    return "lexicographic:" + ",".join(
        f"{item.objective_id}:{item.direction}" for item in definitions
    )


def _network_path_input_closed(
    problem: GroundedPlanningProblem,
    view: object,
    evaluator_context: RelationEvaluationContext,
) -> bool:
    if str(getattr(view, "problem_kind", "")) != "network_path":
        return False
    if not bool(getattr(view, "input_complete", False)):
        return False
    network_refs = {
        str(ref).strip()
        for ref in (getattr(problem, "network_refs", None) or ())
        if str(ref).strip()
    }
    networks = getattr(evaluator_context, "networks", None) or {}
    return bool(network_refs) and all(
        network_readiness(networks.get(ref), ref)[0] == "ready"
        for ref in sorted(network_refs)
    )


def _objective_rank(
    vector: dict[str, float],
    definitions: Sequence[ObjectiveDefinition],
) -> tuple[float, ...]:
    """Return descending normalized values for deterministic lexicographic ranking."""

    return tuple(
        -(
            vector[definition.objective_id]
            if definition.direction == "maximize"
            else -vector[definition.objective_id]
        )
        if definition.objective_id in vector
        else float("inf")
        for definition in definitions
    )


def _objective_vector(
    problem: GroundedPlanningProblem,
    selected: dict[str, tuple[str, ...]],
    satisfactions: list[Any],
    candidates: dict[str, Any],
    objective_definitions: Sequence[ObjectiveDefinition] | None = None,
) -> dict[str, float]:
    selected_ids = [candidate_id for ids in selected.values() for candidate_id in ids]
    candidate_values = [
        _candidate_score(candidates[candidate_id])
        for candidate_id in selected_ids
        if candidate_id in candidates
    ]
    hard_total = sum(
        1
        for item in satisfactions
        if str(getattr(item, "criticality", "") or "") == "hard"
    )
    hard_satisfied = sum(
        1
        for item in satisfactions
        if str(getattr(item, "criticality", "") or "") == "hard"
        and str(getattr(item, "status", "") or "") == "satisfied"
    )
    values = {
        "relation_satisfaction": relation_objective(problem.constraint_factors, satisfactions),
        "candidate_suitability": sum(candidate_values),
        "hard_constraint_coverage": (
            hard_satisfied / hard_total if hard_total else 1.0
        ),
    }
    definitions = _canonical_objective_definitions(objective_definitions)
    return {
        definition.objective_id: values[key]
        for definition in definitions
        for key in [definition.evaluator_key or definition.objective_id]
        if key in values
    }


def _make_scenario(
    problem: GroundedPlanningProblem,
    selected: dict[str, tuple[str, ...]],
    *,
    scenario_id: str,
    evaluator_context: RelationEvaluationContext,
    unavailable: list[str],
    inspected: int,
    spatial_conflicts: list[tuple[str, str, str]],
    objective_definitions: Sequence[ObjectiveDefinition],
    grounding_complete_override: bool = False,
) -> tuple[PlanningScenario, dict[str, float], bool, bool]:
    candidates = {item.candidate_id: item for item in problem.candidate_geometries}
    features, satisfactions = _evaluate_assignment(
        problem,
        selected,
        scenario_id=scenario_id,
        evaluator_context=evaluator_context,
    )
    hard_violated = any(
        item.criticality == "hard" and item.status == "violated"
        for item in satisfactions
    )
    hard_relation_uncertain = any(
        item.criticality == "hard"
        and item.status in {"pending", "deferred", "not_evaluable", "unknown"}
        for item in satisfactions
    )
    hard_unresolved = any(hard_relation_blocked(item) for item in satisfactions)
    objective_vector = _objective_vector(
        problem,
        selected,
        satisfactions,
        candidates,
        objective_definitions,
    )
    findings: list[ScenarioFinding] = [
        _finding(
            "NO_PLANNING_OUTPUT",
            "Target has no executable candidate geometry and was deferred.",
            severity="warning",
            target_id=target,
        )
        for target in unavailable
    ]
    findings.extend(
        _finding(
            "SPATIAL_CANDIDATE_CONFLICT",
            f"Candidate overlaps exclusive target {conflict_target}; target deferred.",
            severity="warning",
            target_id=target_id,
        )
        for target_id, _candidate_id, conflict_target in spatial_conflicts
    )
    findings.extend(
        _finding(
            "HARD_RELATION_UNRESOLVED",
            f"Hard relation is {item.status}; scenario remains provisional.",
            severity="warning",
            relation_id=item.relation_id,
        )
        for item in satisfactions
        if item.criticality == "hard" and item.status != "satisfied"
    )
    if not problem.can_solve and not grounding_complete_override:
        grounding_targets = sorted({
            *problem.candidate_completeness.missing_candidate_target_ids,
            *problem.candidate_completeness.missing_geometry_target_ids,
            *problem.candidate_completeness.unresolved_target_ids,
            *problem.candidate_completeness.candidate_only_target_ids,
            *problem.candidate_completeness.ambiguous_target_ids,
            *problem.candidate_completeness.degraded_geometry_target_ids,
        })
        findings.extend(
            _finding(
                "GROUNDING_INCOMPLETE",
                (
                    f"{reason} (target: {target_id})"
                    if target_id
                    else reason
                ),
                severity="warning",
                target_id=target_id,
            )
            for reason in problem.candidate_completeness.reasons
            for target_id in (grounding_targets or [""])
        )
    missing_objectives = [
        definition.objective_id
        for definition in objective_definitions
        if definition.objective_id not in objective_vector
    ]
    findings.extend(
        _finding(
            "OBJECTIVE_RESULT_MISSING",
            f"Declared objective {objective_id} has no evaluator result.",
            severity="warning",
        )
        for objective_id in missing_objectives
    )
    domain_by_target = {item.target_id: item for item in problem.candidate_domains}
    target_selections = [
        ScenarioTargetSelection(
            target_id=target_id,
            selection_mode=domain_by_target[target_id].selection_mode,
            candidate_ids=list(candidate_ids),
            binding_ref=domain_by_target[target_id].binding_ref,
        )
        for target_id, candidate_ids in sorted(selected.items())
        if target_id in domain_by_target and candidate_ids
    ]
    status = (
        "complete"
        if (problem.can_solve or grounding_complete_override)
        and not unavailable
        and not spatial_conflicts
        and not hard_unresolved
        and not hard_violated
        and not missing_objectives
        else "partial"
    )
    scenario = build_planning_scenario(
        scenario_id=scenario_id,
        problem=problem,
        target_selections=target_selections,
        relation_satisfactions=satisfactions,
        features=features,
        findings=findings,
        metrics={
            "candidate_combinations_inspected": float(inspected),
            "selected_candidate_count": float(len(selected)),
            "selected_target_count": float(len(selected)),
            "relation_objective": objective_vector.get(
                "relation_satisfaction",
                relation_objective(problem.constraint_factors, satisfactions),
            ),
        },
        objective_vector=objective_vector,
        status=status,
    )
    cuts = derive_network_cuts(scenario, problem)
    if cuts:
        scenario_findings = [
            *scenario.findings,
            *(
                _finding(
                    "NETWORK_CUT_REQUIRED",
                    f"Network subproblem emitted cut {cut.cut_id}: {cut.reason}",
                    severity="warning",
                    relation_id=cut.relation_id,
                )
                for cut in cuts
            ),
        ]
        scenario_payload = scenario.model_dump(mode="json")
        scenario_payload["findings"] = scenario_findings
        scenario_payload["metrics"] = {
            **scenario.metrics,
            "network_cut_count": float(len(cuts)),
        }
        # Network cuts are appended after the initial scenario construction;
        # rebuild the contract so its fingerprint covers the final findings
        # and metrics instead of leaving a stale canonical digest.
        scenario_payload["fingerprint"] = ""
        scenario = PlanningScenario.model_validate(scenario_payload)
    return (
        scenario,
        objective_vector,
        status == "complete",
        hard_relation_uncertain or bool(missing_objectives),
    )


def _dominates(
    left: dict[str, float],
    right: dict[str, float],
    objective_definitions: Sequence[ObjectiveDefinition] | None = None,
) -> bool:
    if objective_definitions is None:
        objective_definitions = [
            ObjectiveDefinition(objective_id=key)
            for key in sorted(set(left).union(right))
        ]
    definitions = _canonical_objective_definitions(objective_definitions)
    if not definitions or any(
        definition.objective_id not in left or definition.objective_id not in right
        for definition in definitions
    ):
        return False
    normalized_left = {
        definition.objective_id: (
            left[definition.objective_id]
            if definition.direction == "maximize"
            else -left[definition.objective_id]
        )
        for definition in definitions
    }
    normalized_right = {
        definition.objective_id: (
            right[definition.objective_id]
            if definition.direction == "maximize"
            else -right[definition.objective_id]
        )
        for definition in definitions
    }
    return all(
        normalized_left[key] >= normalized_right[key] for key in normalized_left
    ) and any(
        normalized_left[key] > normalized_right[key] for key in normalized_left
    )


def _pareto_ids(
    scenarios: list[PlanningScenario],
    vectors: dict[str, dict[str, float]],
    objective_definitions: Sequence[ObjectiveDefinition] | None = None,
) -> list[str]:
    feasible = [item for item in scenarios if item.status == "complete"]
    return sorted(
        item.scenario_id
        for item in feasible
        if not any(
            other.scenario_id != item.scenario_id
            and _dominates(
                vectors.get(other.scenario_id, {}),
                vectors.get(item.scenario_id, {}),
                objective_definitions,
            )
            for other in feasible
        )
    )


def _build_solver_certificate(
    *,
    problem: GroundedPlanningProblem,
    model_digest: str,
    deterministic_seed: int,
    search_limit: int,
    status: str,
    termination_reason: str,
    combinations_inspected: int = 0,
    feasible_scenario_count: int = 0,
    conflict_explanations: list[str] | None = None,
    backend_route: dict[str, Any] | None = None,
    selected_candidate_ids: dict[str, list[str]] | None = None,
    route_refs: list[str] | None = None,
    proof_kind: str | None = None,
    solver_invoked: bool = False,
    input_closed: bool = False,
    enumeration_complete: bool = False,
    assumption_refs: list[str] | None = None,
    infeasibility_core_refs: list[str] | None = None,
    conflict_groups: list[SolverConflictGroup] | None = None,
    master_certificate: object | None = None,
) -> SolverCertificate:
    payload: dict[str, Any] = {
        "problem_fingerprint": problem.fingerprint,
        "model_digest": model_digest,
        "solver_version": "scenario-optimizer-v1",
        "deterministic_seed": deterministic_seed,
        "search_limit": search_limit,
        "combinations_inspected": combinations_inspected,
        "feasible_scenario_count": feasible_scenario_count,
        "status": status,
        "termination_reason": termination_reason,
        "conflict_explanations": list(conflict_explanations or []),
        "solver_invoked": solver_invoked,
        "input_closed": input_closed,
        "enumeration_complete": enumeration_complete,
        "proof_kind": proof_kind or {
            "feasible": "feasible_witness",
            "bounded": "bounded_search",
            "infeasible": "infeasibility_core",
        }.get(status, "unknown"),
    }
    if master_certificate is not None:
        payload["master_certificate"] = master_certificate
    if backend_route:
        effective_proof_kind = proof_kind or {
            "feasible": "feasible_witness",
            "bounded": "bounded_search",
            "infeasible": "infeasibility_core",
        }.get(status, "unknown")
        effective_assumptions = list(assumption_refs or [])
        effective_core = list(infeasibility_core_refs or [])
        effective_groups = list(conflict_groups or [])
        if status == "infeasible":
            if not problem.can_solve:
                raise ValueError(
                    "an incomplete grounded problem cannot produce an infeasibility proof"
                )
            if not effective_assumptions or not effective_groups:
                effective_assumptions, effective_groups = _solver_assumption_groups(
                    problem,
                    explanation=termination_reason,
                )
            if not effective_core:
                effective_core = list(effective_assumptions)
        selected_ids = {
            str(target_id): sorted(set(candidate_ids))
            for target_id, candidate_ids in sorted(
                dict(selected_candidate_ids or {}).items()
            )
        }
        if status == "bounded":
            selected_ids = {}
        canonical_route_refs = sorted(set(route_refs or []))
        proof = BackendCertificatePayload(
            **backend_route,
            problem_fingerprint=problem.fingerprint,
            selected_candidate_ids=selected_ids,
            route_refs=canonical_route_refs,
            selection_digest=derive_backend_selection_digest(
                selected_ids,
                canonical_route_refs,
            ),
            status=status,
            termination_reason=termination_reason,
            proof_kind=effective_proof_kind,
            solver_invoked=solver_invoked,
            input_closed=input_closed,
            enumeration_complete=enumeration_complete,
            assumption_refs=effective_assumptions,
            infeasibility_core_refs=effective_core,
            conflict_groups=effective_groups,
        )
        payload.update(
            {
                "model_digest": derive_solver_model_digest(
                    proof,
                    deterministic_seed=deterministic_seed,
                    search_limit=search_limit,
                ),
                "solver_version": f"{proof.backend_id}:{proof.backend_version}",
                "problem_kind": proof.problem_kind,
                "backend_id": proof.backend_id,
                "backend_version": proof.backend_version,
                "required_input_refs": proof.required_input_refs,
                "backend_certificate": proof,
            }
        )
    return SolverCertificate(**payload)


def _optimize_scenarios_enumeration(
    problem: GroundedPlanningProblem,
    *,
    set_id: str,
    evaluator_context: RelationEvaluationContext,
    baseline_ref: str = "",
    max_scenarios: int = 8,
    search_limit: int = _SEARCH_LIMIT,
    deterministic_seed: int = 0,
    objective_definitions: Sequence[ObjectiveDefinition] | None = None,
    backend_route: dict[str, Any] | None = None,
    selection_validator: Callable[
        [dict[str, tuple[str, ...]], dict[str, Any]], tuple[bool, str]
    ] | None = None,
    grounding_complete_override: bool = False,
) -> ScenarioSet:
    """Generate a bounded ScenarioSet from one grounded problem."""

    if not set_id.strip():
        raise ValueError("set_id must be non-empty")
    if max_scenarios < 1:
        raise ValueError("max_scenarios must be >= 1")
    definitions = _canonical_objective_definitions(objective_definitions)
    # An incomplete GROUND problem may still have useful provisional rows for
    # review and partial delivery.  Enumerate those rows, but keep the
    # completeness gate authoritative: only complete rows become feasible or
    # recommended scenarios.
    grounding_incomplete = (
        (not problem.can_solve and not grounding_complete_override)
        or _selection_domain_is_uncertain(problem)
    )

    if search_limit < 1:
        raise ValueError("search_limit must be >= 1")
    targets, option_lists, unavailable, choice_errors = _choices_with_diagnostics(problem)
    if choice_errors or not targets or any(options.count == 0 for options in option_lists):
        reason = "NO_EXECUTABLE_CANDIDATE_GEOMETRY: no executable candidate geometry"
        if choice_errors:
            reason = "INVALID_SELECTION_DOMAIN: invalid candidate selection domain"
        model_payload = {
            "problem_fingerprint": problem.fingerprint,
            "objective_definitions": _digest_objective_definitions(definitions),
            "search_limit": search_limit,
            "max_scenarios": max_scenarios,
            "choice_domains": _choice_model_payload(problem),
        }
        model_digest = hashlib.sha256(
            json.dumps(
                model_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        certificate_status = "unknown" if grounding_incomplete else "infeasible"
        backend_id = str((backend_route or {}).get("backend_id", "") or "")
        solver_route_invoked = backend_id not in {
            "",
            "diagnostic_grounding_gate",
            "unresolved",
        }
        certificate = _build_solver_certificate(
            problem=problem,
            model_digest=model_digest,
            deterministic_seed=deterministic_seed,
            search_limit=search_limit,
            status=certificate_status,
            termination_reason=reason,
            conflict_explanations=[
                reason,
                *unavailable,
                *choice_errors,
                *_grounding_explanations(problem),
            ],
            backend_route=backend_route,
            solver_invoked=solver_route_invoked,
            input_closed=not grounding_incomplete,
            enumeration_complete=(
                not grounding_incomplete
                and certificate_status == "infeasible"
            ),
        )
        return ScenarioSet(
            set_id=set_id,
            problem_fingerprint=problem.fingerprint,
            baseline_ref=baseline_ref or problem.baseline_ref,
            recommendation_policy=_recommendation_policy(definitions),
            objective_definitions=list(definitions),
            solver_certificate=certificate,
            infeasibility_explanations=[
                reason,
                *unavailable,
                *choice_errors,
                *_grounding_explanations(problem),
            ],
        )

    candidates = {item.candidate_id: item for item in problem.candidate_geometries}
    rows: list[tuple[PlanningScenario, dict[str, float], bool, bool]] = []
    selection_rejections: list[str] = []
    inspected = 0
    total_combinations = 1
    for options in option_lists:
        total_combinations *= options.count
    bounded = total_combinations > search_limit
    for choice in _bounded_choice_product(option_lists, search_limit):
        inspected += 1
        selected, conflicts = _prune_spatial_conflicts(
            dict(zip(targets, choice)),
            candidates,
        )
        if not selected:
            continue
        if selection_validator is not None:
            accepted, rejection = selection_validator(selected, candidates)
            if not accepted:
                if rejection:
                    selection_rejections.append(str(rejection))
                continue
        scenario, vector, complete, relation_uncertain = _make_scenario(
            problem,
            selected,
            scenario_id=_scenario_id(set_id, selected),
            evaluator_context=evaluator_context,
            unavailable=unavailable,
            inspected=inspected,
            spatial_conflicts=conflicts,
            objective_definitions=definitions,
            grounding_complete_override=grounding_complete_override,
        )
        rows.append((scenario, vector, complete, relation_uncertain))

    ranked_rows = sorted(
        rows,
        key=lambda row: (
            not row[2],
            _objective_rank(row[1], definitions),
            row[0].scenario_id,
        ),
    )
    full_scenarios = [row[0] for row in rows]
    full_vectors = {row[0].scenario_id: row[1] for row in rows}
    full_feasible_ids = [
        scenario.scenario_id
        for scenario in full_scenarios
        if scenario.status == "complete"
    ]
    full_pareto_ids = _pareto_ids(full_scenarios, full_vectors, definitions)
    pareto_set = set(full_pareto_ids)
    pareto_rows = [row for row in ranked_rows if row[0].scenario_id in pareto_set]
    pareto_output_bounded = len(pareto_rows) > max_scenarios
    if pareto_output_bounded:
        # Never silently discard a non-dominated alternative.  max_scenarios is
        # an output preference, not permission to falsify the frontier.
        selected_rows = pareto_rows
    else:
        selected_rows = pareto_rows + [
            row
            for row in ranked_rows
            if row[0].scenario_id not in pareto_set
        ][: max(0, max_scenarios - len(pareto_rows))]
    output_truncated = len(selected_rows) < len(ranked_rows)
    scenarios = [row[0] for row in selected_rows]
    vectors = {row[0].scenario_id: row[1] for row in selected_rows}
    feasible_ids = [scenario.scenario_id for scenario in scenarios if scenario.status == "complete"]
    pareto_ids = [scenario_id for scenario_id in full_pareto_ids if scenario_id in set(feasible_ids)]
    recommended = next(
        (row[0].scenario_id for row in pareto_rows if row[0].scenario_id in set(feasible_ids)),
        feasible_ids[0] if feasible_ids else "",
    )
    conflict_explanations = sorted({
        finding.message
        for scenario in full_scenarios
        for finding in scenario.findings
        if finding.severity in {"warning", "error"}
    }.union(selection_rejections))
    if bounded:
        conflict_explanations.append(
            f"SEARCH_BOUND_REACHED: search bound reached; evaluated {inspected} of "
            f"{total_combinations} combinations"
        )
    if pareto_output_bounded:
        conflict_explanations.append(
            f"PARETO_OUTPUT_BOUND: pareto frontier exceeds max_scenarios={max_scenarios}; "
            f"returned all {len(pareto_rows)} non-dominated scenarios"
        )
    elif output_truncated:
        conflict_explanations.append(
            f"OUTPUT_SCENARIO_LIMIT: limited to max_scenarios={max_scenarios}; "
            f"non-Pareto alternatives omitted from returned set"
        )
    relation_uncertain = any(row[3] for row in rows)
    status = (
        "unknown"
        if grounding_incomplete or (relation_uncertain and not feasible_ids)
        else (
            "bounded"
            if bounded or pareto_output_bounded or output_truncated
            else ("feasible" if feasible_ids else "infeasible")
        )
    )
    if status == "bounded":
        # A bounded search is provisional evidence only; it cannot expose
        # formal feasible, Pareto, or recommended scenario IDs.
        feasible_ids = []
        pareto_ids = []
        recommended = ""
        scenarios = [
            PlanningScenario.model_validate(
                {
                    **item.model_dump(mode="json"),
                    "status": "partial",
                    "fingerprint": "",
                }
            )
            if item.status == "complete"
            else item
            for item in scenarios
        ]
    model_payload = {
        "problem_fingerprint": problem.fingerprint,
        "objective_definitions": _digest_objective_definitions(definitions),
        "evaluator_version": str(getattr(evaluator_context, "evaluator_version", "") or ""),
        "search_limit": search_limit,
        "max_scenarios": max_scenarios,
        "choice_domains": _choice_model_payload(problem),
    }
    model_digest = hashlib.sha256(
        json.dumps(model_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    termination_reason = (
        (
            f"SEARCH_BOUND_REACHED: search bound reached after {inspected} of "
            f"{total_combinations} combinations"
            if bounded
            else ""
        )
        + (
            "; Pareto frontier exceeds output budget (PARETO_OUTPUT_BOUND)"
            if pareto_output_bounded
            else ""
        )
        + (
            "; scenario output limited (OUTPUT_SCENARIO_LIMIT)"
            if output_truncated and not pareto_output_bounded
            else ""
        )
        or (
            "grounding completeness gate did not pass; provisional scenarios only"
            if grounding_incomplete and not feasible_ids
            else (
                "hard relation evaluation remained deferred or not evaluable"
                if relation_uncertain and not feasible_ids
                else (
                    "at least one hard-feasible scenario"
                    if feasible_ids
                    else "all combinations infeasible"
                )
            )
        )
    )
    certificate = _build_solver_certificate(
        problem=problem,
        model_digest=model_digest,
        deterministic_seed=deterministic_seed,
        search_limit=search_limit,
        combinations_inspected=inspected,
        feasible_scenario_count=len(feasible_ids),
        status=status,
        termination_reason=termination_reason,
        conflict_explanations=conflict_explanations,
        backend_route=backend_route,
        solver_invoked=str((backend_route or {}).get("backend_id", "") or "")
        not in {"", "diagnostic_grounding_gate", "unresolved"},
        input_closed=not grounding_incomplete,
        enumeration_complete=(
            not grounding_incomplete
            and not relation_uncertain
            and not (bounded or pareto_output_bounded or output_truncated)
        ),
        selected_candidate_ids=(
            {
                selection.target_id: list(selection.candidate_ids)
                for scenario in scenarios
                if scenario.scenario_id == recommended
                for selection in scenario.target_selections
            }
            if recommended
            else {}
        ),
    )
    return ScenarioSet(
        set_id=set_id,
        problem_fingerprint=problem.fingerprint,
        baseline_ref=baseline_ref or problem.baseline_ref,
        scenarios=scenarios,
        feasible_scenario_ids=feasible_ids,
        pareto_scenario_ids=pareto_ids,
        recommended_scenario_id=recommended,
        recommendation_policy=_recommendation_policy(definitions),
        objective_definitions=list(definitions),
        objective_vectors=vectors,
        infeasibility_explanations=(
            list(dict.fromkeys([
                *_grounding_explanations(problem),
                *conflict_explanations,
            ]))
            if not feasible_ids
            else []
        ),
        solver_certificate=certificate,
    )


def _attach_route_trace(
    scenario_set: ScenarioSet,
    *,
    problem_kind: str,
    backend_id: str = "",
    backend_version: str = "",
    required_input_refs: list[str] | None = None,
    backend_certificate: dict[str, object] | None = None,
) -> ScenarioSet:
    certificate_payload = scenario_set.solver_certificate.model_dump(mode="json")
    certificate_payload.update(
        {
            "problem_kind": problem_kind,
            "backend_id": backend_id,
            "backend_version": backend_version,
            "required_input_refs": list(required_input_refs or []),
            "backend_certificate": backend_certificate,
            "fingerprint": "",
        }
    )
    certificate = SolverCertificate(**certificate_payload)
    scenario_payload = scenario_set.model_dump(mode="json")
    scenario_payload.update({"solver_certificate": certificate, "fingerprint": ""})
    return ScenarioSet(**scenario_payload)


def _unsupported_backend_result(
    problem: GroundedPlanningProblem,
    *,
    set_id: str,
    baseline_ref: str,
    view: Any,
    reason_codes: list[str],
    required_input_refs: list[str],
    objective_definitions: Sequence[ObjectiveDefinition],
    deterministic_seed: int,
    search_limit: int,
    max_scenarios: int,
) -> ScenarioSet:
    reason = "UNSUPPORTED_SOLVER_KIND: " + ", ".join(sorted(set(reason_codes)))
    model_payload = {
        "problem_fingerprint": problem.fingerprint,
        "problem_kind": view.problem_kind,
        "backend_id": "unresolved",
        "search_limit": search_limit,
    }
    model_digest = hashlib.sha256(
        json.dumps(model_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    from app.contracts.planning.solver import SolverConfig, backend_input_digest

    config = SolverConfig(
        deterministic_seed=deterministic_seed,
        search_limit=search_limit,
        max_scenarios=max_scenarios,
        objective_definitions=list(objective_definitions),
        backend_version="1.0",
    )
    certificate = _build_solver_certificate(
        problem=problem,
        model_digest=model_digest,
        deterministic_seed=deterministic_seed,
        search_limit=search_limit,
        status="unknown",
        termination_reason=reason,
        conflict_explanations=[reason],
        backend_route={
            "backend_id": "unresolved",
            "backend_version": "1.0",
            "problem_kind": view.problem_kind,
            "input_digest": backend_input_digest(view, config),
            "required_input_refs": required_input_refs,
            "deterministic_settings": {
                "deterministic_seed": deterministic_seed,
                "search_limit": search_limit,
                "max_scenarios": max_scenarios,
            },
            "solver_config": config.model_dump(mode="json"),
        },
    )
    return ScenarioSet(
        set_id=set_id,
        problem_fingerprint=problem.fingerprint,
        baseline_ref=baseline_ref or problem.baseline_ref,
        recommendation_policy=_recommendation_policy(objective_definitions),
        objective_definitions=list(objective_definitions),
        infeasibility_explanations=[reason],
        solver_certificate=certificate,
    )


def optimize_scenarios(
    problem: GroundedPlanningProblem,
    *,
    set_id: str,
    evaluator_context: RelationEvaluationContext,
    baseline_ref: str = "",
    max_scenarios: int = 8,
    search_limit: int = _SEARCH_LIMIT,
    deterministic_seed: int = 0,
    objective_definitions: Sequence[ObjectiveDefinition] | None = None,
) -> ScenarioSet:
    """The sole ScenarioOptimizer facade and solver-portfolio caller."""

    from .solver_portfolio import build_solver_problem_view, default_solver_registry
    from app.contracts.planning.solver import SolverConfig, backend_input_digest

    view = build_solver_problem_view(problem, evaluator_context=evaluator_context)
    definitions = _canonical_objective_definitions(objective_definitions)
    network_input_closed = _network_path_input_closed(
        problem,
        view,
        evaluator_context,
    )
    # Specialized routes require their typed input before any enumeration.
    # Never turn an incomplete network/coverage/parcel/topology problem into
    # provisional independent choices: that would produce a misleading plan.
    if not problem.can_solve and not network_input_closed:
        if view.problem_kind in {
            "coverage",
            "parcel_assignment",
            "network_path",
            "topology_layout",
        }:
            return _unsupported_backend_result(
                problem,
                set_id=set_id,
                baseline_ref=baseline_ref,
                view=view,
                reason_codes=[
                    "GROUNDING_INCOMPLETE",
                    "SOLVER_INPUT_INCOMPLETE",
                    *list(view.missing_input_refs),
                ],
                required_input_refs=list(view.required_input_refs),
                objective_definitions=definitions,
                deterministic_seed=deterministic_seed,
                search_limit=search_limit,
                max_scenarios=max_scenarios,
            )
        diagnostic_config = SolverConfig(
            deterministic_seed=deterministic_seed,
            search_limit=search_limit,
            max_scenarios=max_scenarios,
            objective_definitions=list(definitions),
            backend_version="1.0",
        )
        provisional = _optimize_scenarios_enumeration(
            problem,
            set_id=set_id,
            evaluator_context=evaluator_context,
            baseline_ref=baseline_ref,
            max_scenarios=max_scenarios,
            search_limit=search_limit,
            deterministic_seed=deterministic_seed,
            objective_definitions=objective_definitions,
            backend_route={
                "backend_id": "diagnostic_grounding_gate",
                "backend_version": "1.0",
                "problem_kind": view.problem_kind,
                "input_digest": backend_input_digest(view, diagnostic_config),
                "required_input_refs": list(view.required_input_refs),
                "deterministic_settings": {
                    "deterministic_seed": deterministic_seed,
                    "search_limit": search_limit,
                    "max_scenarios": max_scenarios,
                },
                "solver_config": diagnostic_config.model_dump(mode="json"),
            },
        )
        return provisional

    registry = default_solver_registry()
    resolution = registry.resolve(problem, view)
    if resolution.backend is None:
        return _unsupported_backend_result(
            problem,
            set_id=set_id,
            baseline_ref=baseline_ref,
            view=view,
            reason_codes=resolution.support.reason_codes,
            required_input_refs=list(view.required_input_refs),
            objective_definitions=definitions,
            deterministic_seed=deterministic_seed,
            search_limit=search_limit,
            max_scenarios=max_scenarios,
        )

    result = resolution.backend.solve(
        problem,
        view,
        config=SolverConfig(
            deterministic_seed=deterministic_seed,
            search_limit=search_limit,
            max_scenarios=max_scenarios,
            objective_definitions=list(definitions),
        ),
        evaluator_context=evaluator_context,
        set_id=set_id,
        baseline_ref=baseline_ref,
    )
    if result.scenario_set is None:
        raise ValueError("solver backend returned no ScenarioSet")
    return _attach_route_trace(
        result.scenario_set,
        problem_kind=view.problem_kind,
        backend_id=resolution.backend.backend_id,
        backend_version=resolution.backend.backend_version,
        required_input_refs=list(view.required_input_refs),
        backend_certificate=result.certificate.model_dump(mode="json"),
    )


__all__ = ["optimize_scenarios"]
