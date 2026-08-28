"""Validation APIs with lazy exports to keep contract imports acyclic."""

from __future__ import annotations

import importlib


_EXPORTS = {
    "AdjustmentBudget": ("app.workflow.validation.adjustment_executor", "AdjustmentBudget"),
    "BoundedAdjustmentExecutor": ("app.workflow.validation.adjustment_executor", "BoundedAdjustmentExecutor"),
    "validate_aggregate": ("app.workflow.validation.validate", "validate_aggregate"),
    "evaluate_validate_gate": ("app.workflow.validation.validate_gate", "evaluate_validate_gate"),
    "validate_gate_route": ("app.workflow.validation.validate_gate", "validate_gate_route"),
    "build_validate_review_package": ("app.workflow.validation.validate_review", "build_validate_review_package"),
    "check_hard_constraints": ("app.workflow.validation.validate_checks", "check_hard_constraints"),
    "check_area_conservation": ("app.workflow.validation.validate_checks", "check_area_conservation"),
    "check_topology": ("app.workflow.validation.validate_checks", "check_topology"),
    "check_overlap": ("app.workflow.validation.validate_checks", "check_overlap"),
    "check_continuity": ("app.workflow.validation.validate_checks", "check_continuity"),
    "check_accessibility": ("app.workflow.validation.validate_checks", "check_accessibility"),
    "check_contract_completeness": ("app.workflow.validation.validate_checks", "check_contract_completeness"),
    "check_classification_missing": ("app.workflow.validation.validate_checks", "check_classification_missing"),
    "check_relation_validation": ("app.workflow.validation.validate_checks", "check_relation_validation"),
    "check_cross_layer_topology": ("app.workflow.validation.validate_checks", "check_cross_layer_topology"),
    "FinalRelationFinding": ("app.workflow.validation.relation_validation", "FinalRelationFinding"),
    "FinalScenarioValidation": ("app.workflow.validation.relation_validation", "FinalScenarioValidation"),
    "validate_cross_layer_topology": ("app.workflow.validation.relation_validation", "validate_cross_layer_topology"),
    "validate_final_scenario": ("app.workflow.validation.relation_validation", "validate_final_scenario"),
    "ReconciliationFinding": ("app.workflow.validation.scenario_reconciliation", "ReconciliationFinding"),
    "ScenarioReconciliation": ("app.workflow.validation.scenario_reconciliation", "ScenarioReconciliation"),
    "reconcile_scenario_relations": ("app.workflow.validation.scenario_reconciliation", "reconcile_scenario_relations"),
    "reconcile_scenario_validation": ("app.workflow.validation.scenario_reconciliation", "reconcile_scenario_validation"),
    "CandidateDecision": ("app.contracts.llm.closed_set_contracts", "CandidateDecision"),
    "CandidateDescriptor": ("app.contracts.llm.closed_set_contracts", "CandidateDescriptor"),
    "ExactBatchMembershipResult": ("app.contracts.llm.closed_set_contracts", "ExactBatchMembershipResult"),
    "select_closed_set_candidate": ("app.contracts.llm.closed_set_contracts", "select_closed_set_candidate"),
    "validate_exact_batch_membership": ("app.contracts.llm.closed_set_contracts", "validate_exact_batch_membership"),
    "ReferenceGraphNode": ("app.workflow.validation.reference_graph", "ReferenceGraphNode"),
    "validate_reference_graph": ("app.workflow.validation.reference_graph", "validate_reference_graph"),
    "RepairPolicyDecision": ("app.workflow.validation.repair_operations", "RepairPolicyDecision"),
    "evaluate_repair_policy": ("app.workflow.validation.repair_operations", "evaluate_repair_policy"),
    "pending_repair_decisions": ("app.workflow.validation.repair_operations", "pending_repair_decisions"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute_name = target
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = sorted(_EXPORTS)
