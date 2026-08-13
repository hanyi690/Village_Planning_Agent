"""One-shot capacity-constrained allocator for non-zone SELECT targets."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any

from app.contracts.spatial.global_site_allocation_contracts import (
    GlobalSiteAllocationProblem,
    GlobalSiteAllocationResult,
    GlobalSiteAssignment,
    SiteAllocationDiagnostic,
    SiteAllocationLineage,
    SiteCandidateEvidence,
)


def _diagnostic(
    code: str,
    severity: str,
    message: str,
    *,
    target_id: str = "",
    bsm: str = "",
    related_target_ids: list[str] | None = None,
    missing_factors: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> SiteAllocationDiagnostic:
    return SiteAllocationDiagnostic(
        code=code,
        severity=severity,
        message=message,
        target_id=target_id,
        bsm=bsm,
        related_target_ids=related_target_ids or [],
        missing_factors=missing_factors or [],
        details=details or {},
    )


def _lineage(target: Any, candidate: Any, parcel: Any) -> SiteAllocationLineage:
    canonical = {
        "allocator": "global-site-v1",
        "target_id": target.target_id,
        "candidate_id": candidate.candidate_id,
        "bsm": parcel.bsm,
        "target_refs": sorted(set(target.provenance_refs)),
        "candidate_refs": sorted(set(candidate.evidence_refs)),
        "parcel_refs": sorted(set(parcel.provenance_refs)),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return SiteAllocationLineage(
        lineage_id=f"site-lineage-{digest[:24]}",
        target_id=target.target_id,
        candidate_id=candidate.candidate_id,
        bsm=parcel.bsm,
        target_provenance_refs=sorted(set(target.provenance_refs)),
        candidate_evidence_refs=sorted(set(candidate.evidence_refs)),
        parcel_provenance_refs=sorted(set(parcel.provenance_refs)),
        geometry_ref=parcel.geometry_ref,
    )


def _quality(
    candidate: SiteCandidateEvidence,
    *,
    required_area_m2: float,
    capacity_area_m2: float,
    required_factors: tuple[str, ...],
) -> tuple[float, dict[str, float]]:
    breakdown = {
        key: float(candidate.score_breakdown[key])
        for key in required_factors
    }
    area_fit = min(1.0, required_area_m2 / capacity_area_m2)
    breakdown["area_fit"] = area_fit
    breakdown["source_suitability"] = float(candidate.suitability_score)
    values = [*breakdown.values()]
    return sum(values) / len(values), breakdown


def allocate_global_sites(
    problem: GlobalSiteAllocationProblem,
) -> GlobalSiteAllocationResult:
    """Allocate every valid project/facility target in one deterministic MIP.

    Missing evidence removes only that target/candidate from the model and is
    represented as an explicit unplaced assignment.  No neutral or zero-valued
    score is synthesized for a missing factor.
    """

    targets = {item.target_id: item for item in sorted(problem.targets, key=lambda item: item.target_id)}
    parcels = {item.bsm: item for item in sorted(problem.parcels, key=lambda item: item.bsm)}
    candidates_by_target: dict[str, list[SiteCandidateEvidence]] = defaultdict(list)
    for candidate in sorted(problem.candidates, key=lambda item: (item.target_id, item.bsm)):
        candidates_by_target[candidate.target_id].append(candidate)

    diagnostics: list[SiteAllocationDiagnostic] = []
    invalid_reasons: dict[str, str] = {}
    effective: dict[tuple[str, str], tuple[SiteCandidateEvidence, float, dict[str, float]]] = {}

    for target_id, target in targets.items():
        if target.required_area_m2 <= 0:
            invalid_reasons[target_id] = "target_area_capacity_unresolved"
            diagnostics.append(_diagnostic(
                "TARGET_REQUIRED_AREA_MISSING",
                "error",
                "A typed positive footprint/area is required for parcel capacity accounting.",
                target_id=target_id,
            ))
            continue
        rows = candidates_by_target.get(target_id, [])
        if not rows:
            invalid_reasons[target_id] = "target_bound_suitability_missing"
            diagnostics.append(_diagnostic(
                "TARGET_SUITABILITY_CANDIDATES_MISSING",
                "error",
                "No target-bound suitability candidate exists; global-pool fallback is forbidden.",
                target_id=target_id,
            ))
            continue
        for candidate in rows:
            if not candidate.hard_feasible:
                diagnostics.append(_diagnostic(
                    "CANDIDATE_HARD_INFEASIBLE",
                    "info",
                    "Candidate failed terrain or hard-constraint evaluation.",
                    target_id=target_id,
                    bsm=candidate.bsm,
                    details={"exclusion_codes": candidate.exclusion_codes},
                ))
                continue
            blocking_availability = [
                str(item.get("code") or "EVIDENCE_UNAVAILABLE")
                for item in candidate.availability_diagnostics
                if bool(item.get("blocks_candidate"))
            ]
            if blocking_availability:
                diagnostics.append(_diagnostic(
                    "CANDIDATE_EVIDENCE_AVAILABILITY_BLOCKED",
                    "info",
                    "Evidence policy marked this candidate unavailable.",
                    target_id=target_id,
                    bsm=candidate.bsm,
                    details={"codes": blocking_availability},
                ))
                continue
            missing = [
                factor
                for factor in problem.required_score_factors
                if factor not in candidate.score_breakdown
                or candidate.score_breakdown[factor] is None
                or not math.isfinite(float(candidate.score_breakdown[factor]))
            ]
            if missing:
                diagnostics.append(_diagnostic(
                    "CANDIDATE_REQUIRED_EVIDENCE_MISSING",
                    "info",
                    "Candidate lacks one or more required measured suitability factors.",
                    target_id=target_id,
                    bsm=candidate.bsm,
                    missing_factors=missing,
                ))
                continue
            parcel = parcels.get(candidate.bsm)
            if parcel is None:
                diagnostics.append(_diagnostic(
                    "PARCEL_CAPACITY_FACT_MISSING",
                    "error",
                    "Candidate BSM has no authoritative parcel capacity fact.",
                    target_id=target_id,
                    bsm=candidate.bsm,
                ))
                continue
            if target.required_area_m2 > parcel.capacity_area_m2 + 1e-6:
                diagnostics.append(_diagnostic(
                    "CANDIDATE_AREA_CAPACITY_INSUFFICIENT",
                    "info",
                    "Target footprint exceeds available parcel capacity.",
                    target_id=target_id,
                    bsm=candidate.bsm,
                    details={
                        "required_area_m2": target.required_area_m2,
                        "capacity_area_m2": parcel.capacity_area_m2,
                    },
                ))
                continue
            quality, breakdown = _quality(
                candidate,
                required_area_m2=target.required_area_m2,
                capacity_area_m2=parcel.capacity_area_m2,
                required_factors=problem.required_score_factors,
            )
            effective[(target_id, candidate.bsm)] = (candidate, quality, breakdown)

        if not any(key[0] == target_id for key in effective):
            invalid_reasons.setdefault(target_id, "no_fully_evidenced_feasible_candidate")
            diagnostics.append(_diagnostic(
                "TARGET_NO_FEASIBLE_EVIDENCED_CANDIDATE",
                "error",
                "Every target-bound candidate was removed by evidence, hard constraints, or capacity.",
                target_id=target_id,
            ))

    if not targets:
        return GlobalSiteAllocationResult(
            status="OPTIMAL",
            feasible=True,
            complete=True,
            input_provenance_refs=sorted(set(problem.provenance_refs)),
        )

    if not effective:
        assignments = [
            GlobalSiteAssignment(
                target_id=target.target_id,
                target_type=target.target_type,
                expected_output_kind=target.expected_output_kind,
                status="unplaced",
                priority=target.priority,
                reason=invalid_reasons.get(target.target_id, "no_feasible_candidate"),
                target_binding=target.target_binding,
            )
            for target in targets.values()
        ]
        return GlobalSiteAllocationResult(
            status="MODEL_INVALID",
            feasible=False,
            complete=False,
            assignments=assignments,
            diagnostics=diagnostics,
            input_provenance_refs=sorted(set(problem.provenance_refs)),
        )

    try:
        import pulp
    except ImportError:
        diagnostics.append(_diagnostic(
            "SITE_SOLVER_UNAVAILABLE",
            "error",
            "PuLP/CBC is unavailable; no sequential or greedy fallback is allowed.",
        ))
        return GlobalSiteAllocationResult(
            status="SOLVER_UNAVAILABLE",
            feasible=False,
            complete=False,
            assignments=[
                GlobalSiteAssignment(
                    target_id=target.target_id,
                    target_type=target.target_type,
                    expected_output_kind=target.expected_output_kind,
                    status="unplaced",
                    priority=target.priority,
                    reason="global_site_solver_unavailable",
                    target_binding=target.target_binding,
                )
                for target in targets.values()
            ],
            diagnostics=diagnostics,
            input_provenance_refs=sorted(set(problem.provenance_refs)),
        )

    keys = sorted(effective)
    model = pulp.LpProblem("global_non_zone_site_allocation", pulp.LpMaximize)
    variables = {
        key: pulp.LpVariable(f"site_x_{index:06d}", cat=pulp.LpBinary)
        for index, key in enumerate(keys)
    }
    for target_id in sorted(targets):
        model += pulp.lpSum(
            variables[key] for key in keys if key[0] == target_id
        ) <= 1

    keys_by_bsm: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in keys:
        keys_by_bsm[key[1]].append(key)
    for bsm, parcel_keys in sorted(keys_by_bsm.items()):
        parcel = parcels[bsm]
        model += pulp.lpSum(
            targets[target_id].required_area_m2 * variables[(target_id, bsm)]
            for target_id, _ in parcel_keys
        ) <= parcel.capacity_area_m2
        exclusive_keys = [
            key for key in parcel_keys if targets[key[0]].exclusive_bsm
        ]
        if exclusive_keys:
            exclusive_sum = pulp.lpSum(variables[key] for key in exclusive_keys)
            model += exclusive_sum <= 1
            for key in parcel_keys:
                if key not in exclusive_keys:
                    model += variables[key] + exclusive_sum <= 1

    objective_terms = []
    for index, key in enumerate(keys):
        target = targets[key[0]]
        quality = effective[key][1]
        deterministic_tie = (len(keys) - index) * 1e-8
        objective_terms.append(
            (target.priority * 1000.0 + quality * 10.0 + deterministic_tie)
            * variables[key]
        )
    model += pulp.lpSum(objective_terms)

    try:
        model.solve(pulp.PULP_CBC_CMD(msg=0))
    except Exception as exc:
        diagnostics.append(_diagnostic(
            "SITE_SOLVER_ERROR",
            "error",
            "Global site solver raised an exception.",
            details={"type": type(exc).__name__, "message": str(exc)},
        ))
        return GlobalSiteAllocationResult(
            status="SOLVER_ERROR",
            feasible=False,
            complete=False,
            diagnostics=diagnostics,
            input_provenance_refs=sorted(set(problem.provenance_refs)),
        )

    if pulp.LpStatus[model.status] != "Optimal":
        diagnostics.append(_diagnostic(
            "SITE_MODEL_NOT_OPTIMAL",
            "error",
            "Global site model did not reach an optimal solution.",
            details={"solver_status": pulp.LpStatus[model.status]},
        ))
        return GlobalSiteAllocationResult(
            status="INFEASIBLE",
            feasible=False,
            complete=False,
            diagnostics=diagnostics,
            input_provenance_refs=sorted(set(problem.provenance_refs)),
        )

    chosen = {
        key
        for key, variable in variables.items()
        if variable.value() is not None and variable.value() > 0.5
    }
    assignments: list[GlobalSiteAssignment] = []
    for target_id, target in targets.items():
        key = next((item for item in sorted(chosen) if item[0] == target_id), None)
        if key is None:
            reason = invalid_reasons.get(target_id, "global_capacity_or_priority_conflict")
            assignments.append(GlobalSiteAssignment(
                target_id=target_id,
                target_type=target.target_type,
                expected_output_kind=target.expected_output_kind,
                status="unplaced",
                priority=target.priority,
                reason=reason,
                target_binding=target.target_binding,
            ))
            if target_id not in invalid_reasons:
                competing = sorted({
                    other_target
                    for other_target, bsm in keys
                    if other_target != target_id
                    and any(candidate.bsm == bsm for candidate in candidates_by_target[target_id])
                })
                diagnostics.append(_diagnostic(
                    "TARGET_UNPLACED_BY_GLOBAL_CONFLICT",
                    "warning",
                    "Target lost a parcel capacity/exclusivity conflict in the global optimum.",
                    target_id=target_id,
                    related_target_ids=competing,
                ))
            continue
        candidate, quality, breakdown = effective[key]
        parcel = parcels[key[1]]
        binding = dict(target.target_binding)
        binding["allocation_exclusive_bsm"] = target.exclusive_bsm
        assignments.append(GlobalSiteAssignment(
            target_id=target_id,
            target_type=target.target_type,
            expected_output_kind=target.expected_output_kind,
            status="assigned",
            bsm=parcel.bsm,
            anchor_point=candidate.anchor_point,
            consumed_area_m2=target.required_area_m2,
            parcel_capacity_area_m2=parcel.capacity_area_m2,
            priority=target.priority,
            score=quality,
            score_breakdown=breakdown,
            target_binding=binding,
            lineage=_lineage(target, candidate, parcel),
        ))

    complete = all(item.status == "assigned" for item in assignments)
    status = "OPTIMAL" if complete else "PARTIAL"
    return GlobalSiteAllocationResult(
        status=status,
        feasible=True,
        complete=complete,
        assignments=assignments,
        objective_value=float(pulp.value(model.objective) or 0.0),
        diagnostics=diagnostics,
        input_provenance_refs=sorted(set(problem.provenance_refs)),
    )


__all__ = ["allocate_global_sites"]
