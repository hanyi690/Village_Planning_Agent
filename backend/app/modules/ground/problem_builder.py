"""Derive a bounded planning problem after an explicit target deferral.

GROUND owns the full evidence-backed problem.  SELECT may derive a child
problem only when a typed DeferralLedger says that a target is intentionally
out of scope.  This module is pure: it removes the deferred target and every
relation/candidate that depends on it, preserves the parent fingerprint, and
lets the contract recompute completeness and the child fingerprint.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.contracts.ground.grounded_problem import (
    GroundedPlanningProblem,
    derive_parcel_resource_pool,
)


def _normalized_ids(values: Iterable[str]) -> set[str]:
    return {str(value).strip() for value in values if str(value).strip()}


def _touches_target(item: Any, deferred: set[str]) -> bool:
    subject = str(getattr(item, "subject_ref", "") or "").strip()
    object_ref = str(getattr(item, "object_ref", "") or "").strip()
    object_ref_kind = str(getattr(item, "object_ref_kind", "target") or "target")
    return subject in deferred or (object_ref_kind == "target" and object_ref in deferred)


def _requirement_touches_target(item: Any, deferred: set[str]) -> bool:
    metadata = getattr(item, "metadata", None) or {}
    metadata_target = str(metadata.get("target_id", "") or "").strip()
    if metadata_target in deferred:
        return True
    scope = _normalized_ids(getattr(item, "scope", None) or ())
    return bool(scope.intersection(deferred))


def _payload_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def scope_grounded_problem(
    problem: GroundedPlanningProblem,
    deferred_target_ids: Iterable[str],
    *,
    source_refs: Iterable[str] = (),
    reason: str = "explicit target deferral",
) -> GroundedPlanningProblem:
    """Return a new problem containing only targets still in scope.

    The function rejects unknown target IDs.  A typo in a HUMAN decision must
    never silently broaden the executable scope.  The original problem is not
    mutated and remains the immutable GROUND evidence boundary.
    """

    deferred = _normalized_ids(deferred_target_ids)
    # A scoped problem may itself be scoped again after SELECT discovers a
    # second blocker.  Deferral is cumulative: never re-introduce a target
    # that was removed by an earlier child problem.
    deferred.update(
        _normalized_ids(getattr(problem, "deferred_target_ids", None) or ())
    )
    if not deferred:
        return problem

    known = {
        str(item.target_id)
        for item in (
            *list(getattr(problem, "target_domains", None) or []),
            *list(getattr(problem, "candidate_domains", None) or []),
            *list(getattr(problem, "candidate_geometries", None) or []),
        )
        if str(getattr(item, "target_id", "") or "").strip()
    }
    known.update(
        _normalized_ids(getattr(problem, "deferred_target_ids", None) or ())
    )
    unknown = sorted(deferred - known)
    if unknown:
        raise ValueError(
            "cannot scope GroundedPlanningProblem to unknown targets: "
            + ", ".join(unknown)
        )

    parent_fingerprint = str(getattr(problem, "fingerprint", "") or "")
    scoped_source_refs = sorted(
        {
            str(value).strip()
            for value in (
                *list(getattr(problem, "scope_source_refs", None) or []),
                *list(source_refs),
            )
            if str(value).strip()
        }
    )
    kept_factors = [
        factor
        for factor in list(getattr(problem, "constraint_factors", None) or [])
        if not _touches_target(factor, deferred)
    ]
    kept_factor_ids = {str(getattr(item, "factor_id", "") or "") for item in kept_factors}
    kept_relations = [
        relation
        for relation in list(getattr(problem, "relation_satisfaction", None) or [])
        if not _touches_target(relation, deferred)
        and (
            not getattr(relation, "factor_ids", None)
            or set(getattr(relation, "factor_ids", None) or []).issubset(kept_factor_ids)
        )
    ]
    payload = problem.model_dump(mode="python")
    payload.update(
        {
            "scope_policy": "deferred_target_subset",
            "parent_problem_fingerprint": parent_fingerprint,
            "deferred_target_ids": sorted(deferred),
            "scope_reason": " ".join(str(reason or "").split()),
            "scope_source_refs": scoped_source_refs,
            "target_domains": [
                item
                for item in (getattr(problem, "target_domains", None) or [])
                if str(getattr(item, "target_id", "") or "") not in deferred
            ],
            "candidate_domains": [
                item
                for item in (getattr(problem, "candidate_domains", None) or [])
                if str(getattr(item, "target_id", "") or "") not in deferred
            ],
            "candidate_geometries": [
                item
                for item in (getattr(problem, "candidate_geometries", None) or [])
                if str(getattr(item, "target_id", "") or "") not in deferred
            ],
            "bindings": [
                item
                for item in (getattr(problem, "bindings", None) or [])
                if str(getattr(item, "target_id", "") or "") not in deferred
            ],
            "constraint_factors": kept_factors,
            "relation_satisfaction": kept_relations,
            "unresolved": [
                item
                for item in (getattr(problem, "unresolved", None) or [])
                if str(getattr(item, "target_id", "") or "") not in deferred
            ],
            "deferred": [
                item
                for item in (getattr(problem, "deferred", None) or [])
                if str(getattr(item, "target_id", "") or "") not in deferred
            ],
            "evidence_requirements": [
                item
                for item in (getattr(problem, "evidence_requirements", None) or [])
                if not _requirement_touches_target(item, deferred)
            ],
            "diagnostics": [
                *list(getattr(problem, "diagnostics", None) or []),
                f"scoped_from_problem:{parent_fingerprint}",
                *[f"deferred_target:{target_id}" for target_id in sorted(deferred)],
            ],
            "source_artifact_refs": sorted(
                {
                    *list(getattr(problem, "source_artifact_refs", None) or []),
                    *scoped_source_refs,
                }
            ),
            "fingerprint": "",
        }
    )
    active_candidate_ids = {
        str(candidate_id)
        for domain in payload["candidate_domains"]
        for candidate_id in (_payload_value(domain, "candidate_ids", None) or [])
        if str(candidate_id).strip()
    }
    active_candidates = [
        item
        for item in payload["candidate_geometries"]
        if str(_payload_value(item, "candidate_id", "") or "")
        in active_candidate_ids
    ]
    payload["parcel_resource_pool"] = derive_parcel_resource_pool(
        active_candidates,
        pool_id=f"scoped-parcel-pool:{parent_fingerprint[:16]}",
    )
    return GroundedPlanningProblem.model_validate(payload)


__all__ = ["scope_grounded_problem"]
