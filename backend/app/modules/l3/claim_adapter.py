"""Deterministic admission and adaptation of claims to spatial interventions."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from collections.abc import Mapping
from typing import Iterable

from app.contracts.l3.program import PlanningClaim
from app.contracts.l3.l3_contracts import (
    ClaimDisposition,
    L3CandidateRequestRow,
    L3SpatialRequirementRow,
    L3TargetRow,
    PlanningIntervention,
    ProgramIssue,
)


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
    """Check semantic readiness before TARGET assigns a physical package."""
    return bool(
        intervention.planning_role == "spatial_intervention"
        and intervention.admission_reason == "typed_spatial_claim_ready"
        and intervention.claim_refs
        and (intervention.objective_refs or intervention.constraints)
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
        if (
            claim.project_package_ref
            and claim.project_package_ref != intervention.project_package_ref
        ):
            reasons.append(f"claim {claim.claim_id} package identity does not match intervention")
        if claim.suggested_category != intervention.category:
            reasons.append(f"claim {claim.claim_id} category does not match intervention")
        if claim.suggested_output_kind != intervention.expected_output_kind:
            reasons.append(f"claim {claim.claim_id} output kind does not match intervention")
        if claim.asset_kind != intervention.asset_kind:
            reasons.append(f"claim {claim.claim_id} asset kind does not match intervention")
        if expected_role != (intervention.materialization_role or ""):
            reasons.append(f"claim {claim.claim_id} materialization role does not match intervention")
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


def _effective_materialization_role(claim: PlanningClaim) -> str:
    if claim.materialization_role:
        return claim.materialization_role
    derived = {
        "site_area": "site_footprint",
        "protection": "protection_overlay",
        "restoration": "restoration_overlay",
    }.get(claim.suggested_category, "")
    if derived:
        return derived
    parameters = claim.polygon_parameters
    return str(getattr(parameters, "materialization_role", "") or "")


def _admission_reasons(claim: PlanningClaim) -> list[str]:
    reasons: list[str] = []
    if claim.planning_role != "spatial_intervention":
        return reasons
    if claim.suggested_output_kind == "action":
        reasons.append("spatial intervention cannot use action output")
    if (
        claim.suggested_category in {"site_area", "zone", "restoration", "protection"}
        and not _effective_materialization_role(claim)
    ):
        reasons.append("materialization_role is required for this spatial category")
    if not (claim.objective_refs or claim.constraint_refs):
        reasons.append("L2 objective/rule lineage is missing")
    if not (claim.evidence_refs or claim.source_fact_refs or claim.source_refs):
        reasons.append("evidence/source-fact lineage is missing")
    return reasons


_PENDING_REQUIREMENTS_BY_REASON = {
    "evidence/source-fact lineage is missing": "evidence_or_source_lineage",
}


def classify_claims(
    claims: list[PlanningClaim],
    *,
    dimension_key: str = "",
) -> tuple[
    list[PlanningIntervention],
    list[PlanningClaim],
    list[ClaimDisposition],
    list[ProgramIssue],
]:
    """Account for every L3 claim without weakening strict intervention admission."""
    interventions: list[PlanningIntervention] = []
    pending_claims: list[PlanningClaim] = []
    dispositions: list[ClaimDisposition] = []
    issues: list[ProgramIssue] = []

    for claim in claims:
        effective_dimension = dimension_key or claim.dimension_key
        if claim.planning_role != "spatial_intervention":
            reason = f"planning_role={claim.planning_role} is evidence-only"
            interventions_from_claims(
                [claim],
                dimension_key=effective_dimension,
                issues=issues,
            )
            dispositions.append(
                ClaimDisposition(
                    claim_id=claim.claim_id,
                    dimension_key=effective_dimension,
                    status="deferred",
                    reason=reason,
                )
            )
            continue

        reasons = _admission_reasons(claim)
        missing_requirements = [
            _PENDING_REQUIREMENTS_BY_REASON[reason]
            for reason in reasons
            if reason in _PENDING_REQUIREMENTS_BY_REASON
        ]
        if reasons and len(missing_requirements) == len(reasons):
            reason = "; ".join(reasons)
            issue_reason = (
                f"{reason}; missing_requirements={','.join(missing_requirements)}"
            )
            pending_claims.append(claim)
            dispositions.append(
                ClaimDisposition(
                    claim_id=claim.claim_id,
                    dimension_key=effective_dimension,
                    status="pending_grounding",
                    reason=reason,
                    missing_requirements=missing_requirements,
                )
            )
            issues.append(
                _issue(
                    claim,
                    "claim_grounding_pending",
                    issue_reason,
                    severity="warning",
                    dimension_key=effective_dimension,
                )
            )
            continue

        claim_issues: list[ProgramIssue] = []
        admitted = interventions_from_claims(
            [claim],
            dimension_key=effective_dimension,
            issues=claim_issues,
        )
        interventions.extend(admitted)
        issues.extend(claim_issues)
        if admitted:
            dispositions.append(
                ClaimDisposition(
                    claim_id=claim.claim_id,
                    dimension_key=effective_dimension,
                    status="admitted",
                    reason="typed_spatial_claim_ready",
                )
            )
            continue

        reason = "; ".join(reasons) or "; ".join(
            issue.reason or issue.detail or issue.message for issue in claim_issues
        )
        dispositions.append(
            ClaimDisposition(
                claim_id=claim.claim_id,
                dimension_key=effective_dimension,
                status="invalid",
                reason=reason,
                missing_requirements=missing_requirements,
            )
        )
    return interventions, pending_claims, dispositions, issues


def interventions_from_claims(
    claims: list[PlanningClaim],
    *,
    dimension_key: str = "",
    issues: list[ProgramIssue] | None = None,
) -> list[PlanningIntervention]:
    """Admit semantic, evidence-lined targets without doing GROUND work."""
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
            "source_fact_refs": list(claim.source_fact_refs),
            "grounding_requirements": list(
                getattr(claim.spatial_requirements, "grounding_requirements", None)
                or []
            ),
            "spatial_evidence_status": (
                "l1_fact_referenced" if claim.source_fact_refs else "evidence_referenced"
            ),
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
        interventions.append(
            PlanningIntervention(
                intervention_id=intervention_id,
                name=name,
                target_id=intervention_id,
                planning_role="spatial_intervention",
                project_package_ref=package_ref,
                variant_key=str(claim.variant_key or ""),
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


def build_l3_product_rows(
    interventions: list[PlanningIntervention],
) -> tuple[
    list[L3TargetRow],
    list[L3SpatialRequirementRow],
    list[L3CandidateRequestRow],
]:
    """Project admitted interventions into the flat authoritative L3 rows."""

    targets: list[L3TargetRow] = []
    requirements: list[L3SpatialRequirementRow] = []
    requests: list[L3CandidateRequestRow] = []
    for intervention in interventions:
        target_ref = intervention.target_id or intervention.intervention_id
        l2_refs = list(dict.fromkeys([
            *intervention.objective_refs,
            *intervention.constraints,
        ]))
        evidence_refs = list(dict.fromkeys([
            *intervention.evidence_refs,
            *intervention.source_refs,
        ]))
        source_fact_refs = list(dict.fromkeys(intervention.source_fact_refs))
        spatial = dict(intervention.spatial_requirements or {})
        location_hints = list(dict.fromkeys(
            str(value)
            for value in spatial.get("location_hints", [])
            if str(value).strip()
        ))
        declared_grounding = list(dict.fromkeys(
            str(value)
            for value in spatial.get("grounding_requirements", [])
            if str(value).strip()
        ))
        category = intervention.category
        if category == "facility":
            representation_type = "point"
            purpose = "point_location"
            capabilities = ["facility.placement"]
            entity_types = ["facility", "site"]
            defaults = ["place_binding", "candidate_geometry", "demand_points"]
        elif category == "road":
            representation_type = "line"
            purpose = "centerline"
            capability = (
                "road.construction"
                if intervention.asset_kind == "road"
                else f"linear.{intervention.asset_kind}"
            )
            capabilities = [capability]
            entity_types = ["road", "linear_network"]
            defaults = ["place_binding", "candidate_geometry", "network_snapshot", "topology"]
        elif category == "axis":
            representation_type = "line"
            purpose = "corridor"
            capabilities = ["axis.construction"]
            entity_types = ["planning_axis", "linear_network"]
            defaults = ["place_binding", "candidate_geometry", "network_snapshot", "topology"]
        else:
            representation_type = "polygon"
            purpose = str(intervention.materialization_role or "")
            capabilities = ["land.design"]
            entity_types = ["site", "zone", "parcel"]
            defaults = ["place_binding", "candidate_geometry", "parcel_membership", "topology"]
        if not purpose:
            raise ValueError(
                f"L3 target {target_ref} has no representation purpose"
            )
        grounding = list(dict.fromkeys([*declared_grounding, *defaults]))
        candidate_request_ref = f"candidate-request:{target_ref}"
        requirement_ref = f"spatial-requirement:{target_ref}"
        targets.append(L3TargetRow(
            target_ref=target_ref,
            claim_family=category,
            subject_text=intervention.problem_addressed or intervention.name,
            operation=intervention.intervention_action,
            representation_purpose=purpose,
            required_capabilities=capabilities,
            constraint_refs=list(intervention.constraints),
            l2_refs=l2_refs,
            evidence_refs=evidence_refs,
            source_fact_refs=source_fact_refs,
            candidate_request_ref=candidate_request_ref,
        ))
        requirements.append(L3SpatialRequirementRow(
            requirement_ref=requirement_ref,
            target_ref=target_ref,
            representation_type=representation_type,
            representation_purpose=purpose,
            operation=intervention.intervention_action,
            location_hints=location_hints,
            grounding_requirements=grounding,
            required_capabilities=capabilities,
            l2_refs=l2_refs,
            evidence_refs=list(dict.fromkeys([*evidence_refs, *source_fact_refs])),
        ))
        requests.append(L3CandidateRequestRow(
            request_ref=candidate_request_ref,
            target_ref=target_ref,
            entity_type_requirements=entity_types,
            representation_type_requirements=[representation_type],
            representation_purpose=purpose,
            operation=intervention.intervention_action,
            query_terms=list(dict.fromkeys([
                intervention.name,
                category,
                *([intervention.asset_kind] if intervention.asset_kind != "none" else []),
            ])),
            location_hints=location_hints,
            constraint_refs=list(intervention.constraints),
            l2_refs=l2_refs,
            evidence_refs=list(dict.fromkeys([*evidence_refs, *source_fact_refs])),
            status=(
                "ready"
                if location_hints or source_fact_refs
                else "pending_location_evidence"
            ),
        ))
    return targets, requirements, requests


def _merge_values(first: list[str], second: Iterable[str]) -> list[str]:
    return list(dict.fromkeys([*first, *(item for item in second if item)]))


def _intervention_target_id(intervention: PlanningIntervention) -> str:
    if intervention.project_package_ref and intervention.planning_role == "spatial_intervention":
        return canonical_package_intervention_id(
            intervention.project_package_ref,
            intervention.category,
            intervention.expected_output_kind,
            intervention.asset_kind,
            intervention.materialization_role or "",
        )
    return intervention.target_id or intervention.intervention_id


def _relation_endpoint_aliases(
    interventions: Iterable[PlanningIntervention],
) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = defaultdict(set)
    for intervention in interventions:
        target_id = _intervention_target_id(intervention)
        if not target_id:
            continue
        raw_aliases = [
            intervention.intervention_id,
            intervention.target_id,
            intervention.project_package_ref,
            intervention.name,
            *intervention.claim_refs,
        ]
        dimension_key = str(
            (intervention.spatial_requirements or {}).get("admitted_dimension", "")
            if isinstance(intervention.spatial_requirements, dict)
            else ""
        ).strip()
        raw_aliases.extend(
            f"{dimension_key}:claim:{claim_id}"
            for claim_id in intervention.claim_refs
            if dimension_key and claim_id
        )
        for alias in raw_aliases:
            value = str(alias or "").strip()
            if value:
                aliases[value].add(target_id)
    return aliases


def _rewrite_relation_endpoints(
    relation: Mapping[str, object],
    *,
    canonical_target_id: str,
    aliases: dict[str, set[str]],
    issues: list[ProgramIssue],
    claim_refs: list[str],
) -> dict[str, object]:
    rewritten = dict(relation)
    subject_ref = str(rewritten.get("subject_ref") or "").strip()
    subject_targets = aliases.get(subject_ref, set())
    if not subject_ref or canonical_target_id in subject_targets or len(subject_targets) == 1:
        rewritten["subject_ref"] = canonical_target_id
    elif len(subject_targets) > 1:
        issues.append(
            ProgramIssue(
                stage="l3",
                severity="warning",
                code="relation_endpoint_alias_ambiguous",
                claim_ids=list(claim_refs),
                message=f"relation subject alias {subject_ref!r} maps to multiple canonical targets",
                detail=", ".join(sorted(subject_targets)),
                reason="the relation remains unresolved until GROUND identifies the intended target",
            )
        )

    object_ref = str(rewritten.get("object_ref") or "").strip()
    object_targets = aliases.get(object_ref, set())
    if len(object_targets) == 1:
        rewritten["object_ref"] = next(iter(object_targets))
        rewritten["object_ref_kind"] = "target"
    elif len(object_targets) > 1:
        issues.append(
            ProgramIssue(
                stage="l3",
                severity="warning",
                code="relation_endpoint_alias_ambiguous",
                claim_ids=list(claim_refs),
                message=f"relation object alias {object_ref!r} maps to multiple canonical targets",
                detail=", ".join(sorted(object_targets)),
                reason="the relation remains an explicit unresolved package reference",
            )
        )
    return rewritten


def _merged_spatial_relations(
    members: Iterable[PlanningIntervention],
    *,
    canonical_target_id: str,
    aliases: dict[str, set[str]],
    issues: list[ProgramIssue],
    claim_refs: list[str],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for member in members:
        requirements = member.spatial_requirements
        if not isinstance(requirements, dict):
            continue
        for relation in requirements.get("relations", []) or []:
            if not isinstance(relation, Mapping):
                continue
            rewritten = _rewrite_relation_endpoints(
                relation,
                canonical_target_id=canonical_target_id,
                aliases=aliases,
                issues=issues,
                claim_refs=claim_refs,
            )
            relation_id = str(rewritten.get("relation_id") or "").strip()
            key = relation_id or json.dumps(
                rewritten,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(rewritten)
    return result


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
                reason="missing explicit role/L2/admission/evidence lineage",
            )
        )
    interventions = admitted
    relation_aliases = _relation_endpoint_aliases(interventions)
    groups: dict[tuple[str, str, str, str, str, str], list[PlanningIntervention]] = defaultdict(list)
    for intervention in interventions:
        key = (
            intervention.project_package_ref,
            intervention.category,
            intervention.expected_output_kind,
            intervention.asset_kind,
            intervention.materialization_role or "",
            "" if intervention.project_package_ref else intervention.intervention_id,
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
                "source_fact_refs",
                "grounding_requirements",
            ):
                canonical.spatial_requirements[field] = _merge_values(
                    list(canonical.spatial_requirements.get(field, [])),
                    member.spatial_requirements.get(field, []),
                )
        canonical_target_id = canonical.intervention_id
        merged_relations = _merged_spatial_relations(
            members,
            canonical_target_id=canonical_target_id,
            aliases=relation_aliases,
            issues=issues,
            claim_refs=list(canonical.claim_refs),
        )
        if merged_relations:
            canonical.spatial_requirements = dict(canonical.spatial_requirements or {})
            canonical.spatial_requirements["relations"] = merged_relations
        compacted.append(canonical)
    return compacted, issues


__all__ = [
    "canonical_package_intervention_id",
    "compact_interventions",
    "admission_reasons_for_intervention",
    "is_admitted_intervention",
    "build_l3_product_rows",
    "classify_claims",
    "interventions_from_claims",
]
