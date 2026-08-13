"""Deterministic global allocator for authoritative zone parcel assignments.

This module is intentionally independent from SELECT and EXECUTE workers.  It
reuses the repository's PuLP/CBC adapter pattern while enforcing a richer typed
contract: target-bound candidates only, hard-constraint fail-closed behavior,
one authoritative land-use assignment per BSM, per-target area balance, and
complete assignment lineage.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from app.contracts.spatial.global_zone_allocation_contracts import (
    AuthoritativeZoneParcelAssignment,
    GlobalZoneAllocationProblem,
    GlobalZoneAllocationResult,
    ZoneAllocationDiagnostic,
    ZoneAreaBalance,
    ZoneAssignmentLineage,
    ZoneParcelCandidate,
    ZoneParcelFact,
)


_DEFICIT_COST_PER_HA = 1_000_000.0
_EXCESS_COST_PER_HA = 250_000.0
_SUITABILITY_REWARD_PER_HA = 10_000.0
_TIE_BREAK_COST = 0.0001

_MODEL_ERROR_CODES = {
    "TARGET_AREA_INVALID",
    "TARGET_CLASSIFICATION_UNRESOLVED",
    "TARGET_LAND_USE_MISSING",
    "TARGET_ROLE_UNSUPPORTED",
    "TARGET_OUTPUT_KIND_INVALID",
    "TARGET_CANDIDATE_SET_MISSING",
    "TARGET_GROUND_CANDIDATES_EMPTY",
    "CANDIDATE_NOT_GROUNDED",
    "PARCEL_FACT_MISSING",
}


def _diagnostic(
    code: str,
    severity: str,
    message: str,
    *,
    target_id: str = "",
    bsm: str = "",
    related_target_ids: list[str] | None = None,
    constraint_codes: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> ZoneAllocationDiagnostic:
    return ZoneAllocationDiagnostic(
        code=code,
        severity=severity,
        message=message,
        target_id=target_id,
        bsm=bsm,
        related_target_ids=related_target_ids or [],
        constraint_codes=constraint_codes or [],
        details=details or {},
    )


def _resolved_classification(target: Any) -> tuple[str, str, list[str]] | None:
    decision = getattr(target, "classification_decision", None)
    if decision is None or str(getattr(decision, "status", "")) != "resolved":
        return None
    code = str(getattr(decision, "selected_code", "") or "").strip()
    system_value = getattr(decision, "code_system", "")
    system = str(getattr(system_value, "value", system_value) or "").strip()
    if not code or not system:
        return None
    return system, code, sorted(set(getattr(decision, "evidence_refs", None) or []))


def _blocking_constraint_codes(parcel: ZoneParcelFact, target_id: str) -> list[str]:
    return sorted(
        constraint.code
        for constraint in parcel.constraints
        if constraint.blocks_land_use_assignment
        and (
            not constraint.blocked_target_ids
            or target_id in set(constraint.blocked_target_ids)
        )
    )


def _lineage_id(
    target: Any,
    candidate: ZoneParcelCandidate,
    parcel: ZoneParcelFact,
) -> str:
    canonical = {
        "allocator_version": "global-zone-v1",
        "bsm": parcel.bsm,
        "candidate_provenance_refs": sorted(set(candidate.provenance_refs)),
        "claim_refs": sorted(set(getattr(target, "claim_refs", None) or [])),
        "geometry_ref": parcel.geometry_ref,
        "parcel_provenance_refs": sorted(set(parcel.provenance_refs)),
        "target_id": str(getattr(target, "target_id", "") or ""),
        "zone_id": str(getattr(target, "zone_id", "") or ""),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"zone-lineage-{digest[:24]}"


def _empty_balances(
    targets: list[Any],
    tolerance_ratio: float,
) -> list[ZoneAreaBalance]:
    balances: list[ZoneAreaBalance] = []
    for target in sorted(targets, key=lambda item: str(getattr(item, "target_id", ""))):
        requested = max(float(getattr(target, "area_ha", 0.0) or 0.0), 0.0)
        balances.append(
            ZoneAreaBalance(
                target_id=str(getattr(target, "target_id", "") or ""),
                zone_id=str(
                    getattr(target, "zone_id", "")
                    or getattr(target, "target_id", "")
                    or ""
                ),
                requested_area_ha=round(requested, 6),
                assigned_area_ha=0.0,
                shortfall_area_ha=round(requested, 6),
                excess_area_ha=0.0,
                tolerance_area_ha=round(requested * tolerance_ratio, 6),
                fulfillment_ratio=0.0,
                within_tolerance=requested == 0.0,
            )
        )
    return balances


class DeterministicGlobalZoneParcelAllocator:
    """Solve all exclusive ZoneTargets in one deterministic CBC model."""

    def allocate(
        self,
        problem: GlobalZoneAllocationProblem,
    ) -> GlobalZoneAllocationResult:
        diagnostics: list[ZoneAllocationDiagnostic] = []
        targets_by_id = {
            target.target_id: target
            for target in sorted(problem.targets, key=lambda item: item.target_id)
        }
        candidate_sets = {
            item.target_id: item
            for item in sorted(problem.candidate_sets, key=lambda item: item.target_id)
        }
        parcels_by_bsm = {
            parcel.bsm: parcel
            for parcel in sorted(problem.parcels, key=lambda item: item.bsm)
        }
        overlay_targets = sorted(
            problem.overlay_targets,
            key=lambda item: item.target_id,
        )

        orphan_candidate_ids = sorted(set(candidate_sets) - set(targets_by_id))
        for target_id in orphan_candidate_ids:
            diagnostics.append(
                _diagnostic(
                    "ORPHAN_CANDIDATE_SET",
                    "warning",
                    "Candidate set has no matching typed ZoneTarget and was ignored.",
                    target_id=target_id,
                )
            )

        valid_target_ids: list[str] = []
        classification_by_target: dict[str, tuple[str, str, list[str]]] = {}
        for target_id, target in targets_by_id.items():
            role = str(getattr(target, "materialization_role", "") or "")
            if role != "land_use_assignment":
                diagnostics.append(
                    _diagnostic(
                        "TARGET_ROLE_UNSUPPORTED",
                        "error",
                        "Only land_use_assignment targets may enter exclusive allocation.",
                        target_id=target_id,
                        details={"materialization_role": role},
                    )
                )
                continue
            if str(getattr(target, "expected_output_kind", "")) != "polygon":
                diagnostics.append(
                    _diagnostic(
                        "TARGET_OUTPUT_KIND_INVALID",
                        "error",
                        "Exclusive zone allocation requires polygon output.",
                        target_id=target_id,
                    )
                )
                continue
            requested_area = float(getattr(target, "area_ha", 0.0) or 0.0)
            if requested_area <= 0:
                diagnostics.append(
                    _diagnostic(
                        "TARGET_AREA_INVALID",
                        "error",
                        "Zone target requires a positive typed area_ha.",
                        target_id=target_id,
                    )
                )
                continue
            if not str(getattr(target, "land_use", "") or "").strip():
                diagnostics.append(
                    _diagnostic(
                        "TARGET_LAND_USE_MISSING",
                        "error",
                        "Zone target requires an explicit land_use value.",
                        target_id=target_id,
                    )
                )
                continue
            classification = _resolved_classification(target)
            if classification is None:
                diagnostics.append(
                    _diagnostic(
                        "TARGET_CLASSIFICATION_UNRESOLVED",
                        "error",
                        "Authoritative land-use assignment requires a resolved classification.",
                        target_id=target_id,
                    )
                )
                continue
            if target_id not in candidate_sets:
                diagnostics.append(
                    _diagnostic(
                        "TARGET_CANDIDATE_SET_MISSING",
                        "error",
                        "Zone target has no target-bound suitability candidate set.",
                        target_id=target_id,
                    )
                )
                continue
            if not list(getattr(target, "candidate_bsms", None) or []):
                diagnostics.append(
                    _diagnostic(
                        "TARGET_GROUND_CANDIDATES_EMPTY",
                        "error",
                        "Zone target has no grounded candidate BSMs; "
                        "full-pool fallback is forbidden.",
                        target_id=target_id,
                    )
                )
                continue
            valid_target_ids.append(target_id)
            classification_by_target[target_id] = classification

        effective_candidates: dict[tuple[str, str], ZoneParcelCandidate] = {}
        candidate_owners: dict[str, list[str]] = defaultdict(list)
        for target_id in valid_target_ids:
            target = targets_by_id[target_id]
            grounded = set(getattr(target, "candidate_bsms", None) or [])
            excluded = set(getattr(target, "excluded_bsms", None) or [])
            candidate_set = candidate_sets[target_id]
            for candidate in sorted(candidate_set.candidates, key=lambda item: item.bsm):
                bsm = candidate.bsm
                if bsm not in grounded:
                    diagnostics.append(
                        _diagnostic(
                            "CANDIDATE_NOT_GROUNDED",
                            "error",
                            "Suitability candidate is not present in the target's "
                            "grounded BSM set.",
                            target_id=target_id,
                            bsm=bsm,
                        )
                    )
                    continue
                if bsm in excluded:
                    diagnostics.append(
                        _diagnostic(
                            "CANDIDATE_EXCLUDED_BY_TARGET",
                            "info",
                            "Candidate was explicitly excluded by the typed ZoneTarget.",
                            target_id=target_id,
                            bsm=bsm,
                        )
                    )
                    continue
                if not candidate.hard_feasible:
                    diagnostics.append(
                        _diagnostic(
                            "CANDIDATE_HARD_INFEASIBLE",
                            "info",
                            "Suitability evaluation marked the candidate hard-infeasible.",
                            target_id=target_id,
                            bsm=bsm,
                            constraint_codes=sorted(set(candidate.exclusion_codes)),
                        )
                    )
                    continue
                parcel = parcels_by_bsm.get(bsm)
                if parcel is None:
                    diagnostics.append(
                        _diagnostic(
                            "PARCEL_FACT_MISSING",
                            "error",
                            "Candidate BSM has no current parcel area/geometry/provenance facts.",
                            target_id=target_id,
                            bsm=bsm,
                        )
                    )
                    continue
                blocking_codes = _blocking_constraint_codes(parcel, target_id)
                if blocking_codes:
                    diagnostics.append(
                        _diagnostic(
                            "PARCEL_CONSTRAINT_BLOCKED",
                            "info",
                            "Parcel hard constraints forbid this land-use assignment.",
                            target_id=target_id,
                            bsm=bsm,
                            constraint_codes=blocking_codes,
                        )
                    )
                    continue
                effective_candidates[(target_id, bsm)] = candidate
                candidate_owners[bsm].append(target_id)

        effective_target_ids = {target_id for target_id, _ in effective_candidates}
        for target_id in sorted(set(valid_target_ids) - effective_target_ids):
            diagnostics.append(
                _diagnostic(
                    "ZONE_NO_FEASIBLE_CANDIDATE",
                    "error",
                    "Zone target has no feasible target-bound parcel candidate.",
                    target_id=target_id,
                )
            )

        for bsm in sorted(candidate_owners):
            owners = sorted(set(candidate_owners[bsm]))
            if len(owners) > 1:
                diagnostics.append(
                    _diagnostic(
                        "CANDIDATE_OWNERSHIP_CONFLICT",
                        "info",
                        "One parcel is suitable for multiple zones; "
                        "the global model resolves ownership.",
                        bsm=bsm,
                        related_target_ids=owners,
                    )
                )

        empty_balances = _empty_balances(problem.targets, problem.area_tolerance_ratio)
        model_has_errors = any(item.code in _MODEL_ERROR_CODES for item in diagnostics)
        if not valid_target_ids:
            return GlobalZoneAllocationResult(
                status="MODEL_INVALID",
                feasible=False,
                complete=False,
                area_balances=empty_balances,
                unassigned_bsms=sorted(parcels_by_bsm),
                overlay_targets=overlay_targets,
                diagnostics=diagnostics,
                input_provenance_refs=sorted(set(problem.provenance_refs)),
            )
        if not effective_candidates:
            status = "MODEL_INVALID" if model_has_errors else "INFEASIBLE"
            return GlobalZoneAllocationResult(
                status=status,
                feasible=False,
                complete=False,
                area_balances=empty_balances,
                unassigned_bsms=sorted(parcels_by_bsm),
                overlay_targets=overlay_targets,
                diagnostics=diagnostics,
                input_provenance_refs=sorted(set(problem.provenance_refs)),
            )

        try:
            import pulp
        except ImportError:
            diagnostics.append(
                _diagnostic(
                    "ZONE_SOLVER_UNAVAILABLE",
                    "error",
                    "PuLP/CBC is unavailable; allocation remains unresolved.",
                )
            )
            return GlobalZoneAllocationResult(
                status="SOLVER_UNAVAILABLE",
                feasible=False,
                complete=False,
                area_balances=empty_balances,
                unassigned_bsms=sorted(parcels_by_bsm),
                overlay_targets=overlay_targets,
                diagnostics=diagnostics,
                input_provenance_refs=sorted(set(problem.provenance_refs)),
            )

        target_order = sorted(valid_target_ids)
        candidate_order = sorted(effective_candidates)
        model = pulp.LpProblem("deterministic_global_zone_parcel_allocation", pulp.LpMinimize)
        variables = {
            key: pulp.LpVariable(f"zone_x_{index:06d}", cat=pulp.LpBinary)
            for index, key in enumerate(candidate_order)
        }
        shortfall = {
            target_id: pulp.LpVariable(f"zone_shortfall_{index:04d}", lowBound=0)
            for index, target_id in enumerate(target_order)
        }
        excess = {
            target_id: pulp.LpVariable(f"zone_excess_{index:04d}", lowBound=0)
            for index, target_id in enumerate(target_order)
        }

        bsms_to_keys: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for key in candidate_order:
            bsms_to_keys[key[1]].append(key)
        for bsm in sorted(bsms_to_keys):
            model += pulp.lpSum(variables[key] for key in bsms_to_keys[bsm]) <= 1

        for target_id in target_order:
            target = targets_by_id[target_id]
            keys = [key for key in candidate_order if key[0] == target_id]
            assigned_area = pulp.lpSum(
                parcels_by_bsm[bsm].area_ha * variables[(target_id, bsm)]
                for _, bsm in keys
            )
            model += (
                assigned_area + shortfall[target_id] - excess[target_id]
                == float(getattr(target, "area_ha", 0.0) or 0.0)
            )

        model += (
            pulp.lpSum(_DEFICIT_COST_PER_HA * shortfall[item] for item in target_order)
            + pulp.lpSum(_EXCESS_COST_PER_HA * excess[item] for item in target_order)
            - pulp.lpSum(
                _SUITABILITY_REWARD_PER_HA
                * effective_candidates[key].suitability_score
                * parcels_by_bsm[key[1]].area_ha
                * variables[key]
                for key in candidate_order
            )
            + pulp.lpSum(
                _TIE_BREAK_COST * (index + 1) * variables[key]
                for index, key in enumerate(candidate_order)
            )
        )

        try:
            solver = pulp.PULP_CBC_CMD(
                msg=False,
                threads=1,
                options=["randomSeed 0"],
            )
            model.solve(solver)
        except Exception as exc:
            diagnostics.append(
                _diagnostic(
                    "ZONE_SOLVER_ERROR",
                    "error",
                    "Global zone solver failed; no assignments were materialized.",
                    details={"exception_type": type(exc).__name__},
                )
            )
            return GlobalZoneAllocationResult(
                status="SOLVER_ERROR",
                feasible=False,
                complete=False,
                area_balances=empty_balances,
                unassigned_bsms=sorted(parcels_by_bsm),
                overlay_targets=overlay_targets,
                diagnostics=diagnostics,
                input_provenance_refs=sorted(set(problem.provenance_refs)),
            )

        solver_status = str(pulp.LpStatus.get(model.status, "Unknown"))
        if solver_status != "Optimal":
            diagnostics.append(
                _diagnostic(
                    "ZONE_ALLOCATION_INFEASIBLE",
                    "error",
                    "Global zone model did not produce an optimal feasible assignment.",
                    details={"solver_status": solver_status},
                )
            )
            return GlobalZoneAllocationResult(
                status="INFEASIBLE",
                feasible=False,
                complete=False,
                area_balances=empty_balances,
                unassigned_bsms=sorted(parcels_by_bsm),
                overlay_targets=overlay_targets,
                diagnostics=diagnostics,
                input_provenance_refs=sorted(set(problem.provenance_refs)),
            )

        assignments: list[AuthoritativeZoneParcelAssignment] = []
        for target_id, bsm in candidate_order:
            value = variables[(target_id, bsm)].value()
            if value is None or value <= 0.5:
                continue
            target = targets_by_id[target_id]
            candidate = effective_candidates[(target_id, bsm)]
            parcel = parcels_by_bsm[bsm]
            system, code, classification_evidence = classification_by_target[target_id]
            lineage = ZoneAssignmentLineage(
                lineage_id=_lineage_id(target, candidate, parcel),
                target_id=target_id,
                zone_id=str(getattr(target, "zone_id", "") or target_id),
                source_instruction_id=str(
                    getattr(target, "source_instruction_id", "") or ""
                ),
                source_report_key=str(getattr(target, "source_report_key", "") or ""),
                claim_refs=sorted(set(getattr(target, "claim_refs", None) or [])),
                classification_evidence_refs=classification_evidence,
                candidate_provenance_refs=sorted(set(candidate.provenance_refs)),
                parcel_provenance_refs=sorted(set(parcel.provenance_refs)),
                geometry_ref=parcel.geometry_ref,
                constraint_codes_considered=sorted(
                    set(constraint.code for constraint in parcel.constraints)
                ),
            )
            assignments.append(
                AuthoritativeZoneParcelAssignment(
                    target_id=target_id,
                    zone_id=str(getattr(target, "zone_id", "") or target_id),
                    bsm=bsm,
                    land_use=str(getattr(target, "land_use", "") or ""),
                    classification_system=system,
                    classification_code=code,
                    area_ha=round(parcel.area_ha, 6),
                    suitability_score=round(candidate.suitability_score, 6),
                    score_breakdown=dict(sorted(candidate.score_breakdown.items())),
                    lineage=lineage,
                )
            )
        assignments.sort(key=lambda item: (item.target_id, item.bsm))

        assigned_by_target: dict[str, float] = defaultdict(float)
        for assignment in assignments:
            assigned_by_target[assignment.target_id] += assignment.area_ha

        balances: list[ZoneAreaBalance] = []
        for target_id, target in targets_by_id.items():
            requested = max(float(getattr(target, "area_ha", 0.0) or 0.0), 0.0)
            assigned = assigned_by_target.get(target_id, 0.0)
            shortfall_value = max(requested - assigned, 0.0)
            excess_value = max(assigned - requested, 0.0)
            tolerance = requested * problem.area_tolerance_ratio
            within_tolerance = (
                shortfall_value <= tolerance + 1e-9
                and excess_value <= tolerance + 1e-9
                and target_id in valid_target_ids
            )
            balances.append(
                ZoneAreaBalance(
                    target_id=target_id,
                    zone_id=str(getattr(target, "zone_id", "") or target_id),
                    requested_area_ha=round(requested, 6),
                    assigned_area_ha=round(assigned, 6),
                    shortfall_area_ha=round(shortfall_value, 6),
                    excess_area_ha=round(excess_value, 6),
                    tolerance_area_ha=round(tolerance, 6),
                    fulfillment_ratio=(
                        round(assigned / requested, 6) if requested > 0 else 0.0
                    ),
                    within_tolerance=within_tolerance,
                )
            )
            if shortfall_value > tolerance + 1e-9:
                diagnostics.append(
                    _diagnostic(
                        "ZONE_AREA_SHORTFALL",
                        "error",
                        "Assigned parcel area is below the zone target tolerance.",
                        target_id=target_id,
                        details={
                            "requested_area_ha": round(requested, 6),
                            "assigned_area_ha": round(assigned, 6),
                            "shortfall_area_ha": round(shortfall_value, 6),
                        },
                    )
                )
            if excess_value > tolerance + 1e-9:
                diagnostics.append(
                    _diagnostic(
                        "ZONE_AREA_EXCESS",
                        "warning",
                        "Assigned parcel area exceeds the zone target tolerance.",
                        target_id=target_id,
                        details={
                            "requested_area_ha": round(requested, 6),
                            "assigned_area_ha": round(assigned, 6),
                            "excess_area_ha": round(excess_value, 6),
                        },
                    )
                )

        complete = (
            len(valid_target_ids) == len(targets_by_id)
            and all(balance.within_tolerance for balance in balances)
            and not any(item.severity == "error" for item in diagnostics)
        )
        status = "OPTIMAL" if complete else "PARTIAL"
        assigned_bsms = {assignment.bsm for assignment in assignments}
        objective_value = round(
            sum(
                assignment.area_ha * assignment.suitability_score
                for assignment in assignments
            ),
            6,
        )
        return GlobalZoneAllocationResult(
            status=status,
            feasible=True,
            complete=complete,
            assignments=assignments,
            area_balances=balances,
            unassigned_bsms=sorted(set(parcels_by_bsm) - assigned_bsms),
            overlay_targets=overlay_targets,
            objective_value=objective_value,
            diagnostics=diagnostics,
            input_provenance_refs=sorted(set(problem.provenance_refs)),
        )


def allocate_global_zone_parcels(
    problem: GlobalZoneAllocationProblem,
) -> GlobalZoneAllocationResult:
    """Functional entrypoint matching the existing adapter style."""

    return DeterministicGlobalZoneParcelAllocator().allocate(problem)


__all__ = [
    "DeterministicGlobalZoneParcelAllocator",
    "allocate_global_zone_parcels",
]
