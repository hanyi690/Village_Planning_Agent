"""Reconcile solver-time relation evidence with final execution evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

from pydantic import BaseModel, Field

from app.contracts.ground.constraint_factor import RelationSatisfaction
from app.contracts.select.scenario import PlanningScenario
from app.workflow.validation.relation_validation import FinalScenarioValidation


class ReconciliationFinding(BaseModel):
    code: str
    relation_id: str = ""
    severity: str = "error"
    message: str
    pre_status: str = ""
    final_status: str = ""
    pre_measurement: Any = None
    final_measurement: Any = None
    feature_refs: list[str] = Field(default_factory=list)
    evaluator_versions: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)


class ScenarioReconciliation(BaseModel):
    """Serializable comparison between SELECT and VALIDATE relation rows."""

    schema_version: str = "1.0"
    scenario_id: str
    passed: bool = False
    status: str = "failed"
    pre_execution_fingerprint: str = ""
    final_fingerprint: str = ""
    evaluator_version: str = ""
    findings: list[ReconciliationFinding] = Field(default_factory=list)
    changed_relation_ids: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    fingerprint: str = ""


def _row_map(rows: Iterable[RelationSatisfaction]) -> dict[str, RelationSatisfaction]:
    return {str(row.relation_id): row for row in rows if str(row.relation_id)}


def _measurement(row: RelationSatisfaction | None) -> Any:
    if row is None or row.measurement is None:
        return None
    return row.measurement.model_dump(mode="json")


def _numeric_measurement(row: RelationSatisfaction | None) -> float | None:
    if row is None or row.measurement is None:
        return None
    value = row.measurement.value
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def reconcile_scenario_relations(
    scenario: PlanningScenario,
    final_validation: FinalScenarioValidation,
) -> ScenarioReconciliation:
    """Compare every pre-execution row with its independent final row.

    A status transition, changed feature binding, missing measurement, or
    evaluator-version drift is retained as a finding.  ``satisfied`` in the
    solver result can therefore never mask a final violation.
    """

    before = _row_map(scenario.relation_satisfactions)
    after = _row_map(final_validation.satisfactions)
    findings: list[ReconciliationFinding] = []
    changed: set[str] = set()
    relation_ids = sorted(set(before) | set(after))
    for relation_id in relation_ids:
        pre = before.get(relation_id)
        final = after.get(relation_id)
        if pre is None or final is None:
            changed.add(relation_id)
            findings.append(
                ReconciliationFinding(
                    code="relation_missing_in_reconciliation",
                    relation_id=relation_id,
                    message="relation exists on only one side of solver/final comparison",
                    pre_status=pre.status if pre else "missing",
                    final_status=final.status if final else "missing",
                    pre_measurement=_measurement(pre),
                    final_measurement=_measurement(final),
                    feature_refs=sorted(set((pre.subject_feature_refs + pre.object_feature_refs) if pre else []) | set((final.subject_feature_refs + final.object_feature_refs) if final else [])),
                    evaluator_versions=sorted(set(item for item in [pre.evaluator_version if pre else "", final.evaluator_version if final else ""] if item)),
                )
            )
            continue
        feature_refs = sorted(
            set(pre.subject_feature_refs + pre.object_feature_refs)
            | set(final.subject_feature_refs + final.object_feature_refs)
        )
        if pre.status != final.status:
            changed.add(relation_id)
            findings.append(
                ReconciliationFinding(
                    code="relation_status_changed",
                    relation_id=relation_id,
                    message="final geometry changed relation status",
                    pre_status=pre.status,
                    final_status=final.status,
                    pre_measurement=_measurement(pre),
                    final_measurement=_measurement(final),
                    feature_refs=feature_refs,
                    evaluator_versions=sorted(set(filter(None, [pre.evaluator_version, final.evaluator_version]))),
                    trace=list(final.evaluation_trace),
                )
            )
        elif _numeric_measurement(pre) is not None and _numeric_measurement(final) is not None:
            if _numeric_measurement(pre) != _numeric_measurement(final):
                changed.add(relation_id)
                findings.append(
                    ReconciliationFinding(
                        code="relation_measurement_changed",
                        relation_id=relation_id,
                        message="final geometry changed the relation measurement",
                        pre_status=pre.status,
                        final_status=final.status,
                        pre_measurement=_measurement(pre),
                        final_measurement=_measurement(final),
                        feature_refs=feature_refs,
                        evaluator_versions=sorted(set(filter(None, [pre.evaluator_version, final.evaluator_version]))),
                        trace=list(final.evaluation_trace),
                    )
                )
        if set(pre.subject_feature_refs + pre.object_feature_refs) != set(
            final.subject_feature_refs + final.object_feature_refs
        ):
            changed.add(relation_id)
            findings.append(
                ReconciliationFinding(
                    code="relation_feature_replaced",
                    relation_id=relation_id,
                    message="final evaluator used a different feature binding",
                    pre_status=pre.status,
                    final_status=final.status,
                    pre_measurement=_measurement(pre),
                    final_measurement=_measurement(final),
                    feature_refs=feature_refs,
                    evaluator_versions=sorted(set(filter(None, [pre.evaluator_version, final.evaluator_version]))),
                    trace=list(final.evaluation_trace),
                )
            )
        if pre.evaluator_version and final.evaluator_version and pre.evaluator_version != final.evaluator_version:
            changed.add(relation_id)
            findings.append(
                ReconciliationFinding(
                    code="evaluator_version_changed",
                    relation_id=relation_id,
                    message="solver and final evaluator versions differ",
                    pre_status=pre.status,
                    final_status=final.status,
                    pre_measurement=_measurement(pre),
                    final_measurement=_measurement(final),
                    feature_refs=feature_refs,
                    evaluator_versions=sorted(set([pre.evaluator_version, final.evaluator_version])),
                    trace=list(final.evaluation_trace),
                )
            )
        if final.status == "satisfied" and final.measurement is None:
            changed.add(relation_id)
            findings.append(
                ReconciliationFinding(
                    code="final_satisfaction_missing_measurement",
                    relation_id=relation_id,
                    message="final satisfied row has no measurement",
                    pre_status=pre.status,
                    final_status=final.status,
                    feature_refs=feature_refs,
                    evaluator_versions=sorted(set(filter(None, [pre.evaluator_version, final.evaluator_version]))),
                )
            )
    # A final validation finding is part of reconciliation even when there is
    # no corresponding solver row (for example an orphan feature).
    for finding in final_validation.findings:
        if finding.relation_id and finding.relation_id in changed:
            continue
        if finding.code.startswith(("relation_", "missing_", "orphan_", "cross_layer_", "geometry_", "invalid_")):
            changed.add(finding.relation_id or finding.code)
            findings.append(
                ReconciliationFinding(
                    code=f"final_validation:{finding.code}",
                    relation_id=finding.relation_id,
                    message=finding.message,
                    final_status=finding.status,
                    feature_refs=list(finding.feature_refs),
                    trace=list(final_validation.trace),
                )
            )
    payload = {
        "scenario": scenario.fingerprint,
        "final": final_validation.final_fingerprint,
        "findings": [item.model_dump(mode="json") for item in findings],
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    passed = not findings and final_validation.passed
    return ScenarioReconciliation(
        scenario_id=scenario.scenario_id,
        passed=passed,
        status="reconciled" if passed else "diverged",
        pre_execution_fingerprint=scenario.fingerprint,
        final_fingerprint=final_validation.final_fingerprint,
        evaluator_version=final_validation.evaluator_version,
        findings=findings,
        changed_relation_ids=sorted(changed),
        trace=[
            f"pre-relations:{len(before)}",
            f"final-relations:{len(after)}",
            f"changed:{len(changed)}",
            f"fingerprint:{fingerprint}",
        ],
        fingerprint=fingerprint,
    )


def reconcile_scenario_validation(
    scenario: PlanningScenario,
    final_validation: FinalScenarioValidation,
) -> ScenarioReconciliation:
    """Readable alias used by VALIDATE stage adapters."""

    return reconcile_scenario_relations(scenario, final_validation)


__all__ = [
    "ReconciliationFinding",
    "ScenarioReconciliation",
    "reconcile_scenario_relations",
    "reconcile_scenario_validation",
]
