"""Deterministic boundary from typed decisions to the authoritative program."""

from __future__ import annotations

from typing import Iterable

from app.contracts.program import PlanningClaim, ProgramProposal
from app.domain.allocation.model import AllocationAssignment, PortfolioDecision
from app.domain.demand.model import DemandItem, DemandPortfolio
from app.domain.program.classification import classification_program_issues
from app.domain.program.intent_spec import PlanningHumanDecision, TaskIntentSpec
from app.modules.schema.contracts.classification_ref import ClassificationDecision
from app.modules.schema.contracts.l1_contracts import EvidenceGap
from app.modules.schema.contracts.l3_contracts import (
    InterventionDependency,
    PlanningIntervention,
    PlanningProgram,
    ProgramIssue,
)
from app.modules.schema.contracts.provenance import Provenance


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


_KIND_TO_CATEGORY = {
    "project": "project",
    "facility": "facility",
    "road": "road",
    "axis": "axis",
    "zone": "zone",
    "restoration": "restoration",
    "protection": "protection",
    "action": "project",
}

_CANONICAL_OUTPUT = {
    "facility": "point",
    "road": "line",
    "axis": "line",
    "restoration": "polygon",
    "protection": "polygon",
    "zone": "polygon",
}


def _intervention_from_decisions(
    demand: DemandItem,
    assignment: AllocationAssignment,
    classification_by_target: dict[str, ClassificationDecision],
    human: PlanningHumanDecision | None,
) -> PlanningIntervention:
    kind = demand.kind
    expected = _CANONICAL_OUTPUT.get(kind, demand.geometry_kind)
    execution_mode = "non_spatial" if expected == "action" else "spatial"
    target_id = assignment.target_id or demand.target_id
    scale = (
        f"{demand.quantity:g} {demand.quantity_unit}"
        if demand.quantity is not None and demand.quantity_unit
        else ""
    )
    if human is not None and human.scale:
        scale = human.scale
    spatial_requirements = dict(demand.spatial_requirements)
    if human is not None:
        spatial_requirements.update(human.spatial_requirements)
    return PlanningIntervention(
        intervention_id=demand.demand_id,
        name=human.name if human is not None and human.name else f"{target_id}:{kind}",
        target_id=target_id,
        execution_mode=execution_mode,
        expected_output_kind=expected,
        category=_KIND_TO_CATEGORY[kind],
        scale=scale,
        area_range_ha=human.area_range_ha if human is not None else None,
        implementation_phase=(
            human.implementation_phase if human is not None else demand.phase
        ),
        spatial_requirements=spatial_requirements,
        constraints=list(human.constraints) if human is not None else [],
        claim_refs=list(demand.claim_refs),
        evidence_refs=list(demand.evidence_refs),
        classification_decision=classification_by_target.get(target_id),
    )


def _dependencies_from_intent_specs(
    intent_specs: list[TaskIntentSpec] | None,
    target_to_intervention: dict[str, str],
    valid_ids: set[str],
) -> tuple[list[ProgramIssue], list[InterventionDependency]]:
    issues: list[ProgramIssue] = []
    deps: list[InterventionDependency] = []
    for spec in intent_specs or []:
        to_id = target_to_intervention.get(spec.target_id)
        if to_id is None:
            issues.append(
                ProgramIssue(
                    stage="synthesize",
                    severity="error",
                    code="intent_spec_unknown_target",
                    message=f"intent spec target not in program: {spec.target_id}",
                )
            )
            continue
        for dep in spec.deps:
            from_id = target_to_intervention.get(dep, dep)
            if from_id not in valid_ids:
                continue
            deps.append(
                InterventionDependency(
                    from_intervention_id=from_id,
                    to_intervention_id=to_id,
                    dependency_type="task_dependency",
                )
            )
    return issues, deps


