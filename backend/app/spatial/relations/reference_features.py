"""Resolve relation references through the current DATA/WM read boundary."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.contracts.ground.constraint_factor import ConstraintFactor
from app.contracts.select.scenario import ScenarioFeature


_MAX_EXTERNAL_FEATURES = 24
_NON_GEOMETRIC_RELATIONS = frozenset({"serve", "service", "precedes"})


@dataclass(frozen=True)
class RelationReferenceResolution:
    """Bounded relation features materialized from admitted DATA refs."""

    features: dict[str, ScenarioFeature]
    diagnostics: tuple[str, ...] = ()


def resolve_relation_reference_features(
    context: Any,
    factors: Sequence[ConstraintFactor],
    *,
    scenario_id: str = "reference-context",
) -> RelationReferenceResolution:
    """Resolve direct World Model entity refs to DATA-owned geometries.

    A relation object is accepted only when its reference identifies a current
    WM entity and the DATA catalog contains one or more valid normalized
    features for that entity.  Names are not fuzzy-matched and no geometry is
    synthesized from a label or a village center.
    """

    requests: dict[str, list[str]] = {}
    for factor in sorted(factors, key=lambda item: item.factor_id):
        relation_key = str(factor.evaluator_key or factor.kind or "").strip()
        if relation_key in _NON_GEOMETRIC_RELATIONS or factor.object_ref_kind == "target":
            continue
        reference = str(factor.object_ref or "").strip()
        if reference:
            requests.setdefault(reference, []).append(
                factor.factor_id.removeprefix("factor:")
            )
    if not requests:
        return RelationReferenceResolution(features={})

    catalog = getattr(context, "data_resource_catalog", None)
    if catalog is None:
        return RelationReferenceResolution(
            features={},
            diagnostics=("external_relation_data_catalog_unavailable",),
        )

    features: dict[str, ScenarioFeature] = {}
    diagnostics: list[str] = []
    for reference in sorted(requests):
        source_features = list(catalog.features_for_entity(reference) or [])
        if not source_features:
            diagnostics.append(f"external_relation_entity_unresolved:{reference}")
            continue
        feature = _scenario_feature_from_data(
            context,
            reference,
            source_features,
            relation_ids=requests[reference],
            scenario_id=scenario_id,
        )
        if feature is None:
            diagnostics.append(f"external_relation_data_geometry_unavailable:{reference}")
            continue
        features[reference] = feature
        if len(features) >= _MAX_EXTERNAL_FEATURES:
            diagnostics.append("external_relation_reference_bound_reached")
            break
    return RelationReferenceResolution(
        features=features,
        diagnostics=tuple(sorted(dict.fromkeys(diagnostics))),
    )


def _scenario_feature_from_data(
    context: Any,
    reference: str,
    source_features: list[Any],
    *,
    relation_ids: list[str],
    scenario_id: str,
) -> ScenarioFeature | None:
    from shapely.geometry import shape
    from shapely.ops import unary_union

    valid: list[tuple[Any, Any]] = []
    for source_feature in source_features:
        geometry_payload = getattr(source_feature, "normalized_geometry", None)
        if not isinstance(geometry_payload, dict):
            continue
        try:
            geometry = shape(geometry_payload)
        except Exception:
            continue
        if geometry.is_empty or not geometry.is_valid:
            continue
        valid.append((source_feature, geometry))
    if not valid:
        return None
    try:
        geometry = unary_union([item[1] for item in valid])
    except Exception:
        return None
    if geometry.is_empty or not geometry.is_valid:
        return None

    source_ids = sorted({
        str(getattr(feature, "source_feature_ref", "") or "")
        for feature, _geometry in valid
        if str(getattr(feature, "source_feature_ref", "") or "")
    })
    dataset_refs = sorted({
        str(getattr(feature, "dataset_ref", "") or "")
        for feature, _geometry in valid
        if str(getattr(feature, "dataset_ref", "") or "")
    })
    resource_refs = sorted({
        f"resource:{getattr(feature, 'dataset_ref', '')}:{getattr(feature, 'source_feature_ref', '')}"
        for feature, _geometry in valid
        if getattr(feature, "dataset_ref", "") and getattr(feature, "source_feature_ref", "")
    })
    representations = []
    for feature, _geometry in valid:
        representations.extend(
            getattr(context.data_resource_catalog, "representations_for_feature", lambda *_: [])(
                str(getattr(feature, "source_feature_ref", "") or ""),
                dataset_ref=str(getattr(feature, "dataset_ref", "") or ""),
            )
            or []
        )
    representation_refs = sorted({
        str(getattr(item, "representation_ref", "") or "")
        for item in representations
        if str(getattr(item, "representation_ref", "") or "")
    })
    snapshot = getattr(context.data_resource_catalog, "snapshot", None)
    world_model = getattr(context, "world_model", None)
    geometry_kind = {
        "Point": "point",
        "MultiPoint": "point",
        "LineString": "line",
        "MultiLineString": "line",
        "Polygon": "polygon",
        "MultiPolygon": "polygon",
    }.get(geometry.geom_type)
    if geometry_kind is None:
        return None
    source_refs = [*resource_refs, *representation_refs, *source_ids]
    if not source_refs:
        return None
    candidate_id = "reference:" + hashlib.sha256(
        "|".join([reference, *source_refs]).encode("utf-8")
    ).hexdigest()[:24]
    crs = str(
        getattr(representations[0], "crs", "")
        if representations
        else getattr(valid[0][0], "normalized_crs", "")
        or ""
    )
    if not crs:
        return None
    return ScenarioFeature(
        feature_id=f"feature:{scenario_id}:{candidate_id}",
        scenario_id=scenario_id or "reference-context",
        target_id=reference,
        candidate_id=candidate_id,
        geometry_kind=geometry_kind,
        geometry_wkt=geometry.wkt,
        crs=crs,
        generation_operation="relation_data_reference",
        source_refs=source_refs,
        resource_refs=resource_refs,
        representation_refs=representation_refs,
        source_snapshot_refs=[
            str(getattr(snapshot, "snapshot_id", "") or "")
        ] if getattr(snapshot, "snapshot_id", "") else [],
        source_feature_ids=source_ids,
        entity_refs=[reference],
        evidence_refs=[reference, *source_refs],
        world_model_digest=str(
            getattr(world_model, "snapshot_digest", "") or ""
        ),
        relation_ids=sorted(set(relation_ids)),
    )


__all__ = [
    "RelationReferenceResolution",
    "resolve_relation_reference_features",
]
