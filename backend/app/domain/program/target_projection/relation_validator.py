"""Static validation for typed relation intents.

This module validates only the relation declaration.  It deliberately does
not evaluate geometry.  A diagnostic is returned instead of dropping a
relation, allowing later stages to persist a hard relation as deferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.contracts.planning.intent_graph import PlanRelationIntent, PlanTargetNode
from .relation_catalog import relation_spec


@dataclass(frozen=True)
class PlanningDiagnostic:
    code: str
    message: str
    severity: str = "warning"
    relation_id: str = ""

    def __str__(self) -> str:
        suffix = f":{self.relation_id}" if self.relation_id else ""
        return f"{self.code}{suffix}:{self.message}"


def validate_relation_intent(
    relation: PlanRelationIntent,
    node_index: Mapping[str, PlanTargetNode],
) -> list[PlanningDiagnostic]:
    """Validate template, endpoints, parameter status and target kinds.

    The relation itself remains in the graph even when this returns findings.
    ``missing`` and ``invalid`` parameter statuses are durable deferred
    signals; no default distance, capacity or network is invented here.
    """

    findings: list[PlanningDiagnostic] = []
    spec = relation_spec(relation.relation_template)
    if spec is None:
        findings.append(PlanningDiagnostic(
            "unsupported_relation_template",
            f"unsupported relation template {relation.relation_template!r}",
            "error", relation.relation_id,
        ))
        return findings

    subject = node_index.get(relation.subject_ref)
    if subject is None:
        findings.append(PlanningDiagnostic(
            "relation_unknown_subject", f"unknown subject target {relation.subject_ref!r}",
            "error" if relation.criticality == "hard" else "warning", relation.relation_id,
        ))
    elif subject.target_kind not in spec.subject_kinds:
        findings.append(PlanningDiagnostic(
            "relation_subject_type_mismatch",
            f"{relation.relation_template} does not accept subject kind {subject.target_kind!r}",
            "error" if relation.criticality == "hard" else "warning", relation.relation_id,
        ))

    if relation.object_ref_kind not in spec.object_ref_kinds:
        findings.append(PlanningDiagnostic(
            "relation_object_ref_kind_mismatch",
            f"{relation.relation_template} does not accept object ref kind {relation.object_ref_kind!r}",
            "error" if relation.criticality == "hard" else "warning", relation.relation_id,
        ))
    elif relation.object_ref_kind == "target":
        target = node_index.get(relation.object_ref)
        if target is None:
            findings.append(PlanningDiagnostic(
                "relation_unknown_object", f"unknown object target {relation.object_ref!r}",
                "error" if relation.criticality == "hard" else "warning", relation.relation_id,
            ))
        elif target.target_kind not in spec.object_kinds:
            findings.append(PlanningDiagnostic(
                "relation_object_type_mismatch",
                f"{relation.relation_template} does not accept object kind {target.target_kind!r}",
                "error" if relation.criticality == "hard" else "warning", relation.relation_id,
            ))

    if relation.parameter_status in {"missing", "invalid"}:
        findings.append(PlanningDiagnostic(
            "relation_parameters_missing" if relation.parameter_status == "missing" else "relation_parameters_invalid",
            f"{relation.relation_template} is not executable without matching typed parameters",
            "error" if relation.criticality == "hard" else "warning", relation.relation_id,
        ))
    elif relation.parameters is not None and relation.parameters.parameter_type not in spec.parameter_types:
        findings.append(PlanningDiagnostic(
            "relation_parameter_type_mismatch",
            f"parameter type {relation.parameters.parameter_type!r} is not valid for {relation.relation_template!r}",
            "error" if relation.criticality == "hard" else "warning", relation.relation_id,
        ))
    if relation.criticality == "hard" and any(
        item.code in {
            "relation_subject_type_mismatch",
            "relation_object_type_mismatch",
            "relation_unknown_subject",
            "relation_unknown_object",
            "relation_object_ref_kind_mismatch",
        }
        for item in findings
    ):
        findings.append(PlanningDiagnostic(
            "relation_deferred",
            "hard relation is deferred until compatible grounded endpoints are available",
            "error",
            relation.relation_id,
        ))
    return findings


__all__ = ["PlanningDiagnostic", "validate_relation_intent"]