def _unique_dependencies(
    dependencies: list[InterventionDependency],
) -> list[InterventionDependency]:
    seen: set[tuple[str, str]] = set()
    out: list[InterventionDependency] = []
    for dep in dependencies:
        key = (dep.from_intervention_id, dep.to_intervention_id)
        if key not in seen:
            seen.add(key)
            out.append(dep)
    return out


def assemble_program_from_decisions(
    demand_portfolio: DemandPortfolio,
    portfolio_decision: PortfolioDecision,
    classification_decisions: list[ClassificationDecision],
    *,
    human_decisions: list[PlanningHumanDecision] | None = None,
    intent_specs: list[TaskIntentSpec] | None = None,
    dependencies: list[InterventionDependency] | None = None,
    claims: list[PlanningClaim] | None = None,
    omissions: list[str] | None = None,
    evidence_gaps: list[EvidenceGap] | None = None,
    program_issues: list[ProgramIssue] | None = None,
    dimension_provenance: list[Provenance] | None = None,
) -> PlanningProgram:
    """Assemble the authoritative program from typed decisions only.

    Object kind, classification, and geometry expectation come exclusively
    from ``DemandItem.kind``/``geometry_kind``, the ``PortfolioDecision``
    assignment, and resolved ``ClassificationDecision`` objects.  Claim text
    and report text are never read here.
    """

    issues = list(program_issues or [])
    classification_by_target = {
        decision.target_id: decision for decision in classification_decisions
    }
    human_by_target = {
        decision.target_id: decision for decision in (human_decisions or [])
    }
    assignment_by_demand = {
        assignment.demand_id: assignment for assignment in portfolio_decision.assignments
    }

    interventions: list[PlanningIntervention] = []
    for demand in demand_portfolio.demands:
        assignment = assignment_by_demand.get(demand.demand_id)
        if assignment is None or assignment.status in {"unplaced", "deferred"}:
            reason = assignment.reason if assignment is not None else "no assignment"
            issues.append(
                ProgramIssue(
                    stage="synthesize",
                    severity="error",
                    code="demand_not_allocated",
                    message=f"demand not allocated: {demand.demand_id} ({reason})",
                )
            )
            continue
        human = human_by_target.get(demand.target_id)
        if human is not None and not human.approved:
            issues.append(
                ProgramIssue(
                    stage="synthesize",
                    severity="warning",
                    code="human_rejected_target",
                    message=f"target rejected by human decision: {demand.target_id}",
                )
            )
            continue
        expected = _CANONICAL_OUTPUT.get(demand.kind)
        if expected is not None and expected != demand.geometry_kind:
            issues.append(
                ProgramIssue(
                    stage="synthesize",
                    severity="warning",
                    code="geometry_kind_normalized",
                    message=(
                        f"demand {demand.demand_id} geometry_kind "
                        f"{demand.geometry_kind!r} normalized to {expected!r}"
                    ),
                )
            )
        interventions.append(
            _intervention_from_decisions(
                demand, assignment, classification_by_target, human
            )
        )

    provisional = PlanningProgram(interventions=interventions)
    issues.extend(classification_program_issues(provisional))
    valid_ids = {item.intervention_id for item in interventions}
    target_to_intervention = {
        item.target_id: item.intervention_id for item in interventions
    }
    dep_issues, derived_deps = _dependencies_from_intent_specs(
        intent_specs, target_to_intervention, valid_ids
    )
    issues.extend(dep_issues)
    filtered_dependencies = [
        dep
        for dep in (dependencies or [])
        if dep.from_intervention_id in valid_ids
        and dep.to_intervention_id in valid_ids
    ]
    dependencies = _unique_dependencies(filtered_dependencies + derived_deps)

    return PlanningProgram(
        interventions=interventions,
        claims=list(claims or []),
        dependencies=dependencies,
        omissions=_unique(omissions or []),
        evidence_gaps=list(evidence_gaps or []),
        program_issues=issues,
        dimension_provenance=list(dimension_provenance or []),
    )


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


__all__ = ["assemble_planning_program", "assemble_program_from_decisions"]
