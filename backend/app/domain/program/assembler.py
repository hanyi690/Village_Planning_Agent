"""Deterministic boundary from typed decisions to the authoritative program."""

from __future__ import annotations

from typing import Iterable

from app.contracts.program import PlanningClaim
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
    interventions_input: list[PlanningIntervention],
    dependencies: list[InterventionDependency],
    *,
    omissions: list[str] | None = None,
    evidence_gaps: list[EvidenceGap] | None = None,
    program_issues: list[ProgramIssue] | None = None,
    dimension_provenance: list[Provenance] | None = None,
    claims: list[PlanningClaim] | None = None,
) -> PlanningProgram:
    """Create ``PlanningProgram`` from canonical interventions only.

    This function is intentionally the sole canonical-intervention assembly
    point.  It does not classify, select parcels, generate geometry, or
    infer a site.  Those decisions belong to later domain stages.
    """
    issues = list(program_issues or [])
    interventions: list[PlanningIntervention] = []
    seen: set[str] = set()
    for candidate in interventions_input:
        if candidate.intervention_id in seen:
            issues.append(
                ProgramIssue(
                    stage="synthesize",
                    severity="error",
                    code="duplicate_intervention_id",
                    message=f"duplicate intervention id: {candidate.intervention_id}",
                )
            )
            continue
        seen.add(candidate.intervention_id)
        if not candidate.claim_refs and not candidate.evidence_refs:
            issues.append(
                ProgramIssue(
                    stage="synthesize",
                    severity="warning",
                    code="intervention_without_evidence",
                    message=f"intervention has no claim/evidence refs: {candidate.intervention_id}",
                )
            )
        interventions.append(
            candidate.model_copy(
                deep=True,
                update={
                    "claim_refs": _unique(candidate.claim_refs),
                    "evidence_refs": _unique(
                        candidate.evidence_refs + candidate.claim_refs
                    ),
                },
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
