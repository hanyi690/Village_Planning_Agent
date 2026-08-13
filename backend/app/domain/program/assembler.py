"""Deterministic boundary from typed decisions to the authoritative program."""

from __future__ import annotations

from typing import Iterable

from app.contracts.program import PlanningClaim, ProgramProposal
from app.domain.program.classification import classification_program_issues
from app.contracts.domain.l1_contracts import EvidenceGap
from app.contracts.domain.l3_contracts import (
    InterventionDependency,
    PlanningIntervention,
    PlanningProgram,
    ProgramIssue,
)
from app.contracts.artifacts.provenance import Provenance


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def assemble_planning_program(
    proposals: list[ProgramProposal],
    dependencies: list[InterventionDependency],
    *,
    omissions: list[str] | None = None,
    evidence_gaps: list[EvidenceGap] | None = None,
    program_issues: list[ProgramIssue] | None = None,
    dimension_provenance: list[Provenance] | None = None,
    claims: list[PlanningClaim] | None = None,
) -> PlanningProgram:
    """Create ``PlanningProgram`` from validated proposals only.

    This function is intentionally the sole proposal-to-program conversion
    point.  It does not classify, select parcels, generate geometry, or
    infer a site.  Those decisions belong to later domain stages.
    """
    issues = list(program_issues or [])
    interventions: list[PlanningIntervention] = []
    seen: set[str] = set()
    for proposal in proposals:
        if proposal.proposal_id in seen:
            issues.append(
                ProgramIssue(
                    stage="synthesize",
                    severity="error",
                    code="duplicate_proposal_id",
                    message=f"duplicate proposal id: {proposal.proposal_id}",
                )
            )
            continue
        seen.add(proposal.proposal_id)
        if not proposal.claim_refs and not proposal.evidence_refs:
            issues.append(
                ProgramIssue(
                    stage="synthesize",
                    severity="warning",
                    code="proposal_without_evidence",
                    message=f"proposal has no claim/evidence refs: {proposal.proposal_id}",
                )
            )
        interventions.append(
            PlanningIntervention(
                intervention_id=proposal.proposal_id,
                name=proposal.name,
                execution_mode=proposal.execution_mode,
                expected_output_kind=proposal.expected_output_kind,
                category=proposal.category,
                problem_addressed=proposal.problem_addressed,
                scale=proposal.scale,
                area_range_ha=proposal.area_range_ha,
                intervention_action=proposal.intervention_action,
                materialization_role=proposal.materialization_role,
                road_parameters=proposal.road_parameters,
                facility_parameters=proposal.facility_parameters,
                axis_parameters=proposal.axis_parameters,
                polygon_parameters=proposal.polygon_parameters,
                project_parameters=proposal.project_parameters,
                functions=list(proposal.functions),
                service_population=proposal.service_population,
                implementation_phase=proposal.implementation_phase,
                spatial_requirements=dict(proposal.spatial_requirements),
                constraints=list(proposal.constraints),
                claim_refs=_unique(proposal.claim_refs),
                evidence_refs=_unique(proposal.evidence_refs + proposal.claim_refs),
            )
        )
    valid_ids = {item.intervention_id for item in interventions}
    provisional_program = PlanningProgram(interventions=interventions)
    issues.extend(classification_program_issues(provisional_program))
    dependencies = [
        dependency
        for dependency in dependencies
        if dependency.from_intervention_id in valid_ids
        and dependency.to_intervention_id in valid_ids
    ]
    return PlanningProgram(
        interventions=interventions,
        claims=list(claims or []),
        dependencies=dependencies,
        omissions=_unique(omissions or []),
        evidence_gaps=list(evidence_gaps or []),
        program_issues=issues,
        dimension_provenance=list(dimension_provenance or []),
    )


__all__ = ["assemble_planning_program"]
