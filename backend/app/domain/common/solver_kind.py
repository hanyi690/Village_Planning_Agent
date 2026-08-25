"""Deterministic solver-kind compilation from typed planning facts."""

from __future__ import annotations

from typing import Any


_NETWORK_KINDS = frozenset({"connect_network", "provide_access"})
_NETWORK_EVALUATORS = frozenset({
    "connect",
    "connect_network",
    "access_via",
    "provide_access",
    "network_path",
})
_COVERAGE_KINDS = frozenset({"serve"})
_COVERAGE_EVALUATORS = frozenset({"serve", "service", "service_coverage", "coverage"})
_TOPOLOGY_KINDS = frozenset({
    "adjacent_to",
    "contains",
    "co_locate",
    "intersects",
    "located_in",
    "mutually_exclusive",
    "overlaps",
    "part_of",
})
_TOPOLOGY_EVALUATORS = frozenset({
    "adjacency",
    "adjacent",
    "adjacent_to",
    "co_locate",
    "contains",
    "intersects",
    "located_in",
    "mutually_exclusive",
    "overlaps",
    "part_of",
    "topology",
    "topology_layout",
})
_SPECIALIZED_KINDS = frozenset({
    "coverage",
    "parcel_assignment",
    "network_path",
    "topology_layout",
})


def _relation_facts(items: list[Any]) -> tuple[set[str], set[str], set[str], bool]:
    kinds: set[str] = set()
    evaluators: set[str] = set()
    parameter_types: set[str] = set()
    topology_scope = False
    for item in items:
        kind = str(
            getattr(item, "kind", "")
            or getattr(item, "relation_template", "")
            or ""
        )
        evaluator = str(getattr(item, "evaluator_key", "") or "")
        parameters = getattr(item, "parameters", None)
        parameter_type = str(getattr(parameters, "parameter_type", "") or "")
        scope = str(getattr(item, "geometry_scope", "") or "")
        kinds.add(kind)
        evaluators.add(evaluator)
        parameter_types.add(parameter_type)
        topology_scope = topology_scope or (
            kind in _TOPOLOGY_KINDS
            or evaluator in _TOPOLOGY_EVALUATORS
            or (scope == "global" and kind in _TOPOLOGY_KINDS)
        )
    return kinds, evaluators, parameter_types, topology_scope


def infer_intent_solver_kind(graph: Any) -> tuple[str, list[str]]:
    """Compile the earliest auditable route from a typed intent graph."""

    nodes = list(getattr(graph, "nodes", None) or [])
    relations = list(getattr(graph, "relations", None) or [])
    kinds, evaluators, parameter_types, topology_scope = _relation_facts(relations)
    if topology_scope or any("topology" in key or "adjacency" in key for key in evaluators):
        return "topology_layout", ["typed_topology_relation"]
    if kinds & _COVERAGE_KINDS or evaluators & _COVERAGE_EVALUATORS or "service" in parameter_types:
        return "coverage", ["typed_service_coverage_relation"]
    if kinds & _NETWORK_KINDS or evaluators & _NETWORK_EVALUATORS or parameter_types & {"connect", "access"}:
        return "network_path", ["typed_network_relation"]
    if list(getattr(graph, "shared_resource_refs", None) or []):
        return "parcel_assignment", ["typed_shared_resource"]
    return "auto", ["no_specialized_solver_fact"]


def _parcel_coupling_reason(problem: Any) -> str:
    shared_refs = list(getattr(problem, "shared_resource_refs", None) or [])
    if shared_refs:
        return "typed_shared_resource"

    domains = list(getattr(problem, "candidate_domains", None) or [])
    candidate_targets: dict[str, set[str]] = {}
    for domain in domains:
        target_id = str(getattr(domain, "target_id", "") or "")
        for candidate_id in list(getattr(domain, "candidate_ids", None) or []):
            candidate_targets.setdefault(str(candidate_id), set()).add(target_id)
    if any(len(target_ids) > 1 for target_ids in candidate_targets.values()):
        return "typed_competing_candidate_membership"

    candidates = list(getattr(problem, "candidate_geometries", None) or [])
    resource_targets: dict[str, set[str]] = {}
    for candidate in candidates:
        target_id = str(getattr(candidate, "target_id", "") or "")
        if str(getattr(candidate, "materialization_role", "") or "") != "land_use_assignment":
            continue
        refs = {
            *list(getattr(candidate, "source_bsms", None) or []),
            *list(getattr(candidate, "source_feature_ids", None) or []),
        }
        for ref in refs:
            if str(ref).strip():
                resource_targets.setdefault(str(ref), set()).add(target_id)
    if any(len(target_ids) > 1 for target_ids in resource_targets.values()):
        return "typed_shared_parcel_membership"

    candidate_by_id = {
        str(getattr(candidate, "candidate_id", "") or ""): candidate
        for candidate in candidates
    }
    for domain in domains:
        if str(getattr(domain, "selection_mode", "") or "") != "choose_subset":
            continue
        candidate_ids = list(getattr(domain, "candidate_ids", None) or [])
        if len(candidate_ids) < 2:
            continue
        parcel_members = [
            candidate_by_id[candidate_id]
            for candidate_id in candidate_ids
            if candidate_id in candidate_by_id
            and (
                str(getattr(candidate_by_id[candidate_id], "granularity", "") or "")
                in {"parcel_extent", "parcel_set"}
                or str(getattr(candidate_by_id[candidate_id], "role", "") or "")
                == "parcel_candidate"
            )
        ]
        if len(parcel_members) >= 2:
            return "typed_parcel_combination_domain"
    return ""


