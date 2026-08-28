"""Bounded shared-parcel assignment backend for SELECT.

This backend is intentionally small and deterministic.  It consumes the
closed ``GroundedPlanningProblem.parcel_resource_pool`` and only filters
candidate combinations by shared BSM capacity and positive-area overlap.  It
does not create geometry, choose a fallback parcel, or mutate neighboring
parcels; EXECUTE remains responsible for materializing the approved members.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.contracts.select.solver import (
    BackendResult,
    BackendSupport,
    SolverConfig,
    SolverProblemView,
    backend_input_digest,
)
from app.contracts.ground.grounded_problem import GroundedPlanningProblem
from app.spatial.relations.service import RelationEvaluationContext


def _parcel_selection_validator(
    problem: GroundedPlanningProblem,
):
    pool = getattr(problem, "parcel_resource_pool", None)
    resources = {
        str(getattr(item, "bsm", "") or ""): item
        for item in list(getattr(pool, "resources", None) or [])
    }

    def validate(
        selected: dict[str, tuple[str, ...]],
        candidates: dict[str, Any],
    ) -> tuple[bool, str]:
        consumed: dict[str, float] = defaultdict(float)
        geometries: dict[str, list[Any]] = defaultdict(list)
        for target_id, candidate_ids in sorted(selected.items()):
            for candidate_id in candidate_ids:
                candidate = candidates.get(candidate_id)
                if candidate is None:
                    return False, f"PARCEL_CANDIDATE_MISSING:{target_id}:{candidate_id}"
                source_bsms = list(getattr(candidate, "source_bsms", None) or [])
                if len(source_bsms) != 1:
                    return False, f"PARCEL_SOURCE_BSM_NOT_SINGLE:{target_id}:{candidate_id}"
                bsm = str(source_bsms[0])
                resource = resources.get(bsm)
                if resource is None:
                    return False, f"PARCEL_RESOURCE_MISSING:{bsm}"
                area = float(getattr(candidate, "planning_area_ha", 0.0) or 0.0)
                if area <= 0:
                    return False, f"PARCEL_PLANNING_AREA_MISSING:{target_id}:{candidate_id}"
                consumed[bsm] += area
                try:
                    from shapely import wkt

                    geometry = wkt.loads(str(getattr(candidate, "wkt", "") or ""))
                except Exception:
                    geometry = None
                if geometry is None or geometry.is_empty or not geometry.is_valid:
                    return False, f"PARCEL_GEOMETRY_INVALID:{target_id}:{candidate_id}"
                for other in geometries[bsm]:
                    try:
                        if geometry.intersection(other).area > 1e-12:
                            return False, f"PARCEL_SUBGEOMETRY_OVERLAP:{bsm}"
                    except Exception:
                        return False, f"PARCEL_SUBGEOMETRY_RELATION_UNKNOWN:{bsm}"
                geometries[bsm].append(geometry)
        for bsm, area in consumed.items():
            capacity = float(getattr(resources[bsm], "eligible_area_ha", 0.0) or 0.0)
            if capacity <= 0 or area > capacity + 1e-9:
                return False, f"PARCEL_CAPACITY_EXCEEDED:{bsm}"
        return True, ""

    return validate


class ParcelAssignmentBackend:
    """Deterministic bounded solver for typed shared parcel resources."""

    backend_id = "parcel_assignment_bounded"
    backend_version = "1.0"

    def supports(
        self,
        problem: GroundedPlanningProblem,
        view: SolverProblemView,
    ) -> BackendSupport:
        reasons: list[str] = []
        if view.problem_kind != "parcel_assignment":
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

        effective_config = config.model_copy(
            update={"backend_version": self.backend_version}
        )
        effective_set_id = set_id or f"solver:{problem.fingerprint[:12]}"
        input_digest = backend_input_digest(view, effective_config)
        scenario_set = _optimize_scenarios_enumeration(
            problem,
            set_id=effective_set_id,
            evaluator_context=evaluator_context
            or RelationEvaluationContext(scenario_id=effective_set_id),
            baseline_ref=baseline_ref,
            max_scenarios=effective_config.max_scenarios,
            search_limit=effective_config.search_limit,
            deterministic_seed=effective_config.deterministic_seed,
            objective_definitions=effective_config.objective_definitions or None,
            selection_validator=_parcel_selection_validator(problem),
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
            raise ValueError("parcel assignment backend produced no typed certificate")
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
            findings=[
                finding
                for scenario in scenario_set.scenarios
                for finding in scenario.findings
            ],
            infeasibility_explanations=scenario_set.infeasibility_explanations,
            certificate=certificate,
            scenario_set=scenario_set,
        )


__all__ = ["ParcelAssignmentBackend"]
