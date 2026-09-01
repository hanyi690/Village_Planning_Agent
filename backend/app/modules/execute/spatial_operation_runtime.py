"""Deterministic DATA-backed operation boundary for EXECUTE.

Workers never receive a selected WKT until this boundary has reloaded every
input representation from the frozen DATA catalog, revalidated snapshot,
digest, CRS and capability, and replayed the approved operation.  This makes
the candidate WKT an expected result/checksum rather than geometry authority.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from app.contracts.select.selection_decision import SelectionDecisionSet


def _current_world_admission(snapshot: Any) -> tuple[Any | None, dict[str, Any] | None]:
    """Build the immutable current-world admission index at EXECUTE time.

    SELECT's decision set is not itself an admission certificate.  Rebuild
    the index from the live DATA snapshot immediately before replay so a
    representation, resource, or capability cannot smuggle a planning/control
    source into an approved operation.
    """

    if snapshot is None:
        return None, {"code": "data_resource_catalog_snapshot_missing"}
    if not list(getattr(snapshot, "admission_decisions", ()) or ()):
        return None, {"code": "data_current_world_admission_missing"}
    try:
        from app.data.admission import build_admission_index

        index = build_admission_index(snapshot)
    except Exception:
        return None, {"code": "data_current_world_admission_invalid"}
    if not index.feature_keys or not index.resource_refs:
        return None, {"code": "data_current_world_admission_empty"}
    return index, None


class ExecutionResourceError(ValueError):
    """An approval-bound DATA resource cannot be deterministically executed."""

    def __init__(self, diagnostics: list[dict[str, Any]]):
        self.diagnostics = diagnostics
        codes = sorted({str(item.get("code") or "execution_resource_invalid") for item in diagnostics})
        super().__init__("; ".join(codes) or "execution_resource_invalid")


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _kind(value: Any) -> str:
    geom_type = str(getattr(value, "geom_type", "") or "").casefold()
    if geom_type in {"point", "multipoint"}:
        return "point"
    if geom_type in {"linestring", "multilinestring"}:
        return "line"
    if geom_type in {"polygon", "multipolygon"}:
        return "polygon"
    if geom_type in {"multipatch", "multisurface", "polyhedralsurface"}:
        return "multipatch"
    return "unknown"


def _load_shape(geometry: Any) -> Any:
    if not isinstance(geometry, Mapping):
        return None
    try:
        from shapely.geometry import shape

        result = shape(dict(geometry))
    except Exception:
        return None
    if result.is_empty or not result.is_valid:
        return None
    return result


def _float_parameter(parameters: Mapping[str, Any], name: str) -> float:
    try:
        value = float(parameters[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"operation parameter {name} is required and numeric") from exc
    if value <= 0:
        raise ValueError(f"operation parameter {name} must be positive")
    return value


def _transform(geometry: Any, source_crs: str, target_crs: str) -> Any:
    if not target_crs or source_crs == target_crs:
        return geometry
    from pyproj import Transformer
    from shapely.ops import transform

    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    return transform(transformer.transform, geometry)


def _metric_operation_inputs(
    inputs: list[Any],
    input_crs: str,
    parameters: Mapping[str, Any],
) -> tuple[list[Any], str, dict[str, Any]]:
    """Convert a declared metre distance to deterministic operation units."""

    if "distance_m" not in parameters:
        return inputs, input_crs, dict(parameters)
    distance_m = _float_parameter(parameters, "distance_m")
    from pyproj import CRS

    crs = CRS.from_user_input(input_crs)
    adjusted = dict(parameters)
    if crs.is_projected:
        factor = float(
            getattr((crs.axis_info or [None])[0], "unit_conversion_factor", 1.0)
            or 1.0
        )
        adjusted["distance"] = distance_m / factor
        return inputs, input_crs, adjusted
    if not crs.is_geographic:
        raise ValueError("distance_m requires a projected or geographic CRS")
    from shapely.ops import unary_union

    centroid = unary_union(inputs).centroid
    longitude = float(centroid.x)
    latitude = float(centroid.y)
    zone = max(1, min(60, int((longitude + 180.0) // 6.0) + 1))
    metric_crs = f"EPSG:{32600 + zone if latitude >= 0 else 32700 + zone}"
    adjusted["distance"] = distance_m
    return [
        _transform(item, input_crs, metric_crs) for item in inputs
    ], metric_crs, adjusted


def _execute_operation(
    operation: str,
    parameters: Mapping[str, Any],
    inputs: list[Any],
) -> Any:
    from shapely.ops import snap, split, unary_union

    if not inputs:
        raise ValueError("operation has no DATA geometry inputs")
    if operation in {"read", "representation_derivation", "assign", "reclassify"}:
        if len(inputs) != 1:
            raise ValueError(f"{operation} requires exactly one input resource")
        return inputs[0]
    if operation in {"union", "merge"}:
        return unary_union(inputs)
    if operation == "buffer":
        if len(inputs) != 1:
            raise ValueError("buffer requires exactly one input resource")
        return inputs[0].buffer(_float_parameter(parameters, "distance"))
    if operation == "offset":
        if len(inputs) != 1:
            raise ValueError("offset requires exactly one input resource")
        distance = _float_parameter(parameters, "distance")
        side = str(parameters.get("side") or "left")
        return inputs[0].parallel_offset(distance, side=side)
    if operation == "intersect":
        if len(inputs) < 2:
            raise ValueError("intersect requires at least two input resources")
        output = inputs[0]
        for item in inputs[1:]:
            output = output.intersection(item)
        return output
    if operation == "difference":
        if len(inputs) < 2:
            raise ValueError("difference requires at least two input resources")
        return inputs[0].difference(unary_union(inputs[1:]))
    if operation == "snap":
        if len(inputs) != 2:
            raise ValueError("snap requires exactly two input resources")
        return snap(inputs[0], inputs[1], _float_parameter(parameters, "tolerance"))
    if operation == "topology_repair":
        if len(inputs) != 1:
            raise ValueError("topology_repair requires exactly one input resource")
        try:
            from shapely import make_valid

            return make_valid(inputs[0])
        except (ImportError, AttributeError):
            return inputs[0].buffer(0)
    if operation == "point_placement":
        if len(inputs) != 1:
            raise ValueError("point_placement requires exactly one input resource")
        method = str(parameters.get("method") or "")
        if method == "identity":
            if _kind(inputs[0]) != "point":
                raise ValueError("point_placement identity requires point input")
            return inputs[0]
        if method != "representative_point":
            raise ValueError("point_placement requires an approved deterministic method")
        return inputs[0].representative_point()
    if operation == "network_connection":
        if len(inputs) < 2:
            raise ValueError("network_connection requires at least two DATA resources")
        method = str(parameters.get("method") or "")
        if method == "merge_connected":
            from shapely.ops import linemerge

            if any(_kind(item) != "line" for item in inputs):
                raise ValueError("merge_connected requires line inputs")
            return linemerge(unary_union(inputs))
        if method == "connect_nearest":
            from shapely.geometry import LineString
            from shapely.ops import nearest_points

            left = unary_union(inputs[:-1])
            right = inputs[-1]
            start, end = nearest_points(left, right)
            if start.equals(end):
                raise ValueError("network_connection inputs already touch")
            return LineString([start, end])
        raise ValueError(
            "network_connection requires approved merge_connected or connect_nearest method"
        )
    if operation == "split":
        if len(inputs) != 2:
            raise ValueError("split requires source and splitter resources")
        pieces = list(split(inputs[0], inputs[1]).geoms)
        try:
            index = int(parameters["part_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("split requires integer part_index") from exc
        if index < 0 or index >= len(pieces):
            raise ValueError("split part_index is outside the deterministic result")
        return pieces[index]
    raise ValueError(f"unsupported approved spatial operation: {operation}")


def _same_geometry(expected_wkt: str, actual: Any) -> bool:
    if not expected_wkt:
        return False
    try:
        from shapely import wkt

        expected = wkt.loads(expected_wkt)
    except Exception:
        return False
    if expected.is_empty or actual is None or actual.is_empty:
        return False
    try:
        return bool(
            expected.wkt == actual.wkt
            or expected.equals_exact(actual, tolerance=1e-12)
            or expected.equals(actual)
        )
    except Exception:
        return False


def materialize_approved_candidates(
    decision_set: SelectionDecisionSet,
    data_catalog: Any,
    candidate_by_id: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Reload and replay every selected resource operation.

    Returns a candidate catalog whose WKT was produced at this EXECUTE
    boundary plus immutable operation trace rows.  Any stale/missing input
    raises ``ExecutionResourceError`` before a worker is dispatched.
    """

    if data_catalog is None or getattr(data_catalog, "snapshot", None) is None:
        raise ExecutionResourceError([{"code": "data_resource_catalog_missing"}])
    decision_set = SelectionDecisionSet.model_validate(
        decision_set.model_dump(mode="python")
    )
    snapshot = data_catalog.snapshot
    diagnostics: list[dict[str, Any]] = []
    admission_index, admission_error = _current_world_admission(snapshot)
    if admission_error is not None:
        diagnostics.append(admission_error)
    if decision_set.data_snapshot_ref != str(snapshot.snapshot_id or ""):
        diagnostics.append({"code": "selection_data_snapshot_stale"})
    if decision_set.data_catalog_digest != str(snapshot.digest or ""):
        diagnostics.append({"code": "selection_data_catalog_digest_stale"})
    grouped: dict[str, list[Any]] = defaultdict(list)
    for decision in decision_set.decisions:
        grouped[decision.candidate_ref].append(decision)
    materialized = dict(candidate_by_id)
    traces: list[dict[str, Any]] = []
    for candidate_ref, decisions in sorted(grouped.items()):
        candidate = materialized.get(candidate_ref)
        if candidate is None:
            diagnostics.append({"code": "approved_candidate_missing", "candidate_ref": candidate_ref})
            continue
        operations = {item.operation for item in decisions}
        parameters = {str(sorted(item.operation_parameters.items())) for item in decisions}
        input_crs_values = {item.input_crs for item in decisions}
        output_crs_values = {item.output_crs for item in decisions}
        output_kinds = {item.geometry_kind for item in decisions}
        if any(len(values) != 1 for values in (operations, parameters, input_crs_values, output_crs_values, output_kinds)):
            diagnostics.append({"code": "approved_resource_operation_disagreement", "candidate_ref": candidate_ref})
            continue
        inputs: list[Any] = []
        live_refs: list[str] = []
        candidate_failed = False
        for decision in sorted(decisions, key=lambda item: item.selection_ref):
            representation = data_catalog.get_representation(decision.representation_ref)
            common = {
                "candidate_ref": candidate_ref,
                "selection_ref": decision.selection_ref,
            }
            if representation is None:
                diagnostics.append({"code": "approved_representation_missing", **common})
                candidate_failed = True
                continue
            if admission_index is None:
                candidate_failed = True
                continue
            from app.data.admission import (
                is_admitted_capability,
                is_admitted_representation,
            )

            if decision.resource_ref not in (
                admission_index.resource_refs
                | admission_index.representation_resource_refs
            ):
                diagnostics.append({
                    "code": "approved_resource_not_admitted_current_world",
                    "resource_ref": decision.resource_ref,
                    **common,
                })
                candidate_failed = True
                continue
            if not is_admitted_representation(
                snapshot,
                representation,
                index=admission_index,
            ):
                diagnostics.append({
                    "code": "approved_representation_not_admitted_current_world",
                    **common,
                })
                candidate_failed = True
                continue
            expected = {
                "resource_ref": decision.resource_ref,
                "geometry_ref": decision.geometry_ref,
                "source_snapshot_ref": decision.source_snapshot_ref,
                "content_digest": decision.resource_digest,
                "crs": decision.input_crs,
            }
            actual = {
                "resource_ref": str(representation.resource_ref or ""),
                "geometry_ref": str(representation.geometry_ref or ""),
                "source_snapshot_ref": str(representation.source_snapshot_ref or ""),
                "content_digest": str(representation.content_digest or ""),
                "crs": str(representation.crs or ""),
            }
            if expected != actual or str(representation.status or "") != "available":
                diagnostics.append({"code": "approved_representation_drift", "expected": expected, "actual": actual, **common})
                candidate_failed = True
                continue
            capabilities = list(
                data_catalog.capabilities_for(
                    decision.resource_ref,
                    decision.required_capability,
                )
                or []
            )
            capability = next(
                (
                    item
                    for item in capabilities
                    if str(item.capability_ref or "") == decision.capability_ref
                    and str(item.crs or "") == decision.input_crs
                    and str(item.geometry_kind or "") == decision.input_geometry_kind
                ),
                None,
            )
            if capability is None:
                diagnostics.append({"code": "approved_capability_missing_or_stale", **common})
                candidate_failed = True
                continue
            if not is_admitted_capability(
                snapshot,
                capability,
                index=admission_index,
            ):
                diagnostics.append({
                    "code": "approved_capability_not_admitted_current_world",
                    "capability_ref": decision.capability_ref,
                    **common,
                })
                candidate_failed = True
                continue
            if (
                str(capability.operation or "") != str(decision.required_capability or "")
                or str(capability.source_snapshot_ref or "")
                != str(snapshot.snapshot_id or "")
                or str(capability.content_digest or "")
                != str(representation.content_digest or "")
            ):
                diagnostics.append({
                    "code": "approved_capability_snapshot_or_digest_stale",
                    "capability_ref": decision.capability_ref,
                    **common,
                })
                candidate_failed = True
                continue
            geometry = data_catalog.resolve_geometry(
                resource_ref=decision.resource_ref,
                geometry_ref=decision.geometry_ref,
                representation_ref=decision.representation_ref,
                normalized=True,
            )
            shape = _load_shape(geometry)
            if shape is None or _kind(shape) != decision.input_geometry_kind:
                diagnostics.append({"code": "approved_data_geometry_invalid", **common})
                candidate_failed = True
                continue
            inputs.append(shape)
            live_refs.append(decision.resource_ref)
        if candidate_failed:
            continue
        operation = next(iter(operations))
        operation_parameters = dict(decisions[0].operation_parameters)
        input_crs = next(iter(input_crs_values))
        output_crs = next(iter(output_crs_values))
        output_kind = next(iter(output_kinds))
        try:
            operation_inputs, operation_crs, execution_parameters = (
                _metric_operation_inputs(
                    inputs,
                    input_crs,
                    operation_parameters,
                )
            )
            output = _execute_operation(
                operation,
                execution_parameters,
                operation_inputs,
            )
            output = _transform(output, operation_crs, output_crs)
        except Exception as exc:
            diagnostics.append({
                "code": "approved_spatial_operation_failed",
                "candidate_ref": candidate_ref,
                "operation": operation,
                "exception_type": type(exc).__name__,
            })
            continue
        if output is None or output.is_empty or not output.is_valid:
            diagnostics.append({"code": "approved_spatial_operation_empty_or_invalid", "candidate_ref": candidate_ref})
            continue
        if _kind(output) != output_kind:
            diagnostics.append({
                "code": "approved_operation_geometry_kind_mismatch",
                "candidate_ref": candidate_ref,
                "expected": output_kind,
                "actual": _kind(output),
            })
            continue
        expected_wkt = str(_value(candidate, "wkt", "") or "")
        if not _same_geometry(expected_wkt, output):
            diagnostics.append({
                "code": "approved_operation_result_mismatch",
                "candidate_ref": candidate_ref,
                "operation": operation,
            })
            continue
        geometry_wkt = output.wkt
        geometry_digest = "sha256:" + hashlib.sha256(
            geometry_wkt.encode("utf-8")
        ).hexdigest()
        update = {
            "wkt": geometry_wkt,
            "crs": output_crs,
            "kind": output_kind,
            "generation_operation": f"execute:{operation}",
        }
        if hasattr(candidate, "model_copy"):
            materialized[candidate_ref] = candidate.model_copy(update=update)
        elif isinstance(candidate, Mapping):
            materialized[candidate_ref] = {**dict(candidate), **update}
        traces.append({
            "change_ref": f"change:{candidate_ref}:{geometry_digest.removeprefix('sha256:')[:20]}",
            "candidate_ref": candidate_ref,
            "target_ref": decisions[0].target_ref,
            "operation": operation,
            "operation_parameters": operation_parameters,
            "input_resource_refs": sorted(live_refs),
            "input_representation_refs": sorted(item.representation_ref for item in decisions),
            "input_geometry_refs": sorted(item.geometry_ref for item in decisions),
            "source_snapshot_refs": sorted(item.source_snapshot_ref for item in decisions),
            "resource_digests": sorted(item.resource_digest for item in decisions),
            "capability_refs": sorted(item.capability_ref for item in decisions),
            "selection_refs": sorted(item.selection_ref for item in decisions),
            "input_crs": input_crs,
            "output_crs": output_crs,
            "geometry_kind": output_kind,
            "geometry_digest": geometry_digest,
        })
    if diagnostics:
        raise ExecutionResourceError(diagnostics)
    return materialized, traces


__all__ = [
    "ExecutionResourceError",
    "materialize_approved_candidates",
]
