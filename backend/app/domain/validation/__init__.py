"""Validation APIs with lazy exports to keep contract imports acyclic."""

from __future__ import annotations

import importlib


_EXPORTS = {
    "AdjustmentBudget": ("app.domain.validation.adjustment_executor", "AdjustmentBudget"),
    "BoundedAdjustmentExecutor": ("app.domain.validation.adjustment_executor", "BoundedAdjustmentExecutor"),
    "validate_aggregate": ("app.domain.validation.validate", "validate_aggregate"),
    "evaluate_validate_gate": ("app.domain.validation.validate_gate", "evaluate_validate_gate"),
    "validate_gate_route": ("app.domain.validation.validate_gate", "validate_gate_route"),
    "build_validate_review_package": ("app.domain.validation.validate_review", "build_validate_review_package"),
    "check_hard_constraints": ("app.domain.validation.validate_checks", "check_hard_constraints"),
    "check_area_conservation": ("app.domain.validation.validate_checks", "check_area_conservation"),
    "check_topology": ("app.domain.validation.validate_checks", "check_topology"),
    "check_overlap": ("app.domain.validation.validate_checks", "check_overlap"),
    "check_continuity": ("app.domain.validation.validate_checks", "check_continuity"),
    "check_accessibility": ("app.domain.validation.validate_checks", "check_accessibility"),
    "check_contract_completeness": ("app.domain.validation.validate_checks", "check_contract_completeness"),
    "check_classification_missing": ("app.domain.validation.validate_checks", "check_classification_missing"),
    "check_relation_validation": ("app.domain.validation.validate_checks", "check_relation_validation"),
    "check_cross_layer_topology": ("app.domain.validation.validate_checks", "check_cross_layer_topology"),
    "FinalRelationFinding": ("app.domain.validation.relation_validation", "FinalRelationFinding"),
    "FinalScenarioValidation": ("app.domain.validation.relation_validation", "FinalScenarioValidation"),
    "validate_cross_layer_topology": ("app.domain.validation.relation_validation", "validate_cross_layer_topology"),
    "validate_final_scenario": ("app.domain.validation.relation_validation", "validate_final_scenario"),
    "ReconciliationFinding": ("app.domain.validation.scenario_reconciliation", "ReconciliationFinding"),
    "ScenarioReconciliation": ("app.domain.validation.scenario_reconciliation", "ScenarioReconciliation"),
    "reconcile_scenario_relations": ("app.domain.validation.scenario_reconciliation", "reconcile_scenario_relations"),
    "reconcile_scenario_validation": ("app.domain.validation.scenario_reconciliation", "reconcile_scenario_validation"),
    "CandidateDecision": ("app.contracts.llm.closed_set_contracts", "CandidateDecision"),
    "CandidateDescriptor": ("app.contracts.llm.closed_set_contracts", "CandidateDescriptor"),
    "ExactBatchMembershipResult": ("app.contracts.llm.closed_set_contracts", "ExactBatchMembershipResult"),
    "select_closed_set_candidate": ("app.contracts.llm.closed_set_contracts", "select_closed_set_candidate"),
    "validate_exact_batch_membership": ("app.contracts.llm.closed_set_contracts", "validate_exact_batch_membership"),
    "ReferenceGraphNode": ("app.domain.validation.reference_graph", "ReferenceGraphNode"),
    "validate_reference_graph": ("app.domain.validation.reference_graph", "validate_reference_graph"),
    "RepairPolicyDecision": ("app.domain.validation.repair_operations", "RepairPolicyDecision"),
    "evaluate_repair_policy": ("app.domain.validation.repair_operations", "evaluate_repair_policy"),
    "pending_repair_decisions": ("app.domain.validation.repair_operations", "pending_repair_decisions"),
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
