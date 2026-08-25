"""Small typed registry for task-specific ScenarioOptimizer backends.

The registry is intentionally an internal facade, not a plugin framework.  A
backend must opt into a typed ``SolverProblemView`` and an unsupported kind is
returned as an auditable resolution failure rather than falling back to a
different algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.contracts.planning.scenario import ScenarioSet
from app.contracts.planning.solver import (
    BackendResult,
    BackendSupport,
    SolverConfig,
    SolverProblemKind,
    SolverProblemView,
    backend_input_digest,
)
from app.contracts.spatial.grounded_problem import GroundedPlanningProblem
from app.domain.relations.service import RelationEvaluationContext
from app.domain.common.solver_kind import (
    collect_network_refs,
    infer_problem_solver_kind,
    solver_kind_input_gate,
)

from .parcel_assignment_backend import ParcelAssignmentBackend


class SolverBackend(Protocol):
    backend_id: str
    backend_version: str

    def supports(
        self,
        problem: GroundedPlanningProblem,
        view: SolverProblemView,
    ) -> BackendSupport:
        ...

    def solve(
        self,
        problem: GroundedPlanningProblem,
        view: SolverProblemView,
        *,
        config: SolverConfig,
        evaluator_context: RelationEvaluationContext | None = None,
        set_id: str = "",
        baseline_ref: str = "",
    ) -> BackendResult:
        ...


@dataclass(frozen=True)
class BackendResolution:
    backend: SolverBackend | None
    support: BackendSupport


def _typed_relation_refs(problem: GroundedPlanningProblem) -> tuple[list[str], list[str]]:
    """Collect replay-critical network and demand refs from typed factors."""
    network_refs: set[str] = set()
    demand_refs: set[str] = set()
    for factor in list(getattr(problem, "constraint_factors", None) or []):
        parameters = getattr(factor, "parameters", None)
        network_ref = str(getattr(parameters, "network_ref", "") or "").strip()
        demand_ref = str(getattr(parameters, "demand_ref", "") or "").strip()
        if network_ref:
            network_refs.add(network_ref)
        if demand_ref:
            demand_refs.add(demand_ref)
    return sorted(network_refs), sorted(demand_refs)


def build_solver_problem_view(
    problem: GroundedPlanningProblem,
    *,
    evaluator_context: RelationEvaluationContext | None = None,
) -> SolverProblemView:
    """Compile routing facts from the closed GROUND contract only."""

    explicit = str(getattr(problem, "solver_kind", "auto") or "auto")
    domains = sorted(problem.candidate_domains, key=lambda item: item.target_id)
    modes = {item.target_id: item.selection_mode for item in domains}
    candidate_ids = {
        item.target_id: tuple(sorted(item.candidate_ids))
        for item in domains
    }
    inferred_kind, route_reasons = infer_problem_solver_kind(problem)
    kind: SolverProblemKind = inferred_kind  # type: ignore[assignment]
    input_complete, missing_input_refs = solver_kind_input_gate(problem, kind)
    network_refs = collect_network_refs(problem)
    typed_network_refs, demand_refs = _typed_relation_refs(problem)
    network_refs = sorted(set(network_refs).union(typed_network_refs))
    resource_refs: list[str] = []
    resource_pool = getattr(problem, "parcel_resource_pool", None)
    if resource_pool is not None:
        resource_refs.extend([str(getattr(resource_pool, "pool_id", "") or "")])
        for resource in list(getattr(resource_pool, "resources", None) or []):
            resource_refs.extend([
                str(getattr(resource, "resource_id", "") or ""),
                str(getattr(resource, "geometry_ref", "") or ""),
                *list(getattr(resource, "source_refs", None) or []),
                *list(getattr(resource, "evidence_refs", None) or []),
                *list(getattr(resource, "adjacency_evidence_refs", None) or []),
            ])

    required_refs: list[str] = [
        *problem.source_artifact_refs,
        *network_refs,
        *demand_refs,
        *problem.shared_resource_refs,
        *problem.scope_source_refs,
        *resource_refs,
    ]
    for candidate in problem.candidate_geometries:
        required_refs.extend(candidate.source_refs)
        required_refs.extend(candidate.evidence_refs)
    for binding in problem.bindings:
        required_refs.extend(binding.evidence_refs)
        if binding.geometry_ref:
            required_refs.append(binding.geometry_ref)
    for target in problem.target_domains:
        required_refs.extend(target.evidence_refs)

    missing_input_refs = list(missing_input_refs)
    for satisfaction in list(getattr(problem, "relation_satisfaction", None) or []):
        status = str(getattr(satisfaction, "status", "unknown") or "unknown").strip()
        criticality = str(getattr(satisfaction, "criticality", "soft") or "soft").strip()
        relation_id = str(getattr(satisfaction, "relation_id", "") or "").strip()
        if (
            criticality == "hard"
            and status in {"pending", "deferred", "not_evaluable", "unknown"}
        ):
            missing_input_refs.append(
                f"missing:relation_satisfaction:{relation_id or 'unknown'}:{status}"
            )
    if kind in {"coverage", "network_path"}:
        context_networks = getattr(evaluator_context, "networks", None) or {}
        if not network_refs:
            missing_input_refs.append("missing:network_ref")
        else:
            for network_ref in network_refs:
                if network_ref not in context_networks:
                    missing_input_refs.append(f"missing:network:{network_ref}")
    if kind == "coverage":
        context_demands = getattr(evaluator_context, "demands", None) or {}
        if not demand_refs:
            missing_input_refs.append("missing:demand_ref")
        else:
            for demand_ref in demand_refs:
                if demand_ref not in context_demands:
                    missing_input_refs.append(f"missing:demand:{demand_ref}")
    missing_input_refs = sorted(set(missing_input_refs))
    input_complete = input_complete and not missing_input_refs
    return SolverProblemView(
        problem_fingerprint=problem.fingerprint,
        problem_kind=kind,
        target_ids=tuple(item.target_id for item in domains),
        candidate_ids_by_target=candidate_ids,
        selection_modes_by_target=modes,
        required_input_refs=[*required_refs, *missing_input_refs],
        snapshot_refs=[problem.baseline_ref, *network_refs, *demand_refs],
        resource_refs=resource_refs,
        explicit_solver_kind="" if explicit == "auto" else explicit,
        routing_reason_codes=route_reasons,
        input_complete=input_complete,
        missing_input_refs=missing_input_refs,
    )


class DeterministicChoiceBackend:
    """Formal adapter around the bounded, deterministic choice enumerator."""

    backend_id = "deterministic_choice"
    backend_version = "1.0"
    supported_kinds = frozenset({"single_choice", "bounded_multiobjective"})

    def supports(
        self,
        problem: GroundedPlanningProblem,
        view: SolverProblemView,
    ) -> BackendSupport:
        reasons: list[str] = []
        if view.problem_kind not in self.supported_kinds:
            reasons.append("UNSUPPORTED_SOLVER_KIND")
        if not view.input_complete:
            reasons.append("SOLVER_INPUT_INCOMPLETE")
        if not problem.can_solve:
            reasons.append("GROUNDING_INCOMPLETE")
        return BackendSupport(
            supported=not reasons,
            reason_codes=reasons,
            required_input_refs=[
                *view.required_input_refs,
                *view.missing_input_refs,
            ],
            input_complete=problem.can_solve and view.input_complete,
        )

    def solve(
        self,
        problem: GroundedPlanningProblem,
        view: SolverProblemView,
        *,
        config: SolverConfig,
        evaluator_context: RelationEvaluationContext | None = None,
        set_id: str = "",
        baseline_ref: str = "",
    ) -> BackendResult:
        support = self.supports(problem, view)
        if not support.supported:
            raise ValueError("backend is not supported: " + ", ".join(support.reason_codes))

        # Local import breaks the portfolio <-> facade cycle.  The internal
        # function is the pre-Slice-1 implementation and remains private to
        # this adapter; SELECT still calls only optimize_scenarios().
        from .scenario_optimizer import _optimize_scenarios_enumeration

        effective_config = config.model_copy(
            update={"backend_version": self.backend_version}
        )
        definitions = effective_config.objective_definitions or None
        effective_set_id = set_id or f"solver:{problem.fingerprint[:12]}"
        input_digest = backend_input_digest(view, effective_config)
        scenario_set = _optimize_scenarios_enumeration(
            problem,
            set_id=effective_set_id,
            evaluator_context=evaluator_context or RelationEvaluationContext(scenario_id=effective_set_id),
            baseline_ref=baseline_ref,
            max_scenarios=effective_config.max_scenarios,
            search_limit=effective_config.search_limit,
            deterministic_seed=effective_config.deterministic_seed,
            objective_definitions=definitions,
            backend_route={
                "backend_id": self.backend_id,
                "backend_version": self.backend_version,
                "problem_kind": view.problem_kind,
                "input_digest": input_digest,
                "required_input_refs": list(view.required_input_refs),
                "deterministic_settings": {
                    "deterministic_seed": effective_config.deterministic_seed,
                    "search_limit": effective_config.search_limit,
                    "max_scenarios": effective_config.max_scenarios,
                    **effective_config.replay_settings,
                },
                "solver_config": effective_config.model_dump(mode="json"),
            },
        )
        certificate = scenario_set.solver_certificate.backend_certificate
        if certificate is None:
            raise ValueError("choice backend produced no typed backend certificate")
        recommended = scenario_set.recommended
        selected = {}
        if recommended is not None:
            selected = {
                item.target_id: list(item.candidate_ids)
                for item in recommended.target_selections
            }
        return BackendResult(
            problem_kind=view.problem_kind,
            selected_candidate_ids=selected,
            route_refs=list(certificate.route_refs),
            objective_vectors=scenario_set.objective_vectors,
            scenarios=scenario_set.scenarios,
            findings=[finding for scenario in scenario_set.scenarios for finding in scenario.findings],
            infeasibility_explanations=scenario_set.infeasibility_explanations,
            certificate=certificate,
            scenario_set=scenario_set,
        )


class NetworkRelationBackend:
    """Bounded candidate solver for typed network and service relations.

    The backend deliberately reuses the private bounded enumerator: network
    and service measurements are evaluated by ``evaluate_network_subproblem``
    for every candidate combination, while the backend boundary guarantees
    that the required network and demand snapshots are present.  It is a
    small-scale relation solver, not a replacement for a future large MILP,
    CP-SAT or facility-location backend.
    """

    backend_id = "network_relation_bounded"
    backend_version = "1.0"
    supported_kinds = frozenset({"coverage", "network_path"})

    def supports(
        self,
        problem: GroundedPlanningProblem,
        view: SolverProblemView,
    ) -> BackendSupport:
        reasons: list[str] = []
        if view.problem_kind not in self.supported_kinds:
            reasons.append("UNSUPPORTED_SOLVER_KIND")
        if not view.input_complete:
            reasons.append("SOLVER_INPUT_INCOMPLETE")
        if not problem.can_solve:
            reasons.append("GROUNDING_INCOMPLETE")
        return BackendSupport(
            supported=not reasons,
            reason_codes=reasons,
            required_input_refs=[*view.required_input_refs, *view.missing_input_refs],
            input_complete=problem.can_solve and view.input_complete,
        )

    def solve(
        self,
        problem: GroundedPlanningProblem,
        view: SolverProblemView,
        *,
        config: SolverConfig,
        evaluator_context: RelationEvaluationContext | None = None,
        set_id: str = "",
        baseline_ref: str = "",
    ) -> BackendResult:
        support = self.supports(problem, view)
        if not support.supported:
            raise ValueError("backend is not supported: " + ", ".join(support.reason_codes))
        from .scenario_optimizer import _optimize_scenarios_enumeration

        effective_config = config.model_copy(update={"backend_version": self.backend_version})
        effective_set_id = set_id or f"solver:{problem.fingerprint[:12]}"
        input_digest = backend_input_digest(view, effective_config)
        scenario_set = _optimize_scenarios_enumeration(
            problem,
            set_id=effective_set_id,
            evaluator_context=evaluator_context or RelationEvaluationContext(scenario_id=effective_set_id),
            baseline_ref=baseline_ref,
            max_scenarios=effective_config.max_scenarios,
            search_limit=effective_config.search_limit,
            deterministic_seed=effective_config.deterministic_seed,
            objective_definitions=effective_config.objective_definitions or None,
            backend_route={
                "backend_id": self.backend_id,
                "backend_version": self.backend_version,
                "problem_kind": view.problem_kind,
                "input_digest": input_digest,
                "required_input_refs": list(view.required_input_refs),
                "deterministic_settings": {
                    "deterministic_seed": effective_config.deterministic_seed,
                    "search_limit": effective_config.search_limit,
                    "max_scenarios": effective_config.max_scenarios,
                    **effective_config.replay_settings,
                },
                "solver_config": effective_config.model_dump(mode="json"),
            },
        )
        certificate = scenario_set.solver_certificate.backend_certificate
        if certificate is None:
            raise ValueError("network relation backend produced no typed certificate")
        recommended = scenario_set.recommended
        selected = (
            {
                item.target_id: list(item.candidate_ids)
                for item in recommended.target_selections
            }
            if recommended is not None
            else {}
        )
        return BackendResult(
            problem_kind=view.problem_kind,
            selected_candidate_ids=selected,
            route_refs=list(certificate.route_refs),
            objective_vectors=scenario_set.objective_vectors,
            scenarios=scenario_set.scenarios,
            findings=[finding for scenario in scenario_set.scenarios for finding in scenario.findings],
            infeasibility_explanations=scenario_set.infeasibility_explanations,
            certificate=certificate,
            scenario_set=scenario_set,
        )


class SolverBackendRegistry:
    """Ordered registry with explicit fail-closed resolution."""

    def __init__(self, backends: list[SolverBackend] | None = None) -> None:
        self._backends: list[SolverBackend] = []
        for backend in backends or []:
            self.register(backend)

    def register(self, backend: SolverBackend) -> None:
        if any(item.backend_id == backend.backend_id for item in self._backends):
            raise ValueError(f"duplicate solver backend: {backend.backend_id}")
        self._backends.append(backend)

    def resolve(
        self,
        problem: GroundedPlanningProblem,
        view: SolverProblemView,
    ) -> BackendResolution:
        if not problem.can_solve:
            return BackendResolution(
                backend=None,
                support=BackendSupport(
                    supported=False,
                    reason_codes=["GROUNDING_INCOMPLETE"],
                    required_input_refs=list(view.required_input_refs),
                    input_complete=False,
                ),
            )
        if not view.input_complete:
            return BackendResolution(
                backend=None,
                support=BackendSupport(
                    supported=False,
                    reason_codes=[
                        "SOLVER_INPUT_INCOMPLETE",
                        "UNSUPPORTED_SOLVER_KIND",
                        *view.missing_input_refs,
                    ],
                    required_input_refs=[
                        *view.required_input_refs,
                        *view.missing_input_refs,
                    ],
                    input_complete=False,
                ),
            )
        unsupported: list[str] = []
        for backend in self._backends:
            support = backend.supports(problem, view)
            if support.supported:
                return BackendResolution(backend=backend, support=support)
            unsupported.extend(support.reason_codes)
        return BackendResolution(
            backend=None,
            support=BackendSupport(
                supported=False,
                reason_codes=sorted(set(unsupported or ["UNSUPPORTED_SOLVER_KIND"])),
                required_input_refs=list(view.required_input_refs),
                input_complete=problem.can_solve,
            ),
        )


def default_solver_registry() -> SolverBackendRegistry:
    return SolverBackendRegistry([
        ParcelAssignmentBackend(),
        NetworkRelationBackend(),
        DeterministicChoiceBackend(),
    ])


__all__ = [
    "BackendResolution",
    "DeterministicChoiceBackend",
    "NetworkRelationBackend",
    "ParcelAssignmentBackend",
    "SolverBackend",
    "SolverBackendRegistry",
    "build_solver_problem_view",
    "default_solver_registry",
]
