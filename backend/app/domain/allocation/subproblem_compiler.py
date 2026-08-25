"""Deterministic decomposition of a grounded problem into solver units.

The decomposition is deliberately target/factor based.  It does not infer a
plan from prose and it does not change candidate membership; it only records
which already-grounded inputs are required by each bounded solver route.
"""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json

from app.contracts.planning.solver import (
    SolverProblemKind,
    SolverSubproblem,
    SolverSubproblemPlan,
)
from app.contracts.planning.p1_closure import build_relation_readiness
from app.contracts.spatial.grounded_problem import GroundedPlanningProblem
from app.domain.relations.registry import build_default_relation_registry


_NETWORK_KINDS = frozenset({"connect_network", "provide_access"})
_NETWORK_EVALUATORS = frozenset({
    "access_via",
    "connect",
    "connect_network",
    "network_path",
    "provide_access",
})
_COVERAGE_KINDS = frozenset({"serve"})
_COVERAGE_EVALUATORS = frozenset({"coverage", "service", "service_coverage", "serve"})
_TOPOLOGY_KINDS = frozenset({
    "co_locate",
    "mutually_exclusive",
    "part_of",
})
_TOPOLOGY_EVALUATORS = frozenset({"adjacency", "co_locate", "topology"})
_NETWORK_TARGET_KINDS = frozenset({
    "corridor",
    "drainage",
    "linear",
    "network",
    "road",
    "road_segment",
    "street",
    "utility_network",
})
_PARCEL_TARGET_KINDS = frozenset({
    "agriculture",
    "conservation",
    "land_use",
    "parcel",
    "protection",
    "restoration",
    "site_area",
    "zone",
})


def _clean(value: object) -> str:
    return str(value or "").strip()


def _factor_targets(factor: object, target_ids: set[str]) -> tuple[str, ...]:
    refs = {
        _clean(getattr(factor, "subject_ref", "")),
        _clean(getattr(factor, "object_ref", "")),
    }
    return tuple(sorted(ref for ref in refs if ref in target_ids))


def _factors_for_target(problem: GroundedPlanningProblem, target_id: str) -> list[object]:
    factors: list[object] = []
    for factor in problem.constraint_factors:
        if target_id in _factor_targets(factor, {target_id, _clean(getattr(factor, "object_ref", ""))}):
            factors.append(factor)
            continue
        if _clean(getattr(factor, "subject_ref", "")) == target_id:
            factors.append(factor)
            continue
        if _clean(getattr(factor, "object_ref", "")) == target_id:
            factors.append(factor)
    return sorted(factors, key=lambda item: _clean(getattr(item, "factor_id", "")))


def _factor_network_refs(factors: Iterable[object]) -> list[str]:
    refs: set[str] = set()
    for factor in factors:
        refs.update(
            _clean(ref)
            for ref in list(getattr(factor, "network_refs", None) or [])
            if _clean(ref)
        )
        parameters = getattr(factor, "parameters", None)
        network_ref = _clean(getattr(parameters, "network_ref", ""))
        if network_ref:
            refs.add(network_ref)
    return sorted(refs)


def _factor_demand_refs(factors: Iterable[object]) -> list[str]:
    refs: set[str] = set()
    for factor in factors:
        parameters = getattr(factor, "parameters", None)
        demand_ref = _clean(getattr(parameters, "demand_ref", ""))
        if demand_ref:
            refs.add(demand_ref)
    return sorted(refs)


def _relation_input_gaps(
    problem: GroundedPlanningProblem,
    factors: Iterable[object],
) -> list[str]:
    """Return explicit hard-relation evaluation gaps for this target slice."""

    factor_ids = {
        _clean(getattr(factor, "factor_id", ""))
        for factor in factors
        if _clean(getattr(factor, "factor_id", ""))
    }
    satisfaction_by_factor: dict[str, object] = {}
    for satisfaction in list(getattr(problem, "relation_satisfaction", None) or []):
        for factor_id in list(getattr(satisfaction, "factor_ids", None) or []):
            if _clean(factor_id) in factor_ids:
                satisfaction_by_factor[_clean(factor_id)] = satisfaction
    gaps: list[str] = []
    relation_registry = build_default_relation_registry()
    for factor in factors:
        factor_id = _clean(getattr(factor, "factor_id", ""))
        if not factor_id or not bool(getattr(factor, "hard", False)):
            continue
        satisfaction = satisfaction_by_factor.get(factor_id)
        evaluator_key = _clean(getattr(factor, "evaluator_key", "") or getattr(factor, "kind", ""))
        evaluator_available = evaluator_key == "precedes" or relation_registry.get(evaluator_key) is not None
        readiness = build_relation_readiness(
            factor,
            satisfaction,
            evaluator_available=evaluator_available,
        )
        if readiness.evaluation_readiness not in {"ready", "pending_selection"}:
            gaps.append(
                f"missing:relation_readiness:{factor_id}:"
                f"{readiness.evaluation_readiness}"
            )
        elif readiness.status == "blocked":
            gaps.append(f"missing:relation_readiness:{factor_id}:blocked")
    return sorted(set(gaps))


