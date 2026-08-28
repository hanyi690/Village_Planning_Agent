"""Materialize explicitly classified custom zones as parcel changes.

Vocabulary category codes remain semantic selection inputs.  This module only
uses an already resolved, namespace-validated ``ClassificationDecision`` to
produce statutory parcel classifications.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from app.contracts.execute.custom_zone_contracts import CustomZoneTarget, Vocabulary
from app.contracts.execute.parcel_change_contracts import ParcelChange
from app.modules.execute.zoning.custom_zone_generator import CustomZoningGenerator


@dataclass
class CustomZoneMaterializationResult:
    changes: list[ParcelChange] = field(default_factory=list)
    unresolved_items: list[dict[str, object]] = field(default_factory=list)
    diagnostics: list[dict[str, object]] = field(default_factory=list)
    audit: object | None = None


def _value(item: Any, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, Mapping) else getattr(item, name, default)


def _as_target(target: Any, result: CustomZoneMaterializationResult) -> CustomZoneTarget | None:
    if target is None:
        result.unresolved_items.append({
            "code": "custom_zone_target_missing",
            "message": "Custom zone materialization requires a target.",
        })
        return None
    if isinstance(target, CustomZoneTarget):
        return target
    try:
        return CustomZoneTarget.model_validate(target)
    except (TypeError, ValueError) as error:
        result.unresolved_items.append({
            "code": "custom_zone_target_invalid",
            "message": str(error),
        })
        return None


def _as_geometry(value: Any) -> BaseGeometry | None:
    if isinstance(value, BaseGeometry):
        geometry = value
    elif isinstance(value, Mapping):
        try:
            geometry = shape(value)
        except (TypeError, ValueError, AttributeError):
            return None
    else:
        return None
    if geometry.is_empty or not geometry.is_valid:
        return None
    return geometry


def _parcel_items(parcels: Mapping[str, Any] | Iterable[Any]) -> list[tuple[str, Any]]:
    if isinstance(parcels, Mapping):
        return [(str(bsm), parcel) for bsm, parcel in parcels.items()]
    return [
        (str(_value(parcel, "bsm", "") or ""), parcel)
        for parcel in parcels
    ]


def _generator_parcels(
    parcels: Mapping[str, Any] | Iterable[Any],
    result: CustomZoneMaterializationResult,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_by_bsm: dict[str, Any] = {}
    generator_parcels: list[dict[str, Any]] = []
    for index_bsm, parcel in _parcel_items(parcels):
        bsm = str(_value(parcel, "bsm", index_bsm) or index_bsm)
        if not bsm:
            continue
        source_by_bsm[bsm] = parcel
        geometry = _as_geometry(_value(parcel, "geometry"))
        if geometry is None:
            result.diagnostics.append({
                "code": "invalid_geometry",
                "bsm": bsm,
                "message": "Parcel geometry is missing, empty, or invalid.",
            })
            continue
        values = dict(parcel) if isinstance(parcel, Mapping) else {}
        values.update({
            "bsm": bsm,
            "geometry": geometry,
            "area_ha": float(_value(parcel, "area_ha", 0.0) or 0.0),
            "dlbm": str(_value(parcel, "dlbm", "") or ""),
        })
        generator_parcels.append(values)
    return source_by_bsm, generator_parcels


def _unresolved(
    result: CustomZoneMaterializationResult,
    code: str,
    target_id: str,
    message: str,
    **details: object,
) -> None:
    result.unresolved_items.append({
        "code": code,
        "target_id": target_id,
        "message": message,
        **details,
    })


def materialize_custom_zone_changes(
    target: CustomZoneTarget | Mapping[str, Any] | None,
    parcels: Mapping[str, Any] | Iterable[Any],
    three_lines: dict | None = None,
    *,
    vocabulary: Vocabulary | Mapping[str, Any] | None = None,
) -> CustomZoneMaterializationResult:
    """Create reclassification changes from one explicitly classified custom zone.

    ``category_code`` is passed only to ``CustomZoningGenerator`` for vocabulary
    selection.  The output classification comes exclusively from the target's
    resolved ``ClassificationDecision``.
    """
    result = CustomZoneMaterializationResult()
    typed_target = _as_target(target, result)
    if typed_target is None:
        return result

    target_id = typed_target.target_id
    decision = typed_target.classification_decision
    if decision is None or getattr(decision, "status", "") != "resolved":
        _unresolved(
            result,
            "classification_unresolved",
            target_id,
            "Custom zone execution requires an explicit resolved classification decision.",
        )
        return result
    if str(getattr(decision, "target_id", "") or "") != target_id:
        _unresolved(
            result,
            "classification_invalid",
            target_id,
            "Classification decision target_id does not match the custom zone target.",
        )
        return result
    try:
        from app.modules.execute.classification_utils import (
            _classification_from_decision,
        )

        classification = _classification_from_decision(decision, source="user_provided")
    except (AttributeError, TypeError, ValueError):
        classification = None
    if classification is None:
        _unresolved(
            result,
            "classification_invalid",
            target_id,
            "Custom zone classification decision is not valid in its declared code system.",
        )
        return result

    source_by_bsm, generator_parcels = _generator_parcels(parcels, result)
    invalid_bsms = {
        str(item["bsm"])
        for item in result.diagnostics
        if item.get("code") == "invalid_geometry" and item.get("bsm")
    }
    for bsm in typed_target.target_bsms:
        requested_bsm = str(bsm)
        if requested_bsm not in source_by_bsm:
            _unresolved(
                result,
                "missing_bsm",
                target_id,
                "Custom zone references a parcel that is not available to EXECUTE.",
                bsm=requested_bsm,
            )
        elif requested_bsm in invalid_bsms:
            _unresolved(
                result,
                "invalid_geometry",
                target_id,
                "Custom zone references a parcel with invalid geometry.",
                bsm=requested_bsm,
            )

    intent: dict[str, Any] = {
        "vocabulary_name": typed_target.vocabulary_name,
        "custom_zone_targets": [typed_target],
    }
    if vocabulary is not None:
        intent["vocabulary"] = vocabulary
    try:
        zones, audit = CustomZoningGenerator(
            parcels=generator_parcels,
            intent=intent,
            three_lines=three_lines,
        ).generate_with_validation()
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        _unresolved(
            result,
            "custom_zone_generation_failed",
            target_id,
            "Custom zone selection could not be materialized.",
            detail=str(error),
        )
        return result
    result.audit = audit

    matching_zones = [
        zone
        for zone in zones
        if str(zone.get("pln:category_code", "")) == typed_target.category_code
        and list(zone.get("pln:target_bsms", []) or [])
    ]
    if not matching_zones:
        _unresolved(
            result,
            "custom_zone_output_empty",
            target_id,
            "Custom zone generator selected no materializable parcels.",
        )
        return result

    selected_bsms: list[str] = []
    for zone in matching_zones:
        for bsm in zone["pln:target_bsms"]:
            selected_bsm = str(bsm)
            if selected_bsm not in selected_bsms:
                selected_bsms.append(selected_bsm)
    for bsm in selected_bsms:
        parcel = source_by_bsm.get(bsm)
        geometry = _as_geometry(_value(parcel, "geometry")) if parcel is not None else None
        if parcel is None:
            _unresolved(
                result,
                "missing_bsm",
                target_id,
                "Generated custom zone references an unavailable parcel.",
                bsm=bsm,
            )
            continue
        if geometry is None:
            _unresolved(
                result,
                "invalid_geometry",
                target_id,
                "Generated custom zone references a parcel with invalid geometry.",
                bsm=bsm,
            )
            continue
        result.changes.append(
            ParcelChange(
                bsm=bsm,
                action="reclassify",
                derived_from_bsms=[bsm],
                after_classification=classification,
                before_geometry_wkt=geometry.wkt,
                after_geometry_wkt=geometry.wkt,
                new_area_ha=float(_value(parcel, "area_ha", 0.0) or 0.0),
                intervention_id=target_id,
            )
        )
    if not result.unresolved_items:
        result.diagnostics.append({
            "code": "custom_zone_materialized",
            "target_id": target_id,
            "selected_count": len(result.changes),
        })
    return result


__all__ = ["CustomZoneMaterializationResult", "materialize_custom_zone_changes"]
