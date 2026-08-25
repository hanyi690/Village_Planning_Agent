"""Deterministic Shapely/pyproj evaluators for spatial relation factors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from shapely import wkt
from shapely.ops import transform

from app.contracts.planning.constraint_factor import (
    ConstraintFactor,
    RelationMeasurement,
    RelationSatisfaction,
)
from app.contracts.planning.relation_parameters import (
    AvoidConstraintParameters,
    CoLocateParameters,
    DistanceParameters,
)


def _feature_ref(feature: object) -> str:
    return str(getattr(feature, "feature_id", "") or getattr(feature, "target_id", ""))


def _feature_wkt(feature: object) -> str:
    return str(getattr(feature, "geometry_wkt", "") or "")


def _feature_crs(feature: object) -> str:
    return str(getattr(feature, "crs", "") or "")


def _as_geometry(feature: object):
    try:
        geometry = wkt.loads(_feature_wkt(feature))
    except Exception:
        return None
    return geometry if not geometry.is_empty and geometry.is_valid else None


def _crs_is_geographic(crs: str) -> bool:
    value = crs.upper().replace(" ", "")
    return value in {"EPSG:4326", "EPSG:4490", "CRS:84"} or "4326" in value


def _project_for_distance(left, right, left_crs: str, right_crs: str, metric_crs: str):
    if not left_crs or not right_crs:
        return None
    if left_crs.upper() == right_crs.upper() and not _crs_is_geographic(left_crs):
        return left, right, left_crs
    try:
        from pyproj import Transformer

        left_transformer = Transformer.from_crs(left_crs, metric_crs, always_xy=True)
        right_transformer = Transformer.from_crs(right_crs, metric_crs, always_xy=True)
        return (
            transform(left_transformer.transform, left),
            transform(right_transformer.transform, right),
            metric_crs,
        )
    except Exception:
        return None


def _base_satisfaction(
    factor: ConstraintFactor,
    subject: object,
    object_: object,
    *,
    scenario_id: str,
    evaluator_version: str,
):
    return dict(
        relation_id=factor.factor_id.removeprefix("factor:"),
        scenario_id=scenario_id,
        subject_ref=factor.subject_ref,
        object_ref=factor.object_ref,
        subject_feature_refs=[_feature_ref(subject)],
        object_feature_refs=[_feature_ref(object_)],
        criticality="hard" if factor.hard else "soft",
        factor_ids=[factor.factor_id],
        evidence_refs=list(factor.evidence_refs),
        evaluator_version=evaluator_version,
        evaluator_key=factor.evaluator_key or factor.kind,
        source_snapshot_refs=list(factor.source_snapshot_refs),
        input_status=factor.input_status,
    )


class GeometryRelationEvaluator:
    evaluator_key = "geometry"
    version = "relation-evaluator-v1"

    def evaluate(
        self,
        factor: ConstraintFactor,
        features: Mapping[str, Sequence[object]],
        context: object,
    ) -> RelationSatisfaction:
        subjects = list(features.get(factor.subject_ref, ()))
        objects = list(features.get(factor.object_ref, ()))
        if not subjects or not objects:
            return RelationSatisfaction(
                relation_id=factor.factor_id.removeprefix("factor:"),
                scenario_id=str(getattr(context, "scenario_id", "") or ""),
                subject_ref=factor.subject_ref,
                object_ref=factor.object_ref,
                status="not_evaluable",
                criticality="hard" if factor.hard else "soft",
                factor_ids=[factor.factor_id],
                evidence_refs=list(factor.evidence_refs),
                evaluator_version=self.version,
                detail="subject or object feature geometry is missing",
            )
        subject = subjects[0]
        object_ = objects[0]
        left = _as_geometry(subject)
        right = _as_geometry(object_)
        base = _base_satisfaction(
            factor,
            subject,
            object_,
            scenario_id=str(getattr(context, "scenario_id", "") or ""),
            evaluator_version=self.version,
        )
        if left is None or right is None:
            return RelationSatisfaction(
                **base,
                status="not_evaluable",
                detail="subject or object geometry is invalid or empty",
            )

        key = factor.evaluator_key or factor.kind
        left_crs = _feature_crs(subject)
        right_crs = _feature_crs(object_)
        if not left_crs or not right_crs:
            return RelationSatisfaction(
                **base,
                status="not_evaluable",
                detail="relation evaluation requires CRS on both feature geometries",
            )
        if key not in {"near", "far", "co_locate"} and left_crs.upper() != right_crs.upper():
            return RelationSatisfaction(
                **base,
                status="not_evaluable",
                detail="topological relation requires matching feature CRS",
            )
        if key in {"near", "far", "co_locate"}:
            return self._distance(key, factor, subject, object_, left, right, base, context)
        if key in {"contain", "contains", "within_allowed_area"}:
            return self._boolean(
                factor,
                left.contains(right),
                base,
                "contains",
                value=left.contains(right),
                operator="contains",
            )
        if key == "within":
            return self._boolean(factor, left.within(right), base, "within", value=left.within(right), operator="eq")
        if key == "intersects":
            return self._boolean(factor, left.intersects(right), base, "intersects", value=left.intersects(right), operator="eq")
        if key == "overlaps":
            return self._boolean(factor, left.overlaps(right), base, "overlaps", value=left.overlaps(right), operator="eq")
        if key in {"avoid", "avoid_constraint"}:
            parameters = factor.parameters
            buffer_m = (
                float(getattr(parameters, "buffer_m", 0.0) or 0.0)
                if isinstance(parameters, AvoidConstraintParameters)
                else 0.0
            )
            if buffer_m > 0:
                projected = _project_for_distance(
                    left,
                    right,
                    left_crs,
                    right_crs,
                    str(getattr(context, "metric_crs", "EPSG:3857") or "EPSG:3857"),
                )
                if projected is None:
                    return RelationSatisfaction(
                        **base,
                        status="not_evaluable",
                        detail="buffered avoidance requires compatible/projectable CRS",
                    )
                projected_left, projected_right, metric_crs = projected
                passed = projected_left.disjoint(projected_right.buffer(buffer_m))
                status = "satisfied" if passed else "violated"
                return RelationSatisfaction(
                    **base,
                    status=status,
                    measurement=RelationMeasurement(
                        value=passed,
                        threshold=True,
                        operator="eq",
                        method="disjoint_buffered_constraint",
                        crs=metric_crs,
                    ),
                    evaluation_trace=[
                        f"avoid-buffer:{_feature_ref(subject)}:{_feature_ref(object_)}:{buffer_m:g}"
                    ],
                    score=1.0 if passed else 0.0,
                )
            return self._boolean(
                factor,
                left.disjoint(right),
                base,
                "disjoint",
                value=left.disjoint(right),
                operator="eq",
            )
        if key in {"adjacent"}:
            return self._boolean(
                factor,
                left.touches(right),
                base,
                "touches",
                value=left.touches(right),
                operator="eq",
            )
        return RelationSatisfaction(
            **base,
            status="deferred",
            detail=f"unsupported geometry evaluator: {key}",
        )

    def _distance(self, key, factor, subject, object_, left, right, base, context):
        parameters = factor.parameters
        threshold = None
        if isinstance(parameters, DistanceParameters):
            threshold = parameters.max_distance_m
        elif isinstance(parameters, CoLocateParameters):
            threshold = parameters.max_distance_m
        if threshold is None:
            return RelationSatisfaction(
                **base,
                status="deferred",
                detail="distance relation is missing typed threshold parameters",
            )
        projected = _project_for_distance(
            left,
            right,
            _feature_crs(subject),
            _feature_crs(object_),
            str(getattr(context, "metric_crs", "EPSG:3857") or "EPSG:3857"),
        )
        if projected is None:
            return RelationSatisfaction(
                **base,
                status="not_evaluable",
                detail="distance relation requires compatible/projectable CRS",
            )
        projected_left, projected_right, metric_crs = projected
        value = float(projected_left.distance(projected_right))
        if key == "far":
            status = "satisfied" if value > threshold else "violated"
            operator = "gt"
        else:
            status = "satisfied" if value <= threshold else "violated"
            operator = "lte"
        return RelationSatisfaction(
            **base,
            status=status,
            measurement=RelationMeasurement(
                value=value,
                unit="m",
                threshold=threshold,
                operator=operator,
                method="shapely_distance_projected",
                crs=metric_crs,
            ),
            evaluation_trace=[f"distance:{_feature_ref(subject)}:{_feature_ref(object_)}"],
            score=1.0 if status == "satisfied" else 0.0,
        )

    def _boolean(self, factor, passed, base, method, *, value, operator):
        status = "satisfied" if passed else "violated"
        return RelationSatisfaction(
            **base,
            status=status,
            measurement=RelationMeasurement(
                value=value,
                threshold=True,
                operator=operator,
                method=method,
            ),
            evaluation_trace=[method],
            score=1.0 if passed else 0.0,
        )


__all__ = ["GeometryRelationEvaluator"]
