"""Deterministic relation-aware master solver for one PlanningScenario.

The first implementation intentionally solves one scenario.  Candidate
domains are enumerated in stable order (with a bounded search budget), while
geometry/network measurements remain in their dedicated evaluators.  This
keeps the master auditable and prevents an unavailable network from becoming a
false Euclidean success.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from itertools import product
from typing import Any

from app.contracts.planning.constraint_factor import ConstraintFactor, RelationSatisfaction
from app.contracts.planning.scenario import PlanningScenario, ScenarioFinding
from app.contracts.spatial.grounded_problem import GroundedPlanningProblem
from app.domain.relations.service import RelationEvaluationContext, evaluate_relations

from .network_subproblem import ScenarioCut, derive_network_cuts, evaluate_network_subproblem
from .relation_terms import hard_relation_blocked, relation_objective, satisfaction_score
from .scenario_builder import build_planning_scenario, build_scenario_features


_NETWORK_KEYS = frozenset({
    "connect", "connect_network", "access_via", "provide_access", "serve", "service"
})
_SEARCH_LIMIT = 20_000
_EXCLUSIVE_MATERIALIZATION_ROLES = frozenset({
    "land_use_assignment",
    "site_footprint",
    "project_footprint",
})


def _candidate_score(candidate: Any) -> float:
    components = getattr(candidate, "suitability_components", {}) or {}
    numeric = [
        float(value)
        for key, value in sorted(components.items())
        if key not in {"capacity_area_m2", "area_m2"}
        and isinstance(value, (int, float))
    ]
    if numeric:
        return sum(numeric) / len(numeric)
    return max(0.0, min(1.0, float(getattr(candidate, "confidence", 0.0) or 0.0)))


def _factor_key(factor: ConstraintFactor) -> str:
    return factor.evaluator_key or factor.kind


def _candidate_is_selectable(candidate: Any) -> bool:
    """Return whether a grounded geometry may enter scenario selection.

    ``pending`` is retained for compatibility with pre-v2 fixtures: it means
    that GROUND did not have a constraint index, not that a violation was
    proven.  An explicit failed/deferred/unknown status, however, must never
    be promoted into a final planning feature.
    """

    if not bool(getattr(candidate, "is_executable", False)):
        return False
    # Polygon materialization is role-sensitive. A zone without an explicit
    # role must remain deferred: treating it as land-use assignment would
    # silently turn an unresolved functional/protection overlay into an
    # authoritative parcel claim.
    if (
        str(getattr(candidate, "kind", "") or "") in {"polygon", "multipatch"}
        and not str(getattr(candidate, "materialization_role", "") or "").strip()
    ):
        return False
    uncertainty = str(getattr(candidate, "uncertainty_reason", "") or "").lower()
    if any(token in uncertainty for token in ("coarse", "bbox", "village_scope")):
        return False
    if str(getattr(candidate, "role", "") or "") == "scope_geometry":
        return False
    status = str(getattr(candidate, "hard_constraint_status", "pending") or "pending")
    # A typed candidate with an unresolved hard-constraint status is evidence
    # only.  Legacy untyped fixtures keep the old pending compatibility path.
    if status == "pending" and str(getattr(candidate, "materialization_role", "") or ""):
        return False
    return status not in {
        "failed",
        "deferred",
        "unknown",
    }


def _evaluate_assignment(
    problem: GroundedPlanningProblem,
    selected: Mapping[str, str],
    *,
    scenario_id: str,
    evaluator_context: RelationEvaluationContext,
) -> tuple[list[Any], list[RelationSatisfaction]]:
    # Scenario identity is owned by this solve invocation.  Rebind the
    # evaluator context for replay safety when a caller reuses a baseline
    # context with a different scenario id.
    try:
        evaluator_context = replace(evaluator_context, scenario_id=scenario_id)
    except TypeError:
        pass
    candidates = {item.candidate_id: item for item in problem.candidate_geometries}
    features = build_scenario_features(
        selected,
        candidates,
        scenario_id=scenario_id,
        factors=problem.constraint_factors,
        source_refs=problem.source_artifact_refs,
    )
    feature_index: dict[str, list[Any]] = {}
    for feature in features:
        for key in (feature.feature_id, feature.target_id, feature.candidate_id):
            feature_index.setdefault(key, []).append(feature)

    generic_factors: list[ConstraintFactor] = []
    network_results: list[RelationSatisfaction] = []
    networks = getattr(evaluator_context, "networks", {}) or {}
    demands = getattr(evaluator_context, "demands", None) or getattr(evaluator_context, "demand_snapshots", None) or {}
    for factor in sorted(problem.constraint_factors, key=lambda item: item.factor_id):
        if _factor_key(factor) in _NETWORK_KEYS:
            network_results.append(evaluate_network_subproblem(
                factor,
                feature_index,
                networks=networks,
                demands=demands,
                scenario_id=scenario_id,
                evaluator_version=str(getattr(evaluator_context, "evaluator_version", "relation-evaluator-v1")),
            ))
        else:
            generic_factors.append(factor)
    generic_results = evaluate_relations(
        generic_factors,
        features,
        evaluator_context,
    )
    by_id = {item.relation_id: item for item in [*generic_results, *network_results]}
    results = [
        by_id.get(
            factor.factor_id.removeprefix("factor:"),
            RelationSatisfaction(
                relation_id=factor.factor_id.removeprefix("factor:"),
                scenario_id=scenario_id,
                subject_ref=factor.subject_ref,
                object_ref=factor.object_ref,
                status="not_evaluable",
                criticality="hard" if factor.hard else "soft",
                factor_ids=[factor.factor_id],
                detail="relation_evaluator_missing_result",
            ),
        )
        for factor in sorted(problem.constraint_factors, key=lambda item: item.factor_id)
    ]
    return features, results


def _choices(
    problem: GroundedPlanningProblem,
) -> tuple[list[str], list[list[str]], list[str]]:
    geometry = {item.candidate_id: item for item in problem.candidate_geometries}
    targets: list[str] = []
    options: list[list[str]] = []
    unavailable: list[str] = []
    for domain in sorted(problem.candidate_domains, key=lambda item: item.target_id):
        ids = sorted({item for item in domain.candidate_ids if item in geometry})
        # Candidate-only geometry is valid evidence for grounding but cannot
        # become an execution feature in a PlanningScenario.
        ids = [item for item in ids if _candidate_is_selectable(geometry[item])]
        if ids:
            targets.append(domain.target_id)
            options.append(ids)
        else:
            # Candidate-only/unresolved domains are valid grounding evidence,
            # but they must be deferred independently instead of poisoning an
            # otherwise executable partial scenario.
            unavailable.append(domain.target_id)
    return targets, options, unavailable


def _prune_spatial_conflicts(
    selected: Mapping[str, str],
    candidates: Mapping[str, Any],
) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """Keep a deterministic non-overlapping subset of exclusive footprints.

    Protection/restoration/functional overlays are intentionally non-exclusive
    and may overlap.  Land-use assignments and site/project footprints are
    authoritative ownership claims, so selecting two intersecting candidates
    would produce an internally contradictory planning layer.  When domains
    have no alternate candidate, defer the lower-ranked target rather than
    materializing overlapping geometry.
    """
    rows = []
    for target_id, candidate_id in selected.items():
        candidate = candidates.get(candidate_id)
        if candidate is None:
            continue
        role = _candidate_materialization_role(candidate)
        if role not in _EXCLUSIVE_MATERIALIZATION_ROLES:
            rows.append((target_id, candidate_id, candidate, role))
            continue
        rows.append((target_id, candidate_id, candidate, role))
    # Higher-confidence/suitability candidates win; target/candidate IDs break
    # ties and keep replay fingerprints stable.
    rows.sort(
        key=lambda row: (
            row[3] not in _EXCLUSIVE_MATERIALIZATION_ROLES,
            -_candidate_score(row[2]),
            row[0],
            row[1],
        )
    )
    kept: list[tuple[str, str, Any, str, Any]] = []
    dropped: list[tuple[str, str, str]] = []
    for target_id, candidate_id, candidate, role in rows:
        if role not in _EXCLUSIVE_MATERIALIZATION_ROLES:
            kept.append((target_id, candidate_id, candidate, role, None))
            continue
        try:
            from shapely import wkt

            geometry = wkt.loads(str(getattr(candidate, "wkt", "") or ""))
        except Exception:
            geometry = None
        conflict = None
        if geometry is not None and not geometry.is_empty:
            for other_target, _other_candidate, other, other_role, other_geometry in kept:
                if (
                    other_role not in _EXCLUSIVE_MATERIALIZATION_ROLES
                    or other_geometry is None
                ):
                    continue
                try:
                    if geometry.intersection(other_geometry).area > 1e-12:
                        conflict = other_target
                        break
                except Exception:
                    continue
        if conflict:
            dropped.append((target_id, candidate_id, conflict))
            continue
        kept.append((target_id, candidate_id, candidate, role, geometry))
    return {target_id: candidate_id for target_id, candidate_id, *_ in kept}, dropped


def _candidate_materialization_role(candidate: Any) -> str:
    """Resolve the exclusive/non-exclusive role for old untyped candidates."""

    explicit = str(getattr(candidate, "materialization_role", "") or "")
    if explicit:
        return explicit
    legacy_role = str(getattr(candidate, "role", "") or "")
    if legacy_role == "functional_overlay":
        return "functional_overlay"
    if legacy_role == "protection_overlay":
        return "protection_overlay"
    if legacy_role == "restoration_overlay":
        return "restoration_overlay"
    if legacy_role in {"execution_geometry", "parcel_candidate"}:
        return "site_footprint"
    return ""


def _finding(code: str, message: str, *, severity: str = "error", relation_id: str = "", target_id: str = "") -> ScenarioFinding:
    return ScenarioFinding(
        code=code,
        severity=severity,
        message=message,
        relation_id=relation_id,
        target_id=target_id,
    )


def _empty_failed(
    problem: GroundedPlanningProblem,
    *,
    scenario_id: str,
    findings: Sequence[ScenarioFinding],
    satisfactions: Sequence[Any] = (),
    metrics: Mapping[str, float] | None = None,
) -> PlanningScenario:
    return build_planning_scenario(
        scenario_id=scenario_id,
        problem=problem,
        selected_candidate_ids={},
        relation_satisfactions=satisfactions,
        features=[],
        findings=findings,
        metrics=metrics or {"selected_candidate_count": 0.0},
        status="failed",
    )


def solve_scenario(
    problem: GroundedPlanningProblem,
    *,
    scenario_id: str,
    evaluator_context: RelationEvaluationContext,
    max_scenarios: int = 1,
) -> PlanningScenario:
    """Select one deterministic hard-feasible scenario from typed domains."""

    if max_scenarios != 1:
        return _empty_failed(
            problem,
            scenario_id=scenario_id,
            findings=[_finding(
                "UNSUPPORTED_MULTIPLE_SCENARIOS",
                "ScenarioSolver currently emits exactly one scenario; max_scenarios > 1 is unsupported.",
            )],
        )
    if not scenario_id.strip():
        raise ValueError("scenario_id must be non-empty")
    if not problem.candidate_domains or not problem.candidate_geometries:
        return _empty_failed(
            problem,
            scenario_id=scenario_id,
            findings=[_finding(
                "NO_PLANNING_OUTPUT",
                "No typed candidate domains/geometries are available for scenario solving.",
            )],
        )

    targets, option_lists, unavailable = _choices(problem)
    if not targets:
        return _empty_failed(
            problem,
            scenario_id=scenario_id,
            findings=[_finding(
                "NO_PLANNING_OUTPUT",
                "One or more targets have no executable candidate geometry.",
                target_id=target,
            ) for target in unavailable],
        )

    # Keep the search bounded; deterministic candidate order makes replay and
    # idempotency stable even when a project contains a large domain.
    candidate_combinations = product(*option_lists)
    best: tuple[tuple[int, float, float, tuple[str, ...]], dict[str, str], list[Any], list[Any], list[tuple[str, str, str]], bool] | None = None
    inspected = 0
    hard_feasible_count = 0
    for choice in candidate_combinations:
        inspected += 1
        if inspected > _SEARCH_LIMIT:
            break
        selected = dict(zip(targets, choice))
        selected, spatial_conflicts = _prune_spatial_conflicts(
            selected,
            {item.candidate_id: item for item in problem.candidate_geometries},
        )
        if not selected:
            continue
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
        if hard_violated:
            # A measured hard violation is terminal for this combination.
            continue
        hard_unresolved = any(hard_relation_blocked(item) for item in satisfactions)
        if not hard_unresolved:
            hard_feasible_count += 1
        relation_score = relation_objective(problem.constraint_factors, satisfactions)
        candidate_score = sum(
            _candidate_score(next(item for item in problem.candidate_geometries if item.candidate_id == candidate_id))
            for candidate_id in selected.values()
        )
        # Strictly feasible combinations always outrank provisional ones.
        # Deferred/not-evaluable hard relations remain auditable as partial
        # scenarios instead of being collapsed into a false violation.
        score = (
            0 if hard_unresolved else 1,
            relation_score,
            candidate_score,
            tuple(sorted(selected.values())),
        )
        if best is None or score > best[0]:
            best = (
                score,
                selected,
                features,
                satisfactions,
                spatial_conflicts,
                hard_unresolved,
            )

    if best is None:
        return _empty_failed(
            problem,
            scenario_id=scenario_id,
            findings=[_finding(
                "NO_HARD_FEASIBLE_SCENARIO",
                "All candidate combinations were rejected by hard relations or network subproblems.",
            )],
            metrics={
                "candidate_combinations_inspected": float(inspected),
                "hard_feasible_scenarios": 0.0,
                "selected_candidate_count": 0.0,
            },
        )

    _, selected, features, satisfactions, spatial_conflicts, hard_unresolved = best
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
    if inspected > _SEARCH_LIMIT:
        findings.append(_finding(
            "SCENARIO_SEARCH_BOUND_REACHED",
            f"Scenario search was bounded at {_SEARCH_LIMIT} combinations.",
            severity="warning",
        ))
    status = (
        "complete"
        if not unavailable and not spatial_conflicts and not hard_unresolved
        else "partial"
    )
    scenario = build_planning_scenario(
        scenario_id=scenario_id,
        problem=problem,
        selected_candidate_ids=selected,
        relation_satisfactions=satisfactions,
        features=features,
        findings=findings,
        metrics={
            "candidate_combinations_inspected": float(inspected),
            "hard_feasible_scenarios": float(hard_feasible_count),
            "selected_candidate_count": float(len(selected)),
            "spatial_conflict_deferred_count": float(len(spatial_conflicts)),
            "relation_objective": relation_objective(problem.constraint_factors, satisfactions),
        },
        status=status,
    )
    # Force construction of cuts here so callers can use derive_network_cuts
    # immediately and diagnostics remain represented in the scenario ledger.
    cuts = derive_network_cuts(scenario, problem)
    if cuts:
        scenario.findings.extend(
            _finding(
                "NETWORK_CUT_REQUIRED",
                f"Network subproblem emitted cut {cut.cut_id}: {cut.reason}",
                severity="warning",
                relation_id=cut.relation_id,
            )
            for cut in cuts
        )
        scenario.metrics["network_cut_count"] = float(len(cuts))
    return scenario


__all__ = ["ScenarioCut", "derive_network_cuts", "solve_scenario"]
