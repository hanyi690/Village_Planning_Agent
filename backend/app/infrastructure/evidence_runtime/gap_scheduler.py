"""Earliest-stage Evidence Gap scheduling.

This module only decides when a requirement may be attempted.  Retrieval
adapters remain owned by the Evidence Runtime; no provider or network call is
performed here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.contracts.evidence.requirement_contracts import EvidenceRequirement

_STAGE_ORDER = {
    "DATA": 0,
    "PREPARE": 0,
    "KG": 0,
    "COGNITION": 0,
    "EVIDENCE": 1,
    "L1": 1,
    "OBSERVE": 1,
    "L2": 2,
    "STRATEGIZE": 2,
    "L3": 3,
    "PLAN": 3,
    "GROUND": 4,
    "SELECT": 5,
    "EXECUTE": 6,
}

_SOURCE_ALIASES = {
    "local_data": frozenset({"local_data", "data", "gis", "artifact"}),
    "data": frozenset({"local_data", "data", "gis", "artifact"}),
    "gis": frozenset({"local_data", "data", "gis", "artifact"}),
    "artifact": frozenset({"local_data", "data", "gis", "artifact"}),
    "cache": frozenset({"cache", "map_cache", "external_map_cache"}),
    "map_cache": frozenset({"cache", "map_cache", "external_map_cache"}),
    "external_map_cache": frozenset({"cache", "map_cache", "external_map_cache"}),
    "world_model": frozenset({"world_model", "kg"}),
    "kg": frozenset({"world_model", "kg"}),
}


def _source_set(values: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        token = str(value).strip().casefold()
        if not token:
            continue
        result.update(_SOURCE_ALIASES.get(token, (token,)))
    return result


def _stage(value: str) -> str:
    key = str(value or "").strip().upper()
    return key or "L1"


def _earliest(requirement: EvidenceRequirement) -> str:
    explicit = _stage(requirement.earliest_resolution_stage)
    if requirement.earliest_resolution_stage:
        return explicit
    metadata = requirement.metadata or {}
    declared = metadata.get("earliest_resolution_stage") or metadata.get("deferred_until")
    if declared:
        return _stage(str(declared))
    if requirement.kind in {"identity", "spatial"}:
        return "L1"
    if requirement.kind == "metric":
        return "L2"
    if requirement.evidence_role in {"l3_relation_network_missing", "pending_grounding_claim"}:
        return "L3"
    return _stage(requirement.producer_stage)


def _capability(requirement: EvidenceRequirement) -> str:
    if requirement.retrieval_capability:
        return requirement.retrieval_capability
    metadata = requirement.metadata or {}
    if metadata.get("retrieval_capability"):
        return str(metadata["retrieval_capability"])
    if requirement.kind == "spatial":
        return "local_spatial_evidence"
    if requirement.kind == "identity":
        return "identity_evidence"
    if requirement.kind == "metric":
        return "metric_source"
    return "source_evidence"


def schedule_requirement(
    requirement: EvidenceRequirement,
    *,
    current_stage: str,
    available_capabilities: Iterable[str] = (),
    available_sources: Iterable[str] = (),
) -> EvidenceRequirement:
    """Annotate one requirement with its earliest actionable state."""

    current = _stage(current_stage)
    earliest = _earliest(requirement)
    capability = _capability(requirement)
    capabilities = {
        str(value).strip().casefold()
        for value in available_capabilities
        if str(value).strip()
    }
    sources = _source_set(available_sources)
    current_index = _STAGE_ORDER.get(current, 1)
    earliest_index = _STAGE_ORDER.get(earliest, current_index)
    metadata = dict(requirement.metadata or {})
    metadata.update({
        "earliest_resolution_stage": earliest,
        "scheduled_at_stage": current,
        "retrieval_capability": capability,
    })
    if requirement.gap_status in {"resolved", "requires_human_confirmation"}:
        return requirement.model_copy(update={
            "earliest_resolution_stage": earliest,
            "retrieval_capability": capability,
            "metadata": metadata,
        })
    if current_index < earliest_index:
        return requirement.model_copy(update={
            "earliest_resolution_stage": earliest,
            "deferred_until": earliest,
            "retrieval_capability": capability,
            "gap_status": "open",
            "metadata": metadata,
        })
    required_families = _source_set(requirement.source_families)
    family_allowed = not required_families or bool(
        required_families.intersection(sources)
    )
    capability_available = capability.casefold() in capabilities
    if family_allowed and capability_available:
        status = "ready_for_retrieval"
        deferred_until = ""
    else:
        status = "not_available"
        deferred_until = ""
        metadata["unavailable_reason"] = (
            "source_family_unavailable" if not family_allowed else "retrieval_capability_unavailable"
        )
    return requirement.model_copy(update={
        "earliest_resolution_stage": earliest,
        "deferred_until": deferred_until,
        "retrieval_capability": capability,
        "gap_status": status,
        "metadata": metadata,
    })


def schedule_requirements(
    requirements: Sequence[EvidenceRequirement],
    *,
    current_stage: str,
    available_capabilities: Iterable[str] = (),
    available_sources: Iterable[str] = (),
) -> tuple[tuple[EvidenceRequirement, ...], dict[str, Any]]:
    """Schedule a bounded requirement batch and return an audit trace."""

    scheduled = tuple(
        schedule_requirement(
            requirement,
            current_stage=current_stage,
            available_capabilities=available_capabilities,
            available_sources=available_sources,
        )
        for requirement in requirements
    )
    counts: dict[str, int] = {}
    for requirement in scheduled:
        counts[requirement.gap_status] = counts.get(requirement.gap_status, 0) + 1
    return scheduled, {
        "step": "evidence_gap_scheduler",
        "current_stage": _stage(current_stage),
        "counts": counts,
        "immediate_count": counts.get("ready_for_retrieval", 0),
        "deferred_count": counts.get("open", 0),
        "unavailable_count": counts.get("not_available", 0),
    }


__all__ = ["schedule_requirement", "schedule_requirements"]
