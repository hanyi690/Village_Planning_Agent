"""Explicit classification decisions at the program/HUMAN boundary.

Claims and project names are semantic evidence, not land-use codes.  This
module accepts only already-resolved ``ClassificationDecision`` objects and
applies them to an immutable ``PlanningProgram`` revision.  It deliberately
does not infer a code from a parcel's ``dlbm``, a name, or a crosswalk.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.contracts.artifacts.classification_ref import ClassificationDecision
from app.contracts.domain.l3_contracts import PlanningProgram, ProgramIssue


def _raw_items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, Mapping):
        items: list[dict[str, Any]] = []
        for target_id, value in raw.items():
            if not isinstance(value, Mapping):
                raise ValueError(f"classification decision for {target_id!r} must be an object")
            item = dict(value)
            item.setdefault("target_id", str(target_id))
            items.append(item)
        return items
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return [dict(item) for item in raw if isinstance(item, Mapping)]
    raise ValueError("classification_decisions must be an object keyed by target_id or a list")


def parse_classification_decisions(raw: Any) -> list[ClassificationDecision]:
    """Validate the closed-set HUMAN decision payload."""

    decisions = [ClassificationDecision.model_validate(item) for item in _raw_items(raw)]
    ids = [decision.target_id for decision in decisions]
    if len(ids) != len(set(ids)):
        raise ValueError("classification_decisions contains duplicate target_id values")
    unresolved = [decision.target_id for decision in decisions if decision.status != "resolved"]
    if unresolved:
        raise ValueError(
            "classification_decisions must contain resolved decisions only: "
            + ", ".join(unresolved)
        )
    return decisions


def classification_review_targets(program: PlanningProgram) -> list[dict[str, Any]]:
    """Return spatial targets that cannot produce a parcel change yet."""

    targets: list[dict[str, Any]] = []
    for intervention in program.interventions:
        if intervention.expected_output_kind not in {"parcel", "polygon"}:
            continue
        if intervention.materialization_role in {
            "functional_overlay",
            "protection_overlay",
            "restoration_overlay",
        }:
            continue
        decision = intervention.classification_decision
        if decision is not None and decision.status == "resolved":
            continue
        targets.append(
            {
                "target_id": intervention.target_id,
                "name": intervention.name,
                "category": intervention.category,
                "expected_output_kind": intervention.expected_output_kind,
                "claim_refs": list(intervention.claim_refs),
                # Classification must carry auditable lineage even when the L3
                # provider placed it in source_fact_refs/source_refs rather than
                # the generic evidence_refs field.
                "evidence_refs": list(dict.fromkeys([
                    *intervention.evidence_refs,
                    *intervention.source_fact_refs,
                    *intervention.source_refs,
                ])),
                "decision_required": True,
                "recommended_code_system": "ghytbm",
            }
        )
    return targets


def apply_classification_decisions(
    program: PlanningProgram,
    raw_decisions: Any,
) -> tuple[PlanningProgram, list[str]]:
    """Create a program revision with explicit decisions applied.

    Every unresolved spatial target must be included.  A partial revision is
    rejected so that the next stage cannot silently execute only the easiest
    subset and present it as a complete plan.
    """

    decisions = parse_classification_decisions(raw_decisions)
    by_target = {decision.target_id: decision for decision in decisions}
    required = classification_review_targets(program)
    required_ids = {item["target_id"] for item in required}
    missing = sorted(required_ids - set(by_target))
    unknown = sorted(set(by_target) - {item.target_id for item in program.interventions})
    if unknown:
        raise ValueError("classification decision targets are not in PlanningProgram: " + ", ".join(unknown))
    if missing:
        raise ValueError("classification decisions missing required targets: " + ", ".join(missing))

    revised = program.model_copy(deep=True)
    updated = []
    for intervention in revised.interventions:
        decision = by_target.get(intervention.target_id)
        if decision is not None:
            intervention = intervention.model_copy(update={"classification_decision": decision})
        updated.append(intervention)
    revised.interventions = updated
    revised.program_issues = [
        issue
        for issue in revised.program_issues
        if issue.code != "classification_decision_required"
    ]
    return revised, sorted(by_target)


def revise_program_with_decisions(
    program: PlanningProgram,
    raw_decisions: Any,
) -> tuple[PlanningProgram, list[str]]:
    """Apply explicit classification decisions and stamp the revision provenance.

    Thin wrapper over ``apply_classification_decisions`` that also stamps the
    HUMAN-review revision markers (artifact_id suffix and provenance trace).
    Pure construction — the caller owns CAS writes.
    """
    revised, target_ids = apply_classification_decisions(program, raw_decisions)
    revised.artifact_id = f"{program.artifact_id}:classification-revision"
    revised.provenance = (
        revised.provenance.model_copy(
            update={
                "module": "human_review",
                "trace": [*(revised.provenance.trace or []), "classification_revision"],
            }
        )
        if revised.provenance is not None
        else None
    )
    return revised, target_ids


def classification_program_issues(program: PlanningProgram) -> list[ProgramIssue]:
    """Build deterministic issues for missing execution classifications."""

    return [
        ProgramIssue(
            stage="synthesize",
            severity="error",
            code="classification_decision_required",
            message=(
                f"spatial target {item['target_id']} requires an explicit "
                "ClassificationDecision before materialization"
            ),
            detail=item["name"],
        )
        for item in classification_review_targets(program)
    ]


__all__ = [
    "apply_classification_decisions",
    "classification_program_issues",
    "classification_review_targets",
    "parse_classification_decisions",
    "revise_program_with_decisions",
]