def _is_topology_factor(factor: object) -> bool:
    kind = _clean(getattr(factor, "kind", ""))
    evaluator = _clean(getattr(factor, "evaluator_key", ""))
    return kind in _TOPOLOGY_KINDS or evaluator in _TOPOLOGY_EVALUATORS


def _target_problem_kind(
    target_kind: str,
    expected_output_kind: str,
    candidate_selection_mode: str,
    factors: Iterable[object],
    *,
    has_network_input: bool,
) -> SolverProblemKind:
    kinds = {_clean(getattr(item, "kind", "")) for item in factors}
    evaluators = {_clean(getattr(item, "evaluator_key", "")) for item in factors}
    if kinds & _COVERAGE_KINDS or evaluators & _COVERAGE_EVALUATORS:
        return "coverage"
    if kinds & _NETWORK_KINDS or evaluators & _NETWORK_EVALUATORS:
        return "network_path"
    semantic_kinds = {
        _clean(target_kind).lower(),
        _clean(expected_output_kind).lower(),
    }
    # A road/linear target is not automatically a path-search problem.  When
    # GROUND already gives an exact executable line and no network snapshot or
    # network relation is present, SELECT can make a typed single choice.  A
    # network_path route is reserved for the case where the required network
    # input actually exists (or is explicitly requested by a factor).
    if semantic_kinds & _NETWORK_TARGET_KINDS and has_network_input:
        return "network_path"
    if semantic_kinds & _PARCEL_TARGET_KINDS:
        return "parcel_assignment"
    if candidate_selection_mode == "choose_one":
        return "single_choice"
    return "bounded_multiobjective"


def _lineage_refs(candidate: object) -> set[str]:
    refs = {
        _clean(getattr(candidate, "candidate_id", "")),
        _clean(getattr(candidate, "source_ref", "")),
        _clean(getattr(candidate, "l1_snapshot_ref", "")),
    }
    for field in (
        "source_refs",
        "evidence_refs",
        "source_feature_ids",
        "entity_refs",
        "relation_refs",
        "l1_fact_refs",
    ):
        refs.update(
            _clean(ref)
            for ref in list(getattr(candidate, field, None) or [])
            if _clean(ref)
        )
    return refs


def _target_required_refs(
    problem: GroundedPlanningProblem,
    target_id: str,
    candidate_ids: list[str],
    factors: list[object],
    problem_kind: SolverProblemKind,
) -> tuple[list[str], list[str]]:
    target = next(
        (item for item in problem.target_domains if item.target_id == target_id),
        None,
    )
    domain = next(
        (item for item in problem.candidate_domains if item.target_id == target_id),
        None,
    )
    geometries = {
        item.candidate_id: item
        for item in problem.candidate_geometries
        if item.target_id == target_id
    }
    required: set[str] = set()
    missing: set[str] = set()
    if target is None:
        missing.add(f"missing:target_domain:{target_id}")
    else:
        required.update(target.evidence_refs)
    if domain is None:
        missing.add(f"missing:candidate_domain:{target_id}")
    else:
        required.update(domain.candidate_geometry_refs)
    if not candidate_ids:
        missing.add(f"missing:candidates:{target_id}")
    for candidate_id in candidate_ids:
        required.add(candidate_id)
        candidate = geometries.get(candidate_id)
        if candidate is None:
            missing.add(f"missing:candidate_geometry:{target_id}:{candidate_id}")
            continue
        required.update(_lineage_refs(candidate))
    for factor in factors:
        factor_id = _clean(getattr(factor, "factor_id", ""))
        if factor_id:
            required.add(factor_id)
        required.update(
            _clean(ref)
            for ref in list(getattr(factor, "evidence_refs", None) or [])
            if _clean(ref)
        )
    required.update(_factor_network_refs(factors))
    required.update(_factor_demand_refs(factors))
    # The shared pool is a parent-level capacity fact.  Persist it in every
    # parcel subproblem so a later coordinator can detect repeated ownership
    # instead of silently taking a Cartesian product.
    if problem_kind == "parcel_assignment" and problem.parcel_resource_pool is not None:
        required.add(problem.parcel_resource_pool.pool_id)
    missing.update(_relation_input_gaps(problem, factors))
    return sorted(ref for ref in required if ref), sorted(missing)


