"""Stable-key helpers for ExecutionPlan/ExecutionResult evidence."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


StableOutputKey = tuple[str, str]


def stable_output_key(value: Any) -> StableOutputKey:
    return (
        str(getattr(value, "target_id", "")),
        str(getattr(value, "expected_output_kind", "")),
    )


def group_execution_results(outcome: Any) -> dict[StableOutputKey, list[Any]]:
    grouped: dict[StableOutputKey, list[Any]] = defaultdict(list)
    for result in list(getattr(outcome, "task_results", None) or []):
        grouped[stable_output_key(result)].append(result)
    return dict(grouped)


def contradictory_statuses(results: list[Any]) -> bool:
    return len({str(getattr(result, "status", "")) for result in results}) > 1


def active_output_covered(results: list[Any], output_kind: str) -> bool:
    if not results or contradictory_statuses(results):
        return False
    for result in results:
        if getattr(result, "status", "failed") != "succeeded":
            return False
        if output_kind == "action":
            if output_kind not in list(getattr(result, "output_artifacts", None) or []):
                return False
            continue
        feature_ids = [
            str(value)
            for value in list(getattr(result, "feature_ids", None) or [])
            if str(value).strip()
        ]
        artifact_refs = {
            str(value)
            for value in list(getattr(result, "output_artifact_refs", None) or [])
            if str(value).strip()
        }
        if not feature_ids or not {
            f"spatial-feature:{feature_id}" for feature_id in feature_ids
        }.issubset(artifact_refs):
            return False
    return True


def deferred_outcome_contradiction(results: list[Any]) -> bool:
    return any(getattr(result, "status", "") != "deferred" for result in results)


__all__ = [
    "StableOutputKey",
    "active_output_covered",
    "contradictory_statuses",
    "deferred_outcome_contradiction",
    "group_execution_results",
    "stable_output_key",
]
