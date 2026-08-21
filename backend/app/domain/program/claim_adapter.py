"""Deterministic adapter from claims to canonical planning interventions."""

from __future__ import annotations

from app.contracts.program import PlanningClaim
from app.contracts.domain.l3_contracts import PlanningIntervention


def interventions_from_claims(
    claims: list[PlanningClaim],
    *,
    dimension_key: str = "",
) -> list[PlanningIntervention]:
    """Create canonical intervention targets without creating GIS state.

    Claims may suggest an intervention category and geometry, but this adapter
    never creates a BSM, classification decision, geometry, or final program.
    Non-spatial claims remain claims and do not enter the intervention graph.
    """

    interventions: list[PlanningIntervention] = []
    for claim in claims:
        if claim.suggested_category == "action" or claim.suggested_output_kind == "action":
            continue
        name = str(
            (claim.suggested_interventions[0] if claim.suggested_interventions else "")
            or claim.statement[:80]
        ).strip()
        if not name:
            continue
        category = claim.suggested_category
        execution_mode = "spatial"
        spatial_requirements = {
            "location": "、".join(claim.location_hints),
            "location_hints": list(claim.location_hints),
            "affected_parcel_refs": list(claim.affected_parcel_refs),
            "source_fact_refs": list(claim.source_fact_refs),
            "spatial_evidence_status": (
                "l1_fact_bound"
                if claim.source_fact_refs
                else "semantic_candidate_needs_grounding"
            ),
        }
        interventions.append(
            PlanningIntervention(
                intervention_id=f"{dimension_key or claim.dimension_key}:claim:{claim.claim_id}",
                name=name,
                target_id=f"{dimension_key or claim.dimension_key}:claim:{claim.claim_id}",
                category=category,
                execution_mode=execution_mode,
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
                materialization_role=claim.materialization_role,
                road_parameters=claim.road_parameters,
                linear_parameters=claim.linear_parameters,
                facility_parameters=claim.facility_parameters,
                axis_parameters=claim.axis_parameters,
                polygon_parameters=claim.polygon_parameters,
                site_area_parameters=claim.site_area_parameters,
                implementation_phase=claim.implementation_phase,
                spatial_requirements=spatial_requirements,
                constraints=list(claim.constraint_refs),
                claim_refs=[claim.claim_id],
                evidence_refs=list(claim.evidence_refs),
            )
        )
    return interventions


__all__ = ["interventions_from_claims"]