def _typed_specialized_problem_kind(problem: Any) -> tuple[str, list[str]]:
    factors = list(getattr(problem, "constraint_factors", None) or [])
    kinds, evaluators, parameter_types, topology_scope = _relation_facts(factors)
    if topology_scope or evaluators & _TOPOLOGY_EVALUATORS:
        return "topology_layout", ["typed_topology_factor"]
    if kinds & _COVERAGE_KINDS or evaluators & _COVERAGE_EVALUATORS or "service" in parameter_types:
        return "coverage", ["typed_service_coverage_factor"]
    if kinds & _NETWORK_KINDS or evaluators & _NETWORK_EVALUATORS or parameter_types & {"connect", "access"}:
        return "network_path", ["typed_network_factor"]
    parcel_reason = _parcel_coupling_reason(problem)
    if parcel_reason:
        return "parcel_assignment", [parcel_reason]
    return "", []


def solver_kind_input_gate(
    problem: Any,
    problem_kind: str,
) -> tuple[bool, list[str]]:
    """Return whether a specialized route has its required typed fact."""

    if problem_kind not in _SPECIALIZED_KINDS:
        return True, []
    typed_kind, _reasons = _typed_specialized_problem_kind(problem)
    if typed_kind == problem_kind:
        missing: list[str] = []
        if problem_kind == "parcel_assignment":
            pool = getattr(problem, "parcel_resource_pool", None)
            resources = list(getattr(pool, "resources", None) or []) if pool is not None else []
            if not resources:
                missing.append("missing:parcel_resource_pool")
            else:
                for resource in resources:
                    bsm = str(getattr(resource, "bsm", "") or "")
                    if not bsm:
                        missing.append("missing:parcel_resource:bsm")
                        continue
                    if float(getattr(resource, "eligible_area_ha", 0.0) or 0.0) <= 0:
                        missing.append(f"missing:parcel_resource:{bsm}:eligible_area")
                    if str(getattr(resource, "availability_status", "unknown") or "unknown") == "unknown":
                        missing.append(f"missing:parcel_resource:{bsm}:availability_status")
                    if not str(getattr(resource, "geometry_ref", "") or "").strip():
                        missing.append(f"missing:parcel_resource:{bsm}:geometry_ref")
            candidate_geometries = {
                str(getattr(item, "candidate_id", "") or ""): item
                for item in list(getattr(problem, "candidate_geometries", None) or [])
            }
            for domain in list(getattr(problem, "candidate_domains", None) or []):
                for candidate_id in list(getattr(domain, "candidate_ids", None) or []):
                    candidate = candidate_geometries.get(str(candidate_id))
                    if candidate is None:
                        missing.append(f"missing:parcel_candidate:{domain.target_id}:{candidate_id}")
                        continue
                    if len(list(getattr(candidate, "source_bsms", None) or [])) != 1:
                        missing.append(
                            f"missing:parcel_candidate:{domain.target_id}:{candidate_id}:single_source_bsm"
                        )
                    if float(getattr(candidate, "planning_area_ha", 0.0) or 0.0) <= 0:
                        missing.append(
                            f"missing:parcel_candidate:{domain.target_id}:{candidate_id}:planning_area"
                        )
            return not missing, sorted(set(missing))
        if problem_kind == "topology_layout":
            topology_factors = [
                factor
                for factor in list(getattr(problem, "constraint_factors", None) or [])
                if str(getattr(factor, "kind", "") or "") in _TOPOLOGY_KINDS
                or str(getattr(factor, "evaluator_key", "") or "") in _TOPOLOGY_EVALUATORS
            ]
            if not topology_factors:
                missing.append("missing:topology_relation_factor")
                return False, sorted(set(missing))
            target_domains = {
                str(getattr(domain, "target_id", "") or ""): domain
                for domain in list(getattr(problem, "candidate_domains", None) or [])
                if str(getattr(domain, "target_id", "") or "").strip()
            }
            candidates = {
                str(getattr(candidate, "candidate_id", "") or ""): candidate
                for candidate in list(getattr(problem, "candidate_geometries", None) or [])
                if str(getattr(candidate, "candidate_id", "") or "").strip()
            }
            for factor in topology_factors:
                factor_id = str(getattr(factor, "factor_id", "") or "unknown")
                subject_ref = str(getattr(factor, "subject_ref", "") or "").strip()
                object_ref = str(getattr(factor, "object_ref", "") or "").strip()
                if not subject_ref or not object_ref:
                    missing.append(f"missing:topology_endpoint:{factor_id}")
                    continue
                evaluator = str(getattr(factor, "evaluator_key", "") or "").strip()
                kind = str(getattr(factor, "kind", "") or "").strip()
                if evaluator and evaluator not in _TOPOLOGY_EVALUATORS and kind not in _TOPOLOGY_KINDS:
                    missing.append(f"missing:topology_evaluator:{factor_id}:{evaluator}")
                for endpoint in (subject_ref, object_ref):
                    domain = target_domains.get(endpoint)
                    if domain is None:
                        # Non-target endpoints require an independently bound
                        # feature reference; this route does not invent one.
                        if endpoint == object_ref and str(getattr(factor, "object_ref_kind", "target")) != "target":
                            if not list(getattr(factor, "required_refs", None) or []):
                                missing.append(f"missing:topology_reference:{factor_id}:{endpoint}")
                            continue
                        missing.append(f"missing:topology_target:{factor_id}:{endpoint}")
                        continue
                    if str(getattr(domain, "status", "unresolved")) != "resolved":
                        missing.append(f"missing:topology_domain:{endpoint}")
                    candidate_ids = list(getattr(domain, "candidate_ids", None) or [])
                    if not candidate_ids:
                        missing.append(f"missing:topology_candidates:{endpoint}")
                    for candidate_id in candidate_ids:
                        candidate = candidates.get(str(candidate_id))
                        if candidate is None:
                            missing.append(f"missing:topology_geometry:{endpoint}:{candidate_id}")
                            continue
                        if not str(getattr(candidate, "wkt", "") or "").strip():
                            missing.append(f"missing:topology_wkt:{candidate_id}")
                        if not str(getattr(candidate, "crs", "") or "").strip():
                            missing.append(f"missing:topology_crs:{candidate_id}")
                        if str(getattr(candidate, "role", "")) != "execution_geometry":
                            missing.append(f"missing:topology_execution_geometry:{candidate_id}")
            return not missing, sorted(set(missing))
        return True, []
    missing = [f"missing:typed_solver_fact:{problem_kind}"]
    if problem_kind in {"network_path", "coverage"}:
        missing.append("missing:network_ref")
    if problem_kind == "coverage":
        missing.append("missing:demand_ref")
    return False, missing


