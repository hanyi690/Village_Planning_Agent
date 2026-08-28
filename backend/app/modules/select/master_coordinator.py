"""Small deterministic master problem for cross-target resource coordination."""

from __future__ import annotations

import hashlib
import itertools
import json
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.select.scenario import MasterCertificatePayload as MasterCertificate
from app.contracts.ground.relation_parameters import ServiceParameters
from app.contracts.select.scenario import ScenarioFeature
from app.spatial.relations.service import RelationEvaluationContext, evaluate_relations


class MasterCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    target_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    project_id: str = ""
    physical_project_ref: str = ""
    parcel_refs: tuple[str, ...] = ()
    network_refs: tuple[str, ...] = ()
    demand_by_ref: dict[str, float] = Field(default_factory=dict)
    geometry_wkt: str = ""
    crs: str = ""
    source_refs: tuple[str, ...] = ()


def _master_relation_check(
    product: tuple[MasterCandidate, ...],
    factors: Iterable[object],
    evaluator_context: RelationEvaluationContext | None,
) -> tuple[list[str], list[str]]:
    """Evaluate hard relations for one global candidate product.

    The master receives only selected candidate geometries.  A relation that
    cannot be evaluated is a deferred master input, while a measured violation
    is a real conflict.  Keeping these outcomes separate prevents the global
    coordinator from converting missing topology evidence into infeasibility.
    """

    typed_factors = [
        factor
        for factor in factors
        if bool(getattr(factor, "hard", False))
    ]
    if not typed_factors:
        return [], []
    scenario_id = "master:" + hashlib.sha256(
        json.dumps(
            [(item.target_id, item.candidate_id) for item in product],
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    features: list[ScenarioFeature] = []
    for item in product:
        if not item.geometry_wkt:
            continue
        upper = item.geometry_wkt.upper()
        geometry_kind = (
            "point" if upper.startswith("POINT")
            else "line" if upper.startswith(("LINESTRING", "MULTILINESTRING"))
            else "polygon" if upper.startswith(("POLYGON", "MULTIPOLYGON"))
            else "multipatch"
        )
        features.append(ScenarioFeature(
            feature_id=f"feature:{scenario_id}:{item.target_id}:{item.candidate_id}",
            scenario_id=scenario_id,
            target_id=item.target_id,
            candidate_id=item.candidate_id,
            geometry_kind=geometry_kind,
            geometry_wkt=item.geometry_wkt,
            crs=item.crs,
            generation_operation="master_candidate_projection",
            source_refs=list(item.source_refs) or [f"candidate:{item.candidate_id}"],
            relation_ids=[
                str(getattr(factor, "factor_id", "") or "").removeprefix("factor:")
                for factor in typed_factors
                if str(getattr(factor, "factor_id", "") or "").strip()
            ] or [f"selection:{item.target_id}"],
        ))
    context = evaluator_context or RelationEvaluationContext(scenario_id=scenario_id)
    context = context if context.scenario_id == scenario_id else context.__class__(
        **{
            **context.__dict__,
            "scenario_id": scenario_id,
        }
    )
    features.extend(
        feature
        for feature in (getattr(context, "reference_features", {}) or {}).values()
        if isinstance(feature, ScenarioFeature)
    )
    satisfactions = evaluate_relations(typed_factors, features, context)
    conflicts: list[str] = []
    blockers: list[str] = []
    for row in satisfactions:
        relation_ref = f"relation:{row.relation_id}"
        if row.status == "violated":
            conflicts.append(f"{relation_ref}:violated")
        elif row.status != "satisfied":
            blockers.append(f"{relation_ref}:{row.status}")
    return sorted(set(conflicts)), sorted(set(blockers))


def coordinate_master(
    candidates: Iterable[MasterCandidate],
    *,
    parcel_capacity: dict[str, float] | None = None,
    network_capacity: dict[str, float] | None = None,
    demand_capacity: dict[str, float] | None = None,
    relation_factors: Iterable[object] = (),
    evaluator_context: RelationEvaluationContext | None = None,
    search_limit: int = 4096,
) -> MasterCertificate:
    """Enumerate one candidate per target and reject shared over-capacity choices.

    The bounded certificate is intentionally independent from local solver output:
    a locally feasible alternative is never promoted until this master check passes.
    """
    rows = sorted(candidates, key=lambda item: (item.target_id, item.candidate_id))
    by_target: dict[str, list[MasterCandidate]] = {}
    for row in rows:
        by_target.setdefault(row.target_id, []).append(row)
    if not by_target:
        return MasterCertificate(status="deferred", blocker_refs=["master_candidates_missing"], search_limit=search_limit)
    limits = {
        "parcel": parcel_capacity or {},
        "network": network_capacity or {},
        "demand": demand_capacity or {},
    }
    inspected = 0
    conflict_refs: set[str] = set()
    relation_blockers: set[str] = set()
    for product in itertools.product(*(by_target[key] for key in sorted(by_target))):
        inspected += 1
        if inspected > search_limit:
            return MasterCertificate(status="deferred", conflict_refs=sorted(conflict_refs), blocker_refs=["master_search_bound_exceeded"], combinations_inspected=search_limit, search_limit=search_limit)
        project_choice: dict[str, str] = {}
        duplicate_project_conflicts: set[str] = set()
        for item in product:
            project_ref = str(item.physical_project_ref or item.project_id or f"target:{item.target_id}")
            prior = project_choice.get(project_ref)
            if prior is not None and prior != item.candidate_id:
                duplicate_project_conflicts.add(
                    f"project:{project_ref}:multiple_candidate_choices"
                )
            project_choice[project_ref] = item.candidate_id
        if duplicate_project_conflicts:
            conflict_refs.update(duplicate_project_conflicts)
            continue
        used: dict[str, float] = {}
        owned_resources: set[tuple[str, str, str]] = set()
        for item in product:
            owner = str(item.physical_project_ref or item.project_id or f"target:{item.target_id}")
            for ref in item.parcel_refs:
                resource_key = (owner, "parcel", ref)
                if resource_key not in owned_resources:
                    used[f"parcel:{ref}"] = used.get(f"parcel:{ref}", 0.0) + 1.0
                    owned_resources.add(resource_key)
            for ref in item.network_refs:
                resource_key = (owner, "network", ref)
                if resource_key not in owned_resources:
                    used[f"network:{ref}"] = used.get(f"network:{ref}", 0.0) + 1.0
                    owned_resources.add(resource_key)
            for ref, amount in item.demand_by_ref.items():
                resource_key = (owner, "demand", ref)
                if resource_key not in owned_resources:
                    used[f"demand:{ref}"] = used.get(f"demand:{ref}", 0.0) + float(amount)
                    owned_resources.add(resource_key)
        exceeded = [
            key for key, amount in used.items()
            if key.split(":", 1)[1] in limits[key.split(":", 1)[0]]
            and amount > float(limits[key.split(":", 1)[0]][key.split(":", 1)[1]]) + 1e-9
        ]
        if not exceeded:
            relation_conflicts, blockers = _master_relation_check(
                product,
                relation_factors,
                evaluator_context,
            )
            if blockers:
                relation_blockers.update(blockers)
                continue
            if relation_conflicts:
                conflict_refs.update(relation_conflicts)
                continue
            return MasterCertificate(
                status="feasible",
                selected_candidate_ids={item.target_id: item.candidate_id for item in product},
                project_refs=sorted({(item.physical_project_ref or item.project_id) for item in product if item.physical_project_ref or item.project_id}),
                parcel_refs=sorted({ref for item in product for ref in item.parcel_refs}),
                network_refs=sorted({ref for item in product for ref in item.network_refs}),
                demand_refs=sorted({ref for item in product for ref in item.demand_by_ref}),
                combinations_inspected=inspected,
                search_limit=search_limit,
            )
        conflict_refs.update(exceeded)
    if relation_blockers:
        return MasterCertificate(
            status="deferred",
            conflict_refs=sorted(conflict_refs),
            blocker_refs=sorted(relation_blockers),
            combinations_inspected=inspected,
            search_limit=search_limit,
        )
    return MasterCertificate(status="bounded_infeasible", conflict_refs=sorted(conflict_refs), combinations_inspected=inspected, search_limit=search_limit)


def build_master_candidates(
    problem: object,
    subproblem_plan: object,
    evaluator_context: object | None = None,
    *,
    allowed_candidate_ids: set[str] | None = None,
) -> list[MasterCandidate]:
    """Project typed GROUND/subproblem facts into master alternatives."""

    geometries = {
        str(getattr(item, "candidate_id", "")): item
        for item in (getattr(problem, "candidate_geometries", None) or [])
        if str(getattr(item, "candidate_id", "")).strip()
    }
    subproblems_by_target: dict[str, list[object]] = {}
    for subproblem in getattr(subproblem_plan, "subproblems", None) or ():
        for target_id in getattr(subproblem, "target_refs", None) or ():
            subproblems_by_target.setdefault(str(target_id), []).append(subproblem)

    factors_by_target: dict[str, list[object]] = {}
    for factor in getattr(problem, "constraint_factors", None) or ():
        refs = {
            str(getattr(factor, "subject_ref", "") or "").strip(),
            str(getattr(factor, "object_ref", "") or "").strip(),
        }
        for target_id in refs:
            if target_id:
                factors_by_target.setdefault(target_id, []).append(factor)
    pool = getattr(problem, "parcel_resource_pool", None)
    resource_by_bsm = {
        str(getattr(item, "bsm", "")): item
        for item in (getattr(pool, "resources", None) or ())
        if str(getattr(item, "bsm", "")).strip()
    }
    demands = getattr(evaluator_context, "demands", None) or {}
    rows: list[MasterCandidate] = []
    for target_id, target_subproblems in sorted(subproblems_by_target.items()):
        project_ref = next(
            (
                str(getattr(item, "physical_project_ref", "") or "")
                for item in target_subproblems
                if str(getattr(item, "physical_project_ref", "") or "").strip()
            ),
            "",
        )
        candidate_ids = tuple(sorted({
            str(candidate_id)
            for subproblem in target_subproblems
            for candidate_id in getattr(subproblem, "candidate_ids_by_target", {}).get(target_id, ())
            if str(candidate_id).strip()
        }))
        if allowed_candidate_ids is not None:
            candidate_ids = tuple(item for item in candidate_ids if item in allowed_candidate_ids)
        for candidate_id in sorted(set(candidate_ids)):
            candidate = geometries.get(str(candidate_id))
            if candidate is None:
                continue
            if not bool(getattr(candidate, "is_executable", False)):
                continue
            parcel_refs = {
                str(value).strip()
                for value in (getattr(candidate, "source_bsms", None) or ())
                if str(value).strip()
            }
            parcel_refs.update(
                str(getattr(resource_by_bsm[bsm], "resource_id", "")).strip()
                for bsm in tuple(parcel_refs)
                if bsm in resource_by_bsm
                and str(getattr(resource_by_bsm[bsm], "resource_id", "")).strip()
            )
            network_refs: set[str] = set()
            demand_by_ref: dict[str, float] = {}
            for factor in factors_by_target.get(target_id, ()):
                parameters = getattr(factor, "parameters", None)
                network_ref = str(getattr(parameters, "network_ref", "") or "").strip()
                if network_ref:
                    network_refs.add(network_ref)
                demand_ref = str(getattr(parameters, "demand_ref", "") or "").strip()
                if demand_ref and isinstance(parameters, ServiceParameters):
                    snapshot = demands.get(demand_ref)
                    if snapshot is not None:
                        demand_by_ref[demand_ref] = float(
                            getattr(snapshot, "total_demand", 0.0) or 0.0
                        )
            if any(
                str(getattr(subproblem, "problem_kind", "")) in {"coverage", "network_path"}
                for subproblem in target_subproblems
            ):
                network_refs.update(
                    str(ref).strip()
                    for ref in (getattr(problem, "network_refs", None) or ())
                    if str(ref).strip()
                )
            rows.append(MasterCandidate(
                target_id=target_id,
                candidate_id=str(candidate_id),
                project_id=project_ref,
                physical_project_ref=project_ref,
                parcel_refs=tuple(sorted(parcel_refs)),
                network_refs=tuple(sorted(network_refs)),
                demand_by_ref=demand_by_ref,
                geometry_wkt=str(getattr(candidate, "wkt", "") or ""),
                crs=str(getattr(candidate, "crs", "") or ""),
                source_refs=tuple(sorted({
                    *list(getattr(candidate, "source_refs", None) or ()),
                    *list(getattr(candidate, "evidence_refs", None) or ()),
                })),
            ))
    return sorted(rows, key=lambda item: (item.target_id, item.candidate_id))


def coordinate_master_plan(
    problem: object,
    subproblem_plan: object,
    evaluator_context: object | None = None,
    *,
    allowed_candidate_ids: set[str] | None = None,
    search_limit: int = 4096,
) -> MasterCertificate:
    """Run the production master boundary over typed planning artifacts."""

    candidates = build_master_candidates(
        problem,
        subproblem_plan,
        evaluator_context,
        allowed_candidate_ids=allowed_candidate_ids,
    )
    parcel_refs = {
        ref
        for candidate in candidates
        for ref in candidate.parcel_refs
    }
    parcel_capacity = {ref: 1.0 for ref in sorted(parcel_refs)}
    context_network_capacity = getattr(evaluator_context, "network_capacities", None) or {}
    context_demand_capacity = getattr(evaluator_context, "demand_capacities", None) or {}
    return coordinate_master(
        candidates,
        parcel_capacity=parcel_capacity,
        network_capacity={str(key): float(value) for key, value in context_network_capacity.items()},
        demand_capacity={str(key): float(value) for key, value in context_demand_capacity.items()},
        relation_factors=list(getattr(problem, "constraint_factors", None) or ()),
        evaluator_context=evaluator_context,
        search_limit=search_limit,
    )


__all__ = [
    "MasterCandidate",
    "MasterCertificate",
    "build_master_candidates",
    "coordinate_master",
    "coordinate_master_plan",
]
