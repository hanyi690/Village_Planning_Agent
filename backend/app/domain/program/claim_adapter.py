"""Deterministic adapter from non-executable claims to proposal candidates."""

from __future__ import annotations

from app.contracts.program import PlanningClaim, ProgramProposal


def proposals_from_claims(
    claims: list[PlanningClaim],
    *,
    dimension_key: str = "",
) -> list[ProgramProposal]:
    """Create non-authoritative candidates without creating a planning target.

    Claims may suggest an intervention category and geometry, but this adapter
    never creates a BSM, classification decision, geometry, or final program.
    Missing evidence is retained on the proposal and is handled by the later
    domain gates.
    """

    proposals: list[ProgramProposal] = []
    for claim in claims:
        name = str(
            (claim.suggested_interventions[0] if claim.suggested_interventions else "")
            or claim.statement[:80]
        ).strip()
        if not name:
            continue
        category = "project" if claim.suggested_category == "action" else claim.suggested_category
        execution_mode = "non_spatial" if claim.suggested_output_kind == "action" else "spatial"
        spatial_requirements = {
            "location": "、".join(claim.location_hints),
            "location_hints": list(claim.location_hints),
            "affected_parcel_refs": list(claim.affected_parcel_refs),
        }
        proposals.append(
            ProgramProposal(
                proposal_id=f"{dimension_key or claim.dimension_key}:claim:{claim.claim_id}",
                name=name,
                category=category,
                execution_mode=execution_mode,
                expected_output_kind=claim.suggested_output_kind,
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
                facility_parameters=claim.facility_parameters,
                axis_parameters=claim.axis_parameters,
                polygon_parameters=claim.polygon_parameters,
                project_parameters=claim.project_parameters,
                implementation_phase=claim.implementation_phase,
                spatial_requirements=spatial_requirements,
                constraints=list(claim.constraint_refs),
                claim_refs=[claim.claim_id],
                evidence_refs=list(claim.evidence_refs),
                source_ref=claim.claim_id,
            )
        )
    return proposals


__all__ = ["proposals_from_claims"]