def _compile_target_subproblem(
    problem: GroundedPlanningProblem,
    target_id: str,
    target_ids: set[str],
) -> SolverSubproblem:
    target = next(
        (item for item in problem.target_domains if item.target_id == target_id),
        None,
    )
    domain = next(
        (item for item in problem.candidate_domains if item.target_id == target_id),
        None,
    )
    candidate_ids = sorted(set(domain.candidate_ids if domain is not None else []))
    factors = _factors_for_target(problem, target_id)
    problem_kind = _target_problem_kind(
        _clean(getattr(target, "target_kind", "")),
        _clean(getattr(target, "expected_output_kind", "")),
        _clean(getattr(domain, "selection_mode", "")),
        factors,
        has_network_input=bool(
            problem.network_refs or _factor_network_refs(factors)
        ),
    )
    required, missing = _target_required_refs(
        problem,
        target_id,
        candidate_ids,
        factors,
        problem_kind,
    )
    if target is not None and target.status != "resolved":
        missing.append(f"unresolved:target:{target_id}")
    if domain is not None and domain.status != "resolved":
        missing.append(f"unresolved:candidate_domain:{target_id}")
    if problem_kind in {"network_path", "coverage"}:
        network_refs = sorted(set(problem.network_refs).union(_factor_network_refs(factors)))
        if not network_refs:
            missing.append("missing:network_ref")
    if problem_kind == "coverage" and not _factor_demand_refs(factors):
        missing.append("missing:demand_ref")
    if problem_kind == "parcel_assignment":
        pool = problem.parcel_resource_pool
        if pool is None or not pool.resources:
            missing.append("missing:parcel_resource_pool")
    missing = sorted(set(missing))
    diagnostics = [
        f"target_problem_kind:{problem_kind}",
        *[f"missing_input:{ref}" for ref in missing],
    ]
    target_candidates = [
        item
        for item in problem.candidate_geometries
        if _clean(getattr(item, "target_id", "")) == target_id
    ]
    project_refs = sorted({
        _clean(getattr(item, "physical_project_ref", ""))
        for item in target_candidates
        if _clean(getattr(item, "physical_project_ref", ""))
    })
    physical_project_ref = project_refs[0] if len(project_refs) == 1 else ""
    component_claim_refs = sorted({
        _clean(ref)
        for item in target_candidates
        for ref in (getattr(item, "component_claim_refs", None) or [])
        if _clean(ref)
    })
    component_fact_refs = sorted({
        _clean(ref)
        for item in target_candidates
        for ref in (getattr(item, "component_fact_refs", None) or [])
        if _clean(ref)
    })
    return SolverSubproblem(
        subproblem_id=f"target:{target_id}",
        target_refs=(target_id,),
        physical_project_ref=physical_project_ref,
        component_claim_refs=component_claim_refs,
        component_fact_refs=component_fact_refs,
        relation_refs=tuple(
            _clean(getattr(factor, "factor_id", ""))
            for factor in factors
            if _clean(getattr(factor, "factor_id", ""))
        ),
        problem_kind=problem_kind,
        candidate_ids_by_target={target_id: tuple(candidate_ids)},
        required_input_refs=[*required, *missing],
        status="blocked" if missing else "ready",
        diagnostics=diagnostics,
    )


