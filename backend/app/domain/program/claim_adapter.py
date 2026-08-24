"""Deterministic admission and adaptation of claims to spatial interventions."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from typing import Iterable

from app.contracts.program import PlanningClaim
from app.contracts.domain.l3_contracts import PlanningIntervention, ProgramIssue


_PARAMETER_FIELDS = {
    "facility": "facility_parameters",
    "axis": "axis_parameters",
    "road": "road_parameters",
    "zone": "polygon_parameters",
    "restoration": "polygon_parameters",
    "protection": "polygon_parameters",
    "site_area": "site_area_parameters",
}


def canonical_package_intervention_id(
    package_ref: str,
    category: str,
    output_kind: str,
    asset_kind: str,
    materialization_role: str,
) -> str:
    """Return a delimiter-safe, collision-resistant package target ID."""
    variant = json.dumps(
        {
            "asset_kind": asset_kind,
            "category": category,
            "materialization_role": materialization_role,
            "output_kind": output_kind,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(variant).hexdigest()[:16]
    package_digest = hashlib.sha256(package_ref.encode("utf-8")).hexdigest()[:16]
    return f"package:{package_digest}:{digest}"


def is_admitted_intervention(intervention: PlanningIntervention) -> bool:
    """Check the explicit lineage contract required before target projection."""
    return bool(
        intervention.planning_role == "spatial_intervention"
        and intervention.project_package_ref
        and intervention.admission_reason == "typed_spatial_claim_ready"
        and intervention.claim_refs
        and (
            intervention.evidence_refs
            or intervention.source_fact_refs
            or intervention.source_refs
        )
    )


def admission_reasons_for_intervention(
    intervention: PlanningIntervention,
    claims: list[PlanningClaim],
) -> list[str]:
    """Recompute intervention admission from matching original claims."""
    reasons: list[str] = []
    if not is_admitted_intervention(intervention):
        reasons.append("explicit intervention admission lineage is incomplete")
    claims_by_id = {claim.claim_id: claim for claim in claims}
    matched = [claims_by_id[claim_id] for claim_id in intervention.claim_refs if claim_id in claims_by_id]
    missing = [claim_id for claim_id in intervention.claim_refs if claim_id not in claims_by_id]
    if missing:
        reasons.append("matching program claims are missing: " + ",".join(sorted(missing)))
    if not matched:
        reasons.append("intervention has no matching program claim")
        return list(dict.fromkeys(reasons))
    for claim in matched:
        claim_reasons = _admission_reasons(claim)
        if claim_reasons:
            reasons.append(f"claim {claim.claim_id} readiness failed: {'; '.join(claim_reasons)}")
        expected_role = _effective_materialization_role(claim)
        if claim.project_package_ref != intervention.project_package_ref:
            reasons.append(f"claim {claim.claim_id} package identity does not match intervention")
        if claim.suggested_category != intervention.category:
            reasons.append(f"claim {claim.claim_id} category does not match intervention")
        if claim.suggested_output_kind != intervention.expected_output_kind:
            reasons.append(f"claim {claim.claim_id} output kind does not match intervention")
        if claim.asset_kind != intervention.asset_kind:
            reasons.append(f"claim {claim.claim_id} asset kind does not match intervention")
        if expected_role != (intervention.materialization_role or ""):
            reasons.append(f"claim {claim.claim_id} materialization role does not match intervention")
    parameter_field = _PARAMETER_FIELDS.get(intervention.category, "")
    if intervention.category == "road" and intervention.asset_kind != "road":
        parameter_field = "linear_parameters"
    if parameter_field == "site_area_parameters":
        parameter_present = intervention.site_area_parameters is not None
    else:
        parameter_present = bool(parameter_field and getattr(intervention, parameter_field, None) is not None)
    if not parameter_present:
        reasons.append("admitted intervention is missing its typed parameter block")
    return list(dict.fromkeys(reasons))


def _issue(
    claim: PlanningClaim,
    code: str,
    reason: str,
    *,
    severity: str = "error",
    dimension_key: str = "",
) -> ProgramIssue:
    return ProgramIssue(
        stage="l3",
        dimension_key=dimension_key or claim.dimension_key,
        claim_id=claim.claim_id,
        claim_ids=[claim.claim_id],
        dimension_keys=[dimension_key or claim.dimension_key],
        severity=severity,
        code=code,
        message=f"claim {claim.claim_id} is not executable: {reason}",
        detail=reason,
        reason=reason,
    )


def _typed_parameter_present(claim: PlanningClaim) -> bool:
    field_name = _PARAMETER_FIELDS.get(claim.suggested_category)
    if field_name == "road_parameters" and claim.asset_kind != "road":
        field_name = "linear_parameters"
    if field_name == "site_area_parameters":
        return claim.site_area_parameters is not None
    return bool(field_name and getattr(claim, field_name, None) is not None)


def _typed_locator_present(claim: PlanningClaim) -> bool:
    if claim.location_hints or claim.affected_parcel_refs:
        return True
    if claim.source_fact_refs:
        return True
    for parameter_name in ("road_parameters", "linear_parameters", "axis_parameters"):
        parameters = getattr(claim, parameter_name, None)
        if parameters is not None and any(
            getattr(parameters, field, None)
            for field in ("alignment_refs", "reference_features", "connects")
        ):
            return True
    return False


def _typed_completion_present(claim: PlanningClaim) -> bool:
    parameters = getattr(
        claim,
        _PARAMETER_FIELDS.get(claim.suggested_category, ""),
        None,
    )
    if claim.suggested_category == "road" and claim.asset_kind != "road":
        parameters = claim.linear_parameters
    if claim.suggested_category == "site_area":
        parameters = claim.site_area_parameters
    if parameters is None:
        return False
    if claim.suggested_category == "facility":
        return bool(parameters.facility_type.strip())
    if claim.suggested_category == "axis":
        return bool(
            parameters.direction.strip()
            or parameters.reference_features
            or parameters.connects
        )
    if claim.suggested_category in {"road", "site_area"}:
        return bool(
            getattr(parameters, "action", "")
            and (
                getattr(parameters, "alignment_refs", None)
                or getattr(parameters, "connects", None)
                or getattr(parameters, "site_type", "")
                or getattr(parameters, "footprint_area_m2", None)
                or getattr(parameters, "length_m", None)
            )
        )
    return True


def _effective_materialization_role(claim: PlanningClaim) -> str:
    if claim.materialization_role:
        return claim.materialization_role
    parameters = claim.polygon_parameters
    return str(getattr(parameters, "materialization_role", "") or "")


def _admission_reasons(claim: PlanningClaim) -> list[str]:
    reasons: list[str] = []
    if claim.planning_role != "spatial_intervention":
        return reasons
    if not claim.project_package_ref.strip():
        reasons.append("project_package_ref is required")
    if claim.suggested_output_kind == "action":
        reasons.append("spatial intervention cannot use action output")
    if not _typed_parameter_present(claim):
        reasons.append("the category-specific typed parameter block is missing")
    elif not _typed_completion_present(claim):
        reasons.append("typed action/completion semantics are incomplete")
    if (
        claim.suggested_category in {"site_area", "zone", "restoration", "protection"}
        and not _effective_materialization_role(claim)
    ):
        reasons.append("materialization_role is required for this spatial category")
    if not _typed_locator_present(claim):
        reasons.append("locator, candidate, or source-feature reference is missing")
    if not (claim.evidence_refs or claim.source_fact_refs or claim.source_refs):
        reasons.append("evidence/source-fact lineage is missing")
    return reasons


def interventions_from_claims(
    claims: list[PlanningClaim],
    *,
    dimension_key: str = "",
    issues: list[ProgramIssue] | None = None,
) -> list[PlanningIntervention]:
    """Admit only explicitly typed, evidence-lined spatial interventions."""
    interventions: list[PlanningIntervention] = []
    issue_list = issues if issues is not None else []
    for claim in claims:
        if claim.planning_role != "spatial_intervention":
            issue_list.append(
                _issue(
                    claim,
                    "claim_not_executable",
                    f"planning_role={claim.planning_role} is evidence-only",
                    severity="info",
                    dimension_key=dimension_key,
                )
            )
            continue
        reasons = _admission_reasons(claim)
        if reasons:
            issue_list.append(
                _issue(
                    claim,
                    "claim_admission_incomplete",
                    "; ".join(reasons),
                    dimension_key=dimension_key,
                )
            )
            continue
        name = str(
            (claim.suggested_interventions[0] if claim.suggested_interventions else "")
            or claim.statement[:80]
        ).strip()
        if not name:
            issue_list.append(
                _issue(
                    claim,
                    "claim_admission_incomplete",
                    "intervention name is missing",
                    dimension_key=dimension_key,
                )
            )
            continue
        effective_dimension = dimension_key or claim.dimension_key
        package_ref = claim.project_package_ref.strip()
        materialization_role = _effective_materialization_role(claim)
        intervention_id = f"{effective_dimension}:claim:{claim.claim_id}"
        spatial_requirements = {
            "location": "、".join(claim.location_hints),
            "location_hints": list(claim.location_hints),
            "affected_parcel_refs": list(claim.affected_parcel_refs),
            "source_feature_refs": list(claim.affected_parcel_refs),
            "source_fact_refs": list(claim.source_fact_refs),
            "source_refs": list(claim.source_refs),
            "spatial_evidence_status": "l1_fact_bound" if claim.source_fact_refs else "evidence_bound",
            "admitted_dimension": effective_dimension,
        }
        declared_spatial_requirements = claim.spatial_requirements
        if declared_spatial_requirements is not None:
            spatial_requirements.update(
                declared_spatial_requirements.model_dump(
                    mode="json",
                    exclude_none=True,
                )
            )
            # Relation templates are compiled after TARGET has stable target
            # IDs.  Keep the claim's evidence lineage attached to every
            # semantic relation while leaving geometry binding to GROUND.
            for relation in spatial_requirements.get("relations", []) or []:
                if not isinstance(relation, dict):
                    continue
                if not relation.get("subject_ref"):
                    relation["subject_ref"] = intervention_id
                relation["claim_refs"] = list(dict.fromkeys([
                    *[str(value) for value in relation.get("claim_refs", []) if str(value).strip()],
                    claim.claim_id,
                ]))
                relation["evidence_refs"] = list(dict.fromkeys([
                    *[str(value) for value in relation.get("evidence_refs", []) if str(value).strip()],
                    *claim.evidence_refs,
                ]))
                relation["source_claim_refs"] = list(dict.fromkeys([
                    *[str(value) for value in relation.get("source_claim_refs", []) if str(value).strip()],
                    claim.claim_id,
                ]))
        # An explicit source-parcel locator is also a typed shared-resource
        # fact for parcel-backed site footprints.  Preserve it for TARGET
        # projection instead of leaving the compiler to rediscover coupling
        # from candidate geometry after alternatives have already been lost.
        if claim.affected_parcel_refs and claim.suggested_category in {"site_area", "zone"}:
            parcel_refs = list(dict.fromkeys(
                str(ref) for ref in claim.affected_parcel_refs if str(ref).strip()
            ))
            spatial_requirements["parcel_membership_refs"] = parcel_refs
            if materialization_role in {"site_footprint", "land_use_assignment"}:
                spatial_requirements["shared_resource_refs"] = parcel_refs
        interventions.append(
            PlanningIntervention(
                intervention_id=intervention_id,
                name=name,
                target_id=intervention_id,
                planning_role="spatial_intervention",
                project_package_ref=package_ref,
                admission_reason="typed_spatial_claim_ready",
                category=claim.suggested_category,
                execution_mode="spatial",
                expected_output_kind=claim.suggested_output_kind,
                asset_kind=claim.asset_kind,
                problem_addressed=claim.statement,
                scale=(
                    f"{claim.quantity:g} {claim.quantity_unit}"
                    if claim.quantity is not None and claim.quantity_unit
                    else ""
                ),
                area_range_ha=claim.area_range_ha,
                intervention_action=claim.intervention_action,
                materialization_role=materialization_role or None,
                road_parameters=claim.road_parameters,
                linear_parameters=claim.linear_parameters,
                facility_parameters=claim.facility_parameters,
                axis_parameters=claim.axis_parameters,
                polygon_parameters=claim.polygon_parameters,
                site_area_parameters=claim.site_area_parameters,
                implementation_phase=claim.implementation_phase,
                spatial_requirements=spatial_requirements,
                constraints=list(claim.constraint_refs),
                objective_refs=list(claim.objective_refs),
                claim_refs=[claim.claim_id],
                evidence_refs=list(claim.evidence_refs),
                source_fact_refs=list(claim.source_fact_refs),
                source_refs=list(claim.source_refs),
            )
        )
    return interventions


def _merge_values(first: list[str], second: Iterable[str]) -> list[str]:
    return list(dict.fromkeys([*first, *(item for item in second if item)]))


def compact_interventions(interventions: list[PlanningIntervention]) -> tuple[list[PlanningIntervention], list[ProgramIssue]]:
    """Compact same-package compatible members with stable IDs."""
    admitted: list[PlanningIntervention] = []
    issues: list[ProgramIssue] = []
    for intervention in interventions:
        if is_admitted_intervention(intervention):
            admitted.append(intervention)
            continue
        issues.append(
            ProgramIssue(
                stage="l3",
                severity="error",
                code="direct_intervention_not_admitted",
                message="intervention is diagnostic-only until claim admission succeeds",
                detail=intervention.intervention_id,
                reason="missing explicit role/package/admission/evidence lineage",
            )
        )
    interventions = admitted
    groups: dict[tuple[str, str, str, str, str], list[PlanningIntervention]] = defaultdict(list)
    for intervention in interventions:
        key = (
            intervention.project_package_ref,
            intervention.category,
            intervention.expected_output_kind,
            intervention.asset_kind,
            intervention.materialization_role or "",
        )
        groups[key].append(intervention)
    compacted: list[PlanningIntervention] = []
    package_outputs: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
    for intervention in interventions:
        package_outputs[intervention.project_package_ref].add(
            (
                intervention.category,
                intervention.expected_output_kind,
                intervention.asset_kind,
                intervention.materialization_role or "",
            )
        )
    for package_ref, variants in package_outputs.items():
        if package_ref and len(variants) > 1:
            first = min(
                (item for item in interventions if item.project_package_ref == package_ref),
                key=lambda item: (item.spatial_requirements.get("admitted_dimension", ""), item.intervention_id),
            )
            issues.append(
                ProgramIssue(
                    stage="l3",
                    dimension_key=first.spatial_requirements.get("admitted_dimension", ""),
                    severity="warning",
                    code="package_requires_split",
                    claim_ids=sorted(
                        claim_id
                        for item in interventions
                        if item.project_package_ref == package_ref
                        for claim_id in item.claim_refs
                    ),
                    dimension_keys=sorted(
                        {
                            item.spatial_requirements.get("admitted_dimension", "")
                            for item in interventions
                            if item.project_package_ref == package_ref
                        }
                        - {""}
                    ),
                    message=f"package {package_ref} contains incompatible spatial output members",
                    detail="; ".join("/".join(item) for item in sorted(variants)),
                    reason="compatible geometry/output semantics are required for compaction",
                )
            )
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda item: (tuple(item.claim_refs), item.intervention_id))
        canonical = members[0].model_copy(deep=True)
        package_ref = key[0]
        if package_ref:
            canonical.intervention_id = canonical_package_intervention_id(
                package_ref,
                key[1],
                key[2],
                key[3],
                key[4],
            )
            canonical.target_id = canonical.intervention_id
        for member in members[1:]:
            canonical.claim_refs = _merge_values(canonical.claim_refs, member.claim_refs)
            canonical.evidence_refs = _merge_values(canonical.evidence_refs, member.evidence_refs)
            canonical.source_fact_refs = _merge_values(canonical.source_fact_refs, member.source_fact_refs)
            canonical.source_refs = _merge_values(canonical.source_refs, member.source_refs)
            canonical.objective_refs = _merge_values(canonical.objective_refs, member.objective_refs)
            canonical.constraints = _merge_values(canonical.constraints, member.constraints)
            for field in (
                "location_hints",
                "affected_parcel_refs",
                "source_feature_refs",
                "source_fact_refs",
                "source_refs",
            ):
                canonical.spatial_requirements[field] = _merge_values(
                    list(canonical.spatial_requirements.get(field, [])),
                    member.spatial_requirements.get(field, []),
                )
        compacted.append(canonical)
    return compacted, issues


__all__ = [
    "canonical_package_intervention_id",
    "compact_interventions",
    "admission_reasons_for_intervention",
    "is_admitted_intervention",
    "interventions_from_claims",
]
