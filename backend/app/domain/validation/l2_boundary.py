"""Provider-to-domain normalization for one L2 decision set.

The provider is allowed to return a structurally valid ``L2DecisionSet`` that
still contains identities or cross-object references which are not valid in the
current frozen run.  This module is the single deterministic boundary between
that provider wire object and the strict L2 semantic validator.

It never invents an identity, unit, relationship, or source fact.  Values that
cannot be proven against the current catalog are removed or quarantined and are
recorded in ``diagnostics``.  The strict validator remains the final gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.contracts.domain.l2_contracts import L2DecisionSet

from .l1_fact_catalog import L1FactCatalog
from .l2_closure import validate_metric_quantity


def _dedup(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _owner(item: Any, fallback: str) -> str:
    for field_name in (
        "objective_id",
        "metric_id",
        "strategy_id",
        "priority_id",
        "structure_id",
        "conflict_id",
    ):
        value = str(getattr(item, field_name, "") or "").strip()
        if value:
            return value
    return fallback


def _close_source_refs(
    item: Any,
    *,
    owner_kind: str,
    allowed_fact_ids: set[str],
    diagnostics: list[str],
) -> list[str]:
    owner = _owner(item, owner_kind)
    kept: list[str] = []
    dropped: list[str] = []
    duplicate_refs: list[str] = []
    seen: set[str] = set()
    for raw_ref in getattr(item, "source_fact_refs", []) or []:
        ref = str(raw_ref or "").strip()
        if ref in seen:
            duplicate_refs.append(ref)
            continue
        seen.add(ref)
        if ref in allowed_fact_ids:
            kept.append(ref)
        else:
            dropped.append(ref)
    if dropped:
        diagnostics.append(
            "l2_boundary.source_fact_refs_dropped:"
            f"{owner_kind}:{owner}:{','.join(sorted(set(dropped)))}"
        )
    if duplicate_refs:
        diagnostics.append(
            "l2_boundary.source_fact_refs_deduplicated:"
            f"{owner_kind}:{owner}:{','.join(sorted(set(duplicate_refs)))}"
        )
    return kept


def _drop_diagnostic(kind: str, owner: str, detail: str) -> str:
    return f"l2_boundary.{kind}_quarantined:{owner}:{detail}"


@dataclass(frozen=True)
class L2BoundaryNormalization:
    """The normalized decision and whether the provider object changed."""

    decision: L2DecisionSet
    changed: bool


def normalize_l2_decision_boundary(
    decision: L2DecisionSet,
    *,
    catalog: L1FactCatalog,
) -> L2BoundaryNormalization:
    """Close provider references and quarantine unverifiable L2 objects.

    The operation is deterministic and idempotent.  It is intentionally
    narrower than semantic inference: only references and object edges that can
    be checked from the current decision/catalog are touched.
    """

    original_payload = decision.model_dump(mode="python")
    diagnostics = list(decision.diagnostics or [])
    allowed_fact_ids = set(catalog.usable_allowed_fact_ids)

    objectives: list[dict[str, Any]] = []
    for item in decision.objectives:
        payload = item.model_dump(mode="python")
        payload["source_fact_refs"] = _close_source_refs(
            item,
            owner_kind="objective",
            allowed_fact_ids=allowed_fact_ids,
            diagnostics=diagnostics,
        )
        if payload.get("status") == "observed" and not payload["source_fact_refs"]:
            payload["status"] = "proposed"
            diagnostics.append(
                "l2_boundary.observed_objective_demoted_no_closed_fact:"
                f"{item.objective_id}"
            )
        objectives.append(payload)
    objective_ids = {str(item["objective_id"]) for item in objectives}

    metrics: list[dict[str, Any]] = []
    for item in decision.metrics:
        payload = item.model_dump(mode="python")
        payload["source_fact_refs"] = _close_source_refs(
            item,
            owner_kind="metric",
            allowed_fact_ids=allowed_fact_ids,
            diagnostics=diagnostics,
        )
        if payload.get("status") == "observed" and not payload["source_fact_refs"]:
            payload["status"] = "proposed"
            diagnostics.append(
                "l2_boundary.observed_metric_demoted_no_closed_fact:"
                f"{item.metric_id}"
            )
        quantity_errors = validate_metric_quantity(item)
        if quantity_errors:
            diagnostics.append(
                _drop_diagnostic(
                    "metric",
                    item.metric_id,
                    ";".join(quantity_errors),
                )
            )
            continue
        metrics.append(payload)

    strategies: list[dict[str, Any]] = []
    for item in decision.strategies:
        payload = item.model_dump(mode="python")
        payload["source_fact_refs"] = _close_source_refs(
            item,
            owner_kind="strategy",
            allowed_fact_ids=allowed_fact_ids,
            diagnostics=diagnostics,
        )
        if not payload["source_fact_refs"]:
            diagnostics.append(
                _drop_diagnostic(
                    "strategy",
                    item.strategy_id,
                    "no_closed_source_fact_refs",
                )
            )
            continue
        raw_objective_refs = [
            str(value).strip()
            for value in payload.get("objective_refs", []) or []
            if str(value).strip()
        ]
        payload["objective_refs"] = [
            value for value in raw_objective_refs if value in objective_ids
        ]
        missing_objective_refs = sorted(set(raw_objective_refs) - objective_ids)
        if missing_objective_refs:
            diagnostics.append(
                "l2_boundary.strategy_objective_refs_dropped:"
                f"{item.strategy_id}:{','.join(missing_objective_refs)}"
            )
        strategies.append(payload)
    strategy_ids = {str(item["strategy_id"]) for item in strategies}

    # Prerequisites are another closed strategy-to-strategy edge.  Providers
    # frequently emit an ID for a strategy that was quarantined above; keep
    # the surviving strategy and remove only that dangling edge.
    for payload in strategies:
        strategy_id = str(payload.get("strategy_id") or "")
        raw_prerequisites = [
            str(value).strip()
            for value in payload.get("prerequisite_refs", []) or []
            if str(value).strip()
        ]
        payload["prerequisite_refs"] = [
            value
            for value in dict.fromkeys(raw_prerequisites)
            if value in strategy_ids and value != strategy_id
        ]
        missing_prerequisites = sorted(
            set(raw_prerequisites) - set(payload["prerequisite_refs"])
        )
        if missing_prerequisites:
            diagnostics.append(
                "l2_boundary.strategy_prerequisite_refs_dropped:"
                f"{strategy_id}:{','.join(missing_prerequisites)}"
            )

    # A priority without a surviving strategy is not an executable ordering;
    # retaining it would only preserve an invalid cross-object edge.
    priorities: list[dict[str, Any]] = []
    for item in decision.priorities:
        payload = item.model_dump(mode="python")
        raw_strategy_refs = [
            str(value).strip()
            for value in payload.get("strategy_refs", []) or []
            if str(value).strip()
        ]
        payload["strategy_refs"] = [
            value for value in raw_strategy_refs if value in strategy_ids
        ]
        missing_strategy_refs = sorted(set(raw_strategy_refs) - strategy_ids)
        if missing_strategy_refs:
            diagnostics.append(
                "l2_boundary.priority_strategy_refs_dropped:"
                f"{item.priority_id}:{','.join(missing_strategy_refs)}"
            )
        if raw_strategy_refs and not payload["strategy_refs"]:
            diagnostics.append(
                _drop_diagnostic(
                    "priority",
                    item.priority_id,
                    "no_surviving_strategy_refs",
                )
            )
            continue
        priorities.append(payload)

    spatial_structures: list[dict[str, Any]] = []
    for item in decision.spatial_structures:
        payload = item.model_dump(mode="python")
        payload["source_fact_refs"] = _close_source_refs(
            item,
            owner_kind="spatial_structure",
            allowed_fact_ids=allowed_fact_ids,
            diagnostics=diagnostics,
        )
        if not payload["source_fact_refs"]:
            diagnostics.append(
                _drop_diagnostic(
                    "spatial_structure",
                    item.structure_id,
                    "no_closed_source_fact_refs",
                )
            )
            continue
        raw_objective_refs = [
            str(value).strip()
            for value in payload.get("objective_refs", []) or []
            if str(value).strip()
        ]
        payload["objective_refs"] = [
            value for value in raw_objective_refs if value in objective_ids
        ]
        missing_objective_refs = sorted(set(raw_objective_refs) - objective_ids)
        if missing_objective_refs:
            diagnostics.append(
                "l2_boundary.spatial_objective_refs_dropped:"
                f"{item.structure_id}:{','.join(missing_objective_refs)}"
            )
        spatial_structures.append(payload)

    conflicts: list[dict[str, Any]] = []
    for item in decision.conflicts:
        payload = item.model_dump(mode="python")
        raw_objective_refs = [
            str(value).strip()
            for value in payload.get("objective_refs", []) or []
            if str(value).strip()
        ]
        raw_strategy_refs = [
            str(value).strip()
            for value in payload.get("strategy_refs", []) or []
            if str(value).strip()
        ]
        payload["objective_refs"] = [
            value for value in raw_objective_refs if value in objective_ids
        ]
        payload["strategy_refs"] = [
            value for value in raw_strategy_refs if value in strategy_ids
        ]
        endpoints = [*payload["objective_refs"], *payload["strategy_refs"]]
        if len(set(endpoints)) < 2:
            diagnostics.append(
                _drop_diagnostic(
                    "conflict",
                    item.conflict_id,
                    "fewer_than_two_surviving_endpoints",
                )
            )
            continue
        conflicts.append(payload)

    payload = {
        **original_payload,
        "objectives": objectives,
        "metrics": metrics,
        "strategies": strategies,
        "priorities": priorities,
        "spatial_structures": spatial_structures,
        "conflicts": conflicts,
        "diagnostics": _dedup(diagnostics),
    }
    normalized = L2DecisionSet.model_validate(payload)
    return L2BoundaryNormalization(
        decision=normalized,
        changed=normalized.model_dump(mode="python") != original_payload,
    )


__all__ = [
    "L2BoundaryNormalization",
    "normalize_l2_decision_boundary",
]