def _coordinate_physical_project_subproblems(
    target_subproblems: list[SolverSubproblem],
) -> tuple[list[SolverSubproblem], list[str]]:
    """Make one solver boundary for every canonical physical project.

    Target refs remain on the grouped unit so relation evaluation and target
    completeness are not collapsed.  The project is only the shared decision
    boundary used to prevent two claims in one package from being solved as
    independent interventions.
    """

    groups: dict[str, list[SolverSubproblem]] = {}
    for item in target_subproblems:
        if item.physical_project_ref:
            groups.setdefault(item.physical_project_ref, []).append(item)
    grouped_ids: set[str] = set()
    coordinated: list[SolverSubproblem] = []
    diagnostics: list[str] = []
    for project_ref, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        member_ids = sorted(item.subproblem_id for item in members)
        digest = hashlib.sha256(
            json.dumps(
                [project_ref, *member_ids],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:20]
        target_refs = sorted({ref for item in members for ref in item.target_refs})
        relation_refs = sorted({ref for item in members for ref in item.relation_refs})
        candidates: dict[str, tuple[str, ...]] = {}
        for item in members:
            candidates.update(item.candidate_ids_by_target)
        required = sorted({ref for item in members for ref in item.required_input_refs})
        dependencies = sorted({ref for item in members for ref in item.dependency_subproblem_ids})
        statuses = {item.status for item in members}
        status = "blocked" if "blocked" in statuses else (
            "deferred" if "deferred" in statuses else "ready"
        )
        kinds = {item.problem_kind for item in members}
        problem_kind = next(iter(kinds)) if len(kinds) == 1 else "bounded_multiobjective"
        grouped = SolverSubproblem(
            subproblem_id=f"project:{digest}",
            target_refs=tuple(target_refs),
            physical_project_ref=project_ref,
            component_claim_refs=sorted({
                ref for item in members for ref in item.component_claim_refs
            }),
            component_fact_refs=sorted({
                ref for item in members for ref in item.component_fact_refs
            }),
            relation_refs=tuple(relation_refs),
            problem_kind=problem_kind,
            candidate_ids_by_target=candidates,
            required_input_refs=required,
            dependency_subproblem_ids=dependencies,
            status=status,
            diagnostics=[
                *[diagnostic for item in members for diagnostic in item.diagnostics],
                "physical_project_coordinator:joint_project_decision",
            ],
        )
        coordinated.append(grouped)
        grouped_ids.update(member_ids)
        diagnostics.append(f"physical_project_coordinator:{project_ref}")
    coordinated.extend(
        item for item in target_subproblems if item.subproblem_id not in grouped_ids
    )
    return sorted(coordinated, key=lambda item: item.subproblem_id), diagnostics


def _compile_topology_subproblem(
    factor: object,
    *,
    target_ids: set[str],
    target_subproblems: dict[str, SolverSubproblem],
) -> SolverSubproblem:
    factor_id = _clean(getattr(factor, "factor_id", ""))
    endpoints = _factor_targets(factor, target_ids)
    missing: list[str] = []
    if not factor_id:
        missing.append("missing:relation_factor_id")
    if not endpoints:
        missing.append(f"missing:relation_endpoint:{factor_id or 'unknown'}")
    if _clean(getattr(factor, "object_ref", "")) and _clean(getattr(factor, "object_ref", "")) not in target_ids:
        object_ref_kind = _clean(getattr(factor, "object_ref_kind", "target"))
        if object_ref_kind == "target":
            missing.append(f"missing:relation_target:{getattr(factor, 'object_ref', '')}")
    dependencies = [
        target_subproblems[target_id].subproblem_id
        for target_id in endpoints
        if target_id in target_subproblems
    ]
    if any(target_subproblems[target_id].status != "ready" for target_id in endpoints if target_id in target_subproblems):
        missing.append("blocked:dependent_target_subproblem")
    if _clean(getattr(factor, "semantic_status", "valid")) != "valid":
        missing.append(
            f"missing:relation_semantic_status:{factor_id or 'unknown'}:"
            f"{_clean(getattr(factor, 'semantic_status', 'unknown')) or 'unknown'}"
        )
    if _clean(getattr(factor, "input_status", "ready")) != "ready":
        missing.append(
            f"missing:relation_input_status:{factor_id or 'unknown'}:"
            f"{_clean(getattr(factor, 'input_status', 'unknown')) or 'unknown'}"
        )
    if getattr(factor, "solver_supported", None) is False:
        missing.append(f"missing:topology_solver_support:{factor_id or 'unknown'}")
    required = [factor_id]
    required.extend(
        _clean(ref)
        for ref in list(getattr(factor, "evidence_refs", None) or [])
        if _clean(ref)
    )
    required.extend(_factor_network_refs([factor]))
    missing = sorted(set(missing))
    candidate_ids_by_target = {
        target_id: tuple(
            getattr(target_subproblems[target_id], "candidate_ids_by_target", {})
            .get(target_id, ())
        )
        for target_id in endpoints
        if target_id in target_subproblems
    }
    return SolverSubproblem(
        subproblem_id=f"relation:{factor_id or 'unknown'}",
        target_refs=endpoints,
        relation_refs=(factor_id,) if factor_id else (),
        problem_kind="topology_layout",
        candidate_ids_by_target=candidate_ids_by_target,
        dependency_subproblem_ids=dependencies,
        required_input_refs=[*required, *missing],
        status="blocked" if missing else "ready",
        diagnostics=[
            "topology_relation_typed_backend",
            *[f"missing_input:{ref}" for ref in missing],
        ],
    )


def _parcel_resource_refs(
    problem: GroundedPlanningProblem,
    subproblem: SolverSubproblem,
) -> set[str]:
    """Return resource identities owned by one parcel subproblem.

    Resource ownership is derived only from grounded candidate lineage and
    the typed parcel pool.  A free-text label or a target name is never enough
    to make two subproblems share a resource.
    """

    if subproblem.problem_kind != "parcel_assignment":
        return set()
    candidates = {
        item.candidate_id: item
        for item in problem.candidate_geometries
        if item.candidate_id
    }
    resources = {
        _clean(resource.bsm): resource
        for resource in (
            problem.parcel_resource_pool.resources
            if problem.parcel_resource_pool is not None
            else []
        )
        if _clean(resource.bsm)
    }
    refs: set[str] = set()
    for candidate_ids in subproblem.candidate_ids_by_target.values():
        for candidate_id in candidate_ids:
            candidate = candidates.get(candidate_id)
            if candidate is None:
                continue
            bsms = {_clean(value) for value in candidate.source_bsms if _clean(value)}
            refs.update(bsms)
            for bsm in bsms:
                resource = resources.get(bsm)
                if resource is not None:
                    refs.update(
                        _clean(value)
                        for value in (resource.resource_id, resource.geometry_ref)
                        if _clean(value)
                    )
    declared = {_clean(value) for value in problem.shared_resource_refs if _clean(value)}
    refs.update(declared.intersection(refs))
    return refs


def _coordinate_shared_parcel_subproblems(
    problem: GroundedPlanningProblem,
    target_subproblems: list[SolverSubproblem],
) -> tuple[list[SolverSubproblem], list[str]]:
    """Coalesce connected parcel subproblems into one joint solver unit.

    A child solver must not make independent choices over the same parcel
    resource.  Connected components are therefore solved as one
    ``parcel_assignment`` boundary, allowing the parcel backend to enforce
    overlap and capacity across all targets in that component.  Different
    solver kinds remain separate and are handled by the parent coordinator.
    """

    parcel = [
        item for item in target_subproblems
        if item.problem_kind == "parcel_assignment"
    ]
    if len(parcel) < 2:
        return target_subproblems, []

    refs_by_id = {
        item.subproblem_id: _parcel_resource_refs(problem, item)
        for item in parcel
    }
    components: list[list[SolverSubproblem]] = []
    remaining = {item.subproblem_id: item for item in parcel}
    while remaining:
        seed_id = min(remaining)
        component_ids = {seed_id}
        frontier = [seed_id]
        while frontier:
            current = frontier.pop()
            current_refs = refs_by_id[current]
            for other_id in sorted(remaining):
                if other_id in component_ids:
                    continue
                if current_refs.intersection(refs_by_id[other_id]):
                    component_ids.add(other_id)
                    frontier.append(other_id)
        component = [remaining[item_id] for item_id in sorted(component_ids)]
        components.append(component)
        for item_id in component_ids:
            remaining.pop(item_id, None)

    coordinated: list[SolverSubproblem] = []
    diagnostics: list[str] = []
    grouped_ids: set[str] = set()
    for component in components:
        if len(component) == 1:
            continue
        component_ids = sorted(item.subproblem_id for item in component)
        digest = hashlib.sha256(
            json.dumps(component_ids, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        grouped_id = f"target:resource:{digest}"
        target_refs = sorted({ref for item in component for ref in item.target_refs})
        relation_refs = sorted({ref for item in component for ref in item.relation_refs})
        candidates: dict[str, tuple[str, ...]] = {}
        for item in component:
            candidates.update(item.candidate_ids_by_target)
        required = sorted({ref for item in component for ref in item.required_input_refs})
        dependencies = sorted({ref for item in component for ref in item.dependency_subproblem_ids})
        statuses = {item.status for item in component}
        status = "blocked" if "blocked" in statuses else (
            "deferred" if "deferred" in statuses else "ready"
        )
        component_refs = sorted({ref for item in component for ref in refs_by_id[item.subproblem_id]})
        grouped = SolverSubproblem(
            subproblem_id=grouped_id,
            target_refs=tuple(target_refs),
            relation_refs=tuple(relation_refs),
            problem_kind="parcel_assignment",
            candidate_ids_by_target=candidates,
            required_input_refs=required,
            dependency_subproblem_ids=dependencies,
            status=status,
            diagnostics=[
                *[diagnostic for item in component for diagnostic in item.diagnostics],
                "shared_resource_coordinator:joint_parcel_assignment",
                *[f"shared_resource:{ref}" for ref in component_refs],
            ],
        )
        coordinated.append(grouped)
        grouped_ids.update(component_ids)
        diagnostics.append(f"shared_resource_coordinator:{grouped_id}")

    coordinated.extend(
        item for item in target_subproblems if item.subproblem_id not in grouped_ids
    )
    return sorted(coordinated, key=lambda item: item.subproblem_id), diagnostics


def compile_solver_subproblems(
    problem: GroundedPlanningProblem,
    *,
    readiness: object | None = None,
) -> SolverSubproblemPlan:
    """Compile a deterministic target/relation solver plan from GROUND."""

    target_ids = {
        item.target_id
        for item in [*problem.target_domains, *problem.candidate_domains]
        if _clean(getattr(item, "target_id", ""))
    }
    target_subproblems = {
        target_id: _compile_target_subproblem(problem, target_id, target_ids)
        for target_id in sorted(target_ids)
    }
    project_targets, project_diagnostics = _coordinate_physical_project_subproblems(
        list(target_subproblems.values()),
    )
    coordinated_targets, coordination_diagnostics = _coordinate_shared_parcel_subproblems(
        problem,
        project_targets,
    )
    target_subproblem_by_target = {
        target_id: item
        for item in coordinated_targets
        for target_id in item.target_refs
    }
    relation_subproblems = [
        _compile_topology_subproblem(
            factor,
            target_ids=target_ids,
            target_subproblems=target_subproblem_by_target,
        )
        for factor in sorted(
            (factor for factor in problem.constraint_factors if _is_topology_factor(factor)),
            key=lambda item: _clean(getattr(item, "factor_id", "")),
        )
    ]
    diagnostics: list[str] = []
    diagnostics.extend(project_diagnostics)
    diagnostics.extend(coordination_diagnostics)
    if relation_subproblems:
        diagnostics.append("topology_subproblems_use_typed_backend")
    if not target_subproblems:
        diagnostics.append("no_target_level_solver_subproblems")
    readiness_status = str(getattr(readiness, "status", "unverified") or "unverified")
    readiness_fingerprint = str(getattr(readiness, "fingerprint", "") or "")
    readiness_blockers = sorted({
        str(item)
        for item in (getattr(readiness, "blocker_refs", None) or [])
        if str(item).strip()
    })
    if readiness is not None and not bool(getattr(readiness, "ready", False)):
        diagnostics.append(f"solver_readiness_not_ready:{readiness_status}")
        blocked_subproblems: list[SolverSubproblem] = []
        for item in [*coordinated_targets, *relation_subproblems]:
            payload = item.model_dump(mode="python")
            payload["status"] = "blocked"
            payload["required_input_refs"] = [
                *payload.get("required_input_refs", []),
                *readiness_blockers,
            ]
            payload["diagnostics"] = [
                *payload.get("diagnostics", []),
                f"solver_readiness_not_ready:{readiness_status}",
            ]
            payload["fingerprint"] = ""
            blocked_subproblems.append(SolverSubproblem.model_validate(payload))
        coordinated_targets = [
            item for item in blocked_subproblems if item.subproblem_id.startswith("target:")
        ]
        relation_subproblems = [
            item for item in blocked_subproblems if item.subproblem_id.startswith("relation:")
        ]
    return SolverSubproblemPlan(
        problem_fingerprint=problem.fingerprint,
        readiness_status=readiness_status,
        readiness_fingerprint=readiness_fingerprint,
        readiness_blocker_refs=readiness_blockers,
        subproblems=[*coordinated_targets, *relation_subproblems],
        diagnostics=diagnostics,
    )


def should_decompose_solver_subproblems(problem: GroundedPlanningProblem) -> bool:
    """Return whether SELECT has a typed mixed target/relation boundary."""

    plan = compile_solver_subproblems(problem)
    target_kinds = {
        item.problem_kind
        for item in plan.subproblems
        if item.problem_kind != "topology_layout" and item.target_refs
    }
    return len(target_kinds) > 1 or any(
        item.problem_kind == "topology_layout" for item in plan.subproblems
    )


__all__ = ["compile_solver_subproblems", "should_decompose_solver_subproblems"]
