"""Conservative auto-application policy for verified-decision repairs."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.contracts.llm.decision_contracts import PendingDecision, RepairOperation, StrictDecisionModel


class RepairPolicyDecision(StrictDecisionModel):
    """Whether a typed repair may run without human review."""

    operation_id: str
    status: Literal["auto_apply", "pending"]
    reason_code: str


def evaluate_repair_policy(operation: RepairOperation) -> RepairPolicyDecision:
    """Apply generic, fail-closed repair rules without domain inference."""
    if operation.hard_relation and operation.operation == "remove":
        return RepairPolicyDecision(
            operation_id=operation.operation_id,
            status="pending",
            reason_code="hard_relation_removal_requires_review",
        )
    if operation.repair_kind in {"shape_only", "identity_resolution"}:
        return RepairPolicyDecision(
            operation_id=operation.operation_id,
            status="auto_apply",
            reason_code="safe_repair_kind",
        )
    if not operation.evidence_refs:
        return RepairPolicyDecision(
            operation_id=operation.operation_id,
            status="pending",
            reason_code="semantic_change_requires_evidence",
        )
    return RepairPolicyDecision(
        operation_id=operation.operation_id,
        status="auto_apply",
        reason_code="semantic_change_has_evidence",
    )


def pending_repair_decisions(
    operations: list[RepairOperation],
) -> list[PendingDecision]:
    """Translate non-auto-applicable repairs into explicit pending work."""
    pending: list[PendingDecision] = []
    for operation in operations:
        policy = evaluate_repair_policy(operation)
        if policy.status == "pending":
            pending.append(
                PendingDecision(
                    decision_ref=operation.object_ref,
                    reason_code=policy.reason_code,
                    dependency_refs=[operation.object_ref],
                    requires_human_review=True,
                )
            )
    return pending


__all__ = ["RepairPolicyDecision", "evaluate_repair_policy", "pending_repair_decisions"]