def collect_network_refs(problem: Any) -> list[str]:
    """Collect replay-critical network snapshots from problem and factors."""

    refs = {
        str(ref)
        for ref in list(getattr(problem, "network_refs", None) or [])
        if str(ref).strip()
    }
    for factor in list(getattr(problem, "constraint_factors", None) or []):
        refs.update(
            str(ref)
            for ref in list(getattr(factor, "network_refs", None) or [])
            if str(ref).strip()
        )
        parameters = getattr(factor, "parameters", None)
        network_ref = str(getattr(parameters, "network_ref", "") or "")
        if network_ref:
            refs.add(network_ref)
    return sorted(refs)


def infer_problem_solver_kind(problem: Any) -> tuple[str, list[str]]:
    """Classify a closed GROUND problem conservatively.

    Specialized typed facts always win over candidate cardinality.  This is
    what prevents a one-candidate network/coverage problem from being silently
    interpreted as a simple deterministic choice.
    """

    explicit = str(getattr(problem, "solver_kind", "auto") or "auto")
    specialized_kind, specialized_reasons = _typed_specialized_problem_kind(problem)
    if specialized_kind:
        if explicit not in {"auto", specialized_kind}:
            return specialized_kind, [
                *specialized_reasons,
                f"solver_kind_conflict:{explicit}:{specialized_kind}",
            ]
        return specialized_kind, specialized_reasons
    if explicit in _SPECIALIZED_KINDS:
        return explicit, [f"explicit_solver_kind_missing_typed_facts:{explicit}"]

    domains = list(getattr(problem, "candidate_domains", None) or [])
    if len(domains) == 1 and str(getattr(domains[0], "selection_mode", "") or "") == "choose_one":
        structural_kind = "single_choice"
        reasons = ["single_choose_one_domain"]
        if explicit not in {"auto", structural_kind}:
            reasons.append(f"solver_kind_conflict:{explicit}:{structural_kind}")
        return structural_kind, reasons
    if domains:
        structural_kind = "bounded_multiobjective"
        reasons = ["closed_candidate_domain_product"]
        if explicit not in {"auto", structural_kind}:
            reasons.append(f"solver_kind_conflict:{explicit}:{structural_kind}")
        return structural_kind, reasons
    return "unknown", ["no_candidate_domain"]


__all__ = [
    "collect_network_refs",
    "infer_intent_solver_kind",
    "infer_problem_solver_kind",
    "solver_kind_input_gate",
]
