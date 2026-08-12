"""Selective spatial reads with a pyogrio-first GeoJSON fallback.

The port returns bounded feature batches.  Callers that need the complete
layer must use ``materialize`` at a local delivery boundary; the port itself
does not expose a full layer to agent state or model prompts.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Protocol

from app.contracts.spatial.spatial_delivery_contracts import (
    DeliverySpatialSnapshot,
    FeatureBatch,
    SpatialLayerRef,
    SpatialReadRequest,
)


class SpatialDataError(RuntimeError):
    """Raised when a spatial source cannot be read or filtered safely."""


class SpatialDataPort(Protocol):
    def describe(self, ref: SpatialLayerRef) -> SpatialLayerRef: ...
    def read(self, request: SpatialReadRequest) -> FeatureBatch: ...
    def read_by_bsms(self, ref: SpatialLayerRef, bsms: list[str], columns: list[str]) -> FeatureBatch: ...
    def materialize(self, ref: SpatialLayerRef) -> FeatureBatch: ...


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_bbox(values: Any) -> tuple[float, float, float, float] | None:
    if values is None:
        return None
    try:
        result = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None
    if len(result) != 4 or not all(math.isfinite(value) for value in result):
        return None
    west, south, east, north = result
    if west > east or south > north:
        return None
    return west, south, east, north


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _safe_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


def _is_geojson(ref: SpatialLayerRef) -> bool:
    return ref.driver.lower() in {"geojson", "json"} or Path(ref.path).suffix.lower() in {
        ".geojson",
        ".json",
    }


def _find_field(fields: list[str], *names: str) -> str | None:
    by_lower = {field_name.lower(): field_name for field_name in fields}
    for name in names:
        if name.lower() in by_lower:
            return by_lower[name.lower()]
    return None


def _resolve_columns(available: list[str], requested: list[str]) -> list[str]:
    if not requested:
        return list(available)
    by_lower = {field_name.lower(): field_name for field_name in available}
    resolved = []
    for column in requested:
        actual = column if column in available else by_lower.get(column.lower())
        if actual is None:
            raise ValueError(f"unknown spatial field: {column}")
        resolved.append(actual)
    return list(dict.fromkeys(resolved))


def _geometry_bounds(geometry: Any) -> tuple[float, float, float, float] | None:
    coordinates = (geometry or {}).get("coordinates") if isinstance(geometry, dict) else None
    values: list[tuple[float, float]] = []

    def collect(item: Any) -> None:
        if isinstance(item, (list, tuple)):
            if len(item) >= 2 and all(
                isinstance(value, (int, float)) and math.isfinite(value)
                for value in item[:2]
            ):
                values.append((float(item[0]), float(item[1])))
                return
            for child in item:
                collect(child)

    collect(coordinates)
    if not values:
        return None
    xs, ys = zip(*values)
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_intersects(left: tuple[float, float, float, float] | None, right: tuple[float, float, float, float]) -> bool:
    if left is None:
        return False
    return not (left[2] < right[0] or left[0] > right[2] or left[3] < right[1] or left[1] > right[3])


def _mask_intersects(geometry: Any, mask: dict[str, Any]) -> bool:
    try:
        from shapely.geometry import shape

        return bool(shape(geometry).intersects(shape(mask)))
    except Exception as exc:
        raise SpatialDataError("mask filtering requires valid GeoJSON geometries") from exc


_WHERE_PART = re.compile(
    r"^\s*(?P<field>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?P<operator>IN|=|!=|<>|<=|>=|<|>)\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)


def _property_value(properties: dict[str, Any], field: str) -> Any:
    for key, value in properties.items():
        if key.lower() == field.lower():
            return value
    return None


def _literal(value: str) -> Any:
    try:
        return ast.literal_eval(value.strip())
    except (SyntaxError, ValueError):
        return value.strip().strip("\"'")


def _where_matches(properties: dict[str, Any], where: str | None) -> bool:
    if not where:
        return True
    parts = re.split(r"\s+AND\s+", where, flags=re.IGNORECASE)
    for part in parts:
        match = _WHERE_PART.match(part)
        if match is None:
            raise SpatialDataError(f"GeoJSON fallback cannot parse where clause: {where!r}")
        actual = _property_value(properties, match.group("field"))
        operator = match.group("operator").upper()
        raw_value = match.group("value").strip()
        if operator == "IN":
            if not (raw_value.startswith("(") and raw_value.endswith(")")):
                raise SpatialDataError(f"invalid IN clause: {where!r}")
            values = [_literal(item) for item in raw_value[1:-1].split(",") if item.strip()]
            if actual not in values and str(actual) not in {str(value) for value in values}:
                return False
            continue
        expected = _literal(raw_value)
        try:
            if operator == "=" and not (actual == expected or str(actual) == str(expected)):
                return False
            if operator in {"!=", "<>"} and (actual == expected or str(actual) == str(expected)):
                return False
            if operator == "<" and not actual < expected:
                return False
            if operator == ">" and not actual > expected:
                return False
            if operator == "<=" and not actual <= expected:
                return False
            if operator == ">=" and not actual >= expected:
                return False
        except TypeError:
            return False
    return True


def _feature_bsm(properties: dict[str, Any]) -> str:
    value = _property_value(properties, "BSM")
    return "" if value is None else str(value)


class GeoJSONSpatialDataPort:
    """Deterministic fallback adapter for local GeoJSON artifacts."""

    def _load(self, ref: SpatialLayerRef) -> dict[str, Any]:
        try:
            payload = json.loads(Path(ref.path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpatialDataError(f"cannot read GeoJSON source: {ref.path}") from exc
        if payload.get("type") != "FeatureCollection":
            raise SpatialDataError(f"expected a GeoJSON FeatureCollection: {ref.path}")
        return payload

    def describe(self, ref: SpatialLayerRef) -> SpatialLayerRef:
        payload = self._load(ref)
        features = payload.get("features", [])
        fields = sorted(
            {
                str(key)
                for feature in features
                for key in (feature.get("properties") or {})
            }
        )
        bounds = [_geometry_bounds(feature.get("geometry")) for feature in features]
        valid_bounds = [bound for bound in bounds if bound is not None]
        bbox = None
        if valid_bounds:
            bbox = (
                min(bound[0] for bound in valid_bounds),
                min(bound[1] for bound in valid_bounds),
                max(bound[2] for bound in valid_bounds),
                max(bound[3] for bound in valid_bounds),
            )
        crs = ((payload.get("crs") or {}).get("properties") or {}).get("name", "")
        return ref.model_copy(
            update={
                "fields": fields,
                "feature_count": len(features),
                "bbox": ref.bbox or bbox,
                "crs": ref.crs or crs,
                "checksum": ref.checksum or _file_checksum(Path(ref.path)),
            }
        )

    def read(self, request: SpatialReadRequest) -> FeatureBatch:
        ref = self.describe(request.layer_ref)
        payload = self._load(ref)
        selected = _resolve_columns(ref.fields, request.columns)
        wanted = {str(bsm) for bsm in request.bsms}
        features = []
        for index, source in enumerate(payload.get("features", [])):
            properties = dict(source.get("properties") or {})
            if wanted and _feature_bsm(properties) not in wanted:
                continue
            if request.fids and index not in request.fids and source.get("id") not in request.fids:
                continue
            geometry = source.get("geometry")
            if request.bbox is not None and not _bbox_intersects(_geometry_bounds(geometry), request.bbox):
                continue
            if request.mask is not None and not _mask_intersects(geometry, request.mask):
                continue
            if not _where_matches(properties, request.where):
                continue
            if request.columns:
                properties = {key: properties[key] for key in selected if key in properties}
            item: dict[str, Any] = {
                "type": "Feature",
                "properties": _safe_json(properties),
            }
            if "id" in source:
                item["id"] = _safe_json(source["id"])
            if request.read_geometry:
                item["geometry"] = _safe_json(geometry)
            features.append(item)
        return FeatureBatch(
            layer_ref=ref,
            features=features,
            selected_columns=selected if request.columns else ref.fields,
            complete=False,
            feature_count=len(features),
        )

    def read_by_bsms(self, ref: SpatialLayerRef, bsms: list[str], columns: list[str]) -> FeatureBatch:
        return self.read(SpatialReadRequest(layer_ref=ref, bsms=bsms, columns=columns))

    def materialize(self, ref: SpatialLayerRef) -> FeatureBatch:
        result = self.read(SpatialReadRequest(layer_ref=ref, read_geometry=True))
        return result.model_copy(update={"complete": True, "feature_count": len(result.features)})


class PyogrioSpatialDataPort:
    """Use GDAL/pyogrio filters first and fall back for GeoJSON artifacts."""

    def __init__(self, *, prefer_pyogrio: bool = True, fallback: GeoJSONSpatialDataPort | None = None):
        self.prefer_pyogrio = prefer_pyogrio
        self.fallback = fallback or GeoJSONSpatialDataPort()

    @staticmethod
    def _pyogrio() -> Any | None:
        try:
            import pyogrio

            return pyogrio
        except ImportError:
            return None

    @staticmethod
    def _with_layer(call: Any, path: str, layer_name: str, **kwargs: Any) -> Any:
        try:
            return call(path, layer=layer_name, **kwargs)
        except Exception:
            if not layer_name:
                raise
            return call(path, **kwargs)

    def describe(self, ref: SpatialLayerRef) -> SpatialLayerRef:
        pyogrio = self._pyogrio() if self.prefer_pyogrio else None
        if pyogrio is None:
            return self.fallback.describe(ref)
        try:
            info = self._with_layer(
                pyogrio.read_info,
                ref.path,
                ref.layer_name,
                force_feature_count=True,
                force_total_bounds=True,
            )
            fields = [str(value) for value in info.get("fields", [])]
            return ref.model_copy(
                update={
                    "fields": fields,
                    "feature_count": int(info.get("features") or 0),
                    "bbox": ref.bbox or _finite_bbox(info.get("total_bounds")),
                    "crs": ref.crs or str(info.get("crs") or ""),
                    "driver": str(info.get("driver") or ref.driver),
                    "checksum": ref.checksum or _file_checksum(Path(ref.path)),
                }
            )
        except Exception as exc:
            if _is_geojson(ref):
                return self.fallback.describe(ref)
            raise SpatialDataError(f"cannot describe spatial source: {ref.path}") from exc

    def _read_dataframe(self, pyogrio: Any, request: SpatialReadRequest, ref: SpatialLayerRef) -> Any:
        available = ref.fields
        if not available:
            ref = self.describe(ref)
            available = ref.fields
        selected = _resolve_columns(available, request.columns)
        bsm_field = _find_field(available, "BSM", "bsm")
        read_columns = list(selected)
        if request.bsms and bsm_field and bsm_field not in read_columns:
            read_columns.append(bsm_field)
        effective_where = request.where
        if request.bsms and bsm_field:
            values = ", ".join(
                "'" + str(bsm).replace("'", "''") + "'" for bsm in request.bsms
            )
            bsm_where = f'"{bsm_field.replace(chr(34), chr(34) * 2)}" IN ({values})'
            effective_where = f"({effective_where}) AND ({bsm_where})" if effective_where else bsm_where
        kwargs: dict[str, Any] = {
            "columns": read_columns or None,
            "read_geometry": request.read_geometry,
            "bbox": request.bbox,
            "where": effective_where,
            "mask": None,
            "fids": request.fids or None,
            "use_arrow": True,
        }
        if request.mask is not None:
            try:
                from shapely.geometry import shape

                kwargs["mask"] = shape(request.mask)
            except Exception as exc:
                raise SpatialDataError("mask filtering requires a valid GeoJSON geometry") from exc
        try:
            return self._with_layer(pyogrio.read_dataframe, ref.path, ref.layer_name, **kwargs)
        except Exception:
            kwargs["use_arrow"] = False
            try:
                return self._with_layer(pyogrio.read_dataframe, ref.path, ref.layer_name, **kwargs)
            except Exception as exc:
                raise SpatialDataError(f"pyogrio read failed for {ref.path}") from exc

    def read(self, request: SpatialReadRequest) -> FeatureBatch:
        ref = self.describe(request.layer_ref)
        pyogrio = self._pyogrio() if self.prefer_pyogrio else None
        if pyogrio is None:
            return self.fallback.read(request.model_copy(update={"layer_ref": ref}))
        try:
            frame = self._read_dataframe(pyogrio, request, ref)
            raw_features = list(frame.iterfeatures(na="null", drop_id=False))
            requested = set(request.columns)
            wanted = {str(bsm) for bsm in request.bsms}
            features = []
            for feature in raw_features:
                properties = dict(feature.get("properties") or {})
                if wanted and _feature_bsm(properties) not in wanted:
                    continue
                if request.columns:
                    properties = {
                        key: value
                        for key, value in properties.items()
                        if key in requested or key.lower() in {item.lower() for item in requested}
                    }
                item = {"type": "Feature", "properties": _safe_json(properties)}
                if "id" in feature:
                    item["id"] = _safe_json(feature["id"])
                if request.read_geometry:
                    item["geometry"] = _safe_json(feature.get("geometry"))
                features.append(item)
            selected = request.columns or ref.fields
            return FeatureBatch(
                layer_ref=ref,
                features=features,
                selected_columns=list(selected),
                complete=False,
                feature_count=len(features),
            )
        except Exception as exc:
            if _is_geojson(ref):
                return self.fallback.read(request.model_copy(update={"layer_ref": ref}))
            if isinstance(exc, SpatialDataError):
                raise
            raise SpatialDataError(f"cannot read spatial source: {ref.path}") from exc

    def read_by_bsms(self, ref: SpatialLayerRef, bsms: list[str], columns: list[str]) -> FeatureBatch:
        return self.read(SpatialReadRequest(layer_ref=ref, bsms=bsms, columns=columns))

    def materialize(self, ref: SpatialLayerRef) -> FeatureBatch:
        result = self.read(SpatialReadRequest(layer_ref=ref, read_geometry=True))
        return result.model_copy(update={"complete": True, "feature_count": len(result.features)})


LocalSpatialDataPort = PyogrioSpatialDataPort


__all__ = [
    "SpatialDataError",
    "SpatialDataPort",
    "DeliverySpatialSnapshot",
    "GeoJSONSpatialDataPort",
    "PyogrioSpatialDataPort",
    "LocalSpatialDataPort",
]
