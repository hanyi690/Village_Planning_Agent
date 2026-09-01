"""Fail-closed checks for geometry crossing SELECT/EXECUTE/DELIVER."""

from __future__ import annotations

from typing import Any, Iterable


def is_external_observation_ref(value: Any) -> bool:
    return str(value or "").strip().startswith("external-observation:")


def validate_executable_resource_ref(
    resource_ref: str,
    *,
    evidence_refs: Iterable[str] = (),
) -> dict[str, Any]:
    """Validate that an executable resource is local and separately evidenced.

    External observations are valid evidence references but never executable
    geometry resources.  The function returns a serializable diagnostic so
    SELECT can expose a rejection reason without throwing away the candidate.
    """

    resource = str(resource_ref or "").strip()
    evidence = [str(item).strip() for item in evidence_refs if str(item).strip()]
    if not resource:
        return {"status": "rejected", "code": "missing_resource_ref"}
    if is_external_observation_ref(resource):
        return {
            "status": "rejected",
            "code": "external_observation_not_executable",
            "resource_ref": resource,
            "evidence_refs": evidence,
        }
    return {
        "status": "accepted",
        "resource_ref": resource,
        "evidence_refs": evidence,
    }


def validate_render_feature(feature: dict[str, Any], *, planned: bool = True) -> dict[str, Any]:
    """Check geometry and lineage fields before a feature is rendered."""

    geometry = feature.get("geometry")
    properties = feature.get("properties") or {}
    if not geometry:
        return {"status": "rejected", "code": "missing_geometry"}
    if not planned:
        return {"status": "accepted"}
    lineage_keys = (
        "resource_ref",
        "representation_ref",
        "source_snapshot_ref",
        "world_model_digest",
        "bundle_snapshot_digest",
    )
    if not any(
        str(properties.get(key) or "").strip()
        or any(str(value).strip() for value in (properties.get(f"{key}s") or []))
        for key in lineage_keys
    ):
        return {"status": "diagnostic_only", "code": "missing_geometry_lineage"}
    for key in ("resource_ref", "representation_ref"):
        if is_external_observation_ref(properties.get(key)):
            return {"status": "rejected", "code": "external_observation_geometry_ref"}
        if any(is_external_observation_ref(value) for value in (properties.get(f"{key}s") or [])):
            return {"status": "rejected", "code": "external_observation_geometry_ref"}
    return {"status": "accepted"}


__all__ = [
    "is_external_observation_ref",
    "validate_executable_resource_ref",
    "validate_render_feature",
]
