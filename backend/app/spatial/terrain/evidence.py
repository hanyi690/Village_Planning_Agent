"""Windowed and sampled DEM evidence with deterministic disk caching.

The service sits below SELECT. It measures terrain and returns typed evidence;
it neither chooses a parcel nor modifies workflow state.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from uuid import uuid4

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.features import geometry_mask
from rasterio.transform import Affine
from rasterio.windows import Window, from_bounds
from rasterio.warp import transform, transform_geom
from shapely import from_wkt, normalize, to_geojson
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from app.contracts.spatial.terrain_evidence import (
    TerrainEvidence,
    TerrainEvidenceConfig,
    TerrainEvidenceProvenance,
    TerrainPointSample,
    TerrainPointSampleSet,
    TerrainRasterMetadata,
    TerrainStatistics,
)


class TerrainSourceError(ValueError):
    """Raised when no safe, existing DEM source can be resolved."""


@dataclass(frozen=True)
class _ResolvedTerrainSource:
    path: Path
    origin: str


_CHECKSUM_CACHE: dict[tuple[str, int, int], str] = {}


def _path_from_raster_ref(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, Path)):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("path") or "")
    return str(getattr(value, "path", "") or "")


def _is_within(path: Path, roots: Sequence[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def resolve_dem_source(
    *,
    planning_context: Any | None = None,
    catalog: Any | None = None,
    explicit_path: str | Path | None = None,
    allowed_roots: Sequence[str | Path] = (),
) -> _ResolvedTerrainSource:
    """Resolve a DEM without village-name or absolute-path assumptions.

    Resolution order is authoritative session context, explicit catalog, then
    an explicit path. Explicit paths are accepted only under caller-supplied
    roots, preventing an API value from becoming an arbitrary file read.
    """

    workspace = getattr(planning_context, "workspace", None)
    rasters = getattr(workspace, "rasters", None)
    context_path = _path_from_raster_ref(getattr(rasters, "dem", None))
    if context_path:
        path = Path(context_path).expanduser().resolve()
        if path.is_file():
            return _ResolvedTerrainSource(path=path, origin="planning_context")

    if catalog is not None:
        # The legacy ``DataCatalog`` exposes a provider driver while the
        # generic DATA catalog exposes immutable features/representations.
        # Keep both behind this resolver instead of making SELECT construct a
        # legacy catalog (which silently reintroduced Bundle coupling).
        finder = getattr(catalog, "find_source_by_layer_type", None)
        if callable(finder):
            source = finder("dem")
            if source is not None:
                result = source.fetch()
                if bool(getattr(result, "success", False)):
                    catalog_path = _path_from_raster_ref(getattr(result, "data", None))
                    if not catalog_path:
                        catalog_path = str(getattr(result, "path", "") or "")
                    path = Path(catalog_path).expanduser().resolve()
                    if path.is_file():
                        return _ResolvedTerrainSource(path=path, origin="catalog")

        # Generic raster rows carry their path as a source attribute.  DATA
        # does not prescribe a field name, so only accept an explicit,
        # path-like value and never infer a file from a layer label alone.
        snapshot = getattr(catalog, "snapshot", catalog)
        for feature in tuple(getattr(snapshot, "features", ()) or ()):
            if str(getattr(feature, "geometry_kind", "") or "").casefold() != "raster":
                continue
            attributes = getattr(feature, "raw_attributes", {}) or {}
            candidate = (
                attributes.get("path")
                or attributes.get("file_path")
                or attributes.get("raster_path")
                or attributes.get("uri")
                or attributes.get("source_uri")
            )
            candidate_path = _path_from_raster_ref(candidate)
            if not candidate_path or "://" in candidate_path:
                continue
            path = Path(candidate_path).expanduser().resolve()
            if path.is_file():
                return _ResolvedTerrainSource(path=path, origin="data_resource_catalog")

    if explicit_path is not None:
        if not allowed_roots:
            raise TerrainSourceError("explicit DEM path requires at least one allowed root")
        path = Path(explicit_path).expanduser().resolve()
        roots = tuple(Path(root).expanduser().resolve() for root in allowed_roots)
        if not _is_within(path, roots):
            raise TerrainSourceError("explicit DEM path is outside the allowed roots")
        if path.is_file():
            return _ResolvedTerrainSource(path=path, origin="explicit_path")
        raise TerrainSourceError("explicit DEM path does not exist or is not a file")

    raise TerrainSourceError("no readable DEM found in PlanningContext, catalog, or explicit path")


def _sha256_file(path: Path) -> str:
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    cached = _CHECKSUM_CACHE.get(key)
    if cached:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    value = "sha256:" + digest.hexdigest()
    _CHECKSUM_CACHE[key] = value
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_payload(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _coerce_geometry(value: Any) -> BaseGeometry:
    if isinstance(value, BaseGeometry):
        return value
    if isinstance(value, str):
        return from_wkt(value)
    if isinstance(value, dict):
        if value.get("type") == "Feature":
            value = value.get("geometry") or {}
        return shape(value)
    geometry = getattr(value, "geometry", None)
    if geometry is not None:
        return _coerce_geometry(geometry)
    raise TypeError("geometry must be Shapely, WKT, GeoJSON, or expose .geometry")


def _empty_stats(unit: str, total: int = 0) -> TerrainStatistics:
    return TerrainStatistics(
        unit=unit,
        total_cell_count=total,
        valid_cell_count=0,
        valid_fraction=0.0,
    )


def _statistics(values: np.ndarray, *, unit: str, total: int) -> TerrainStatistics:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    count = int(finite.size)
    if count == 0:
        return _empty_stats(unit, total)
    return TerrainStatistics(
        unit=unit,
        total_cell_count=total,
        valid_cell_count=count,
        valid_fraction=count / total if total else 0.0,
        minimum=float(np.min(finite)),
        maximum=float(np.max(finite)),
        mean=float(np.mean(finite)),
        median=float(np.median(finite)),
        p10=float(np.percentile(finite, 10)),
        p90=float(np.percentile(finite, 90)),
        standard_deviation=float(np.std(finite)),
    )


def _integer_window(window: Window, width: int, height: int, padding: int) -> Window | None:
    left = max(0, math.floor(window.col_off) - padding)
    top = max(0, math.floor(window.row_off) - padding)
    right = min(width, math.ceil(window.col_off + window.width) + padding)
    bottom = min(height, math.ceil(window.row_off + window.height) + padding)
    if right <= left or bottom <= top:
        return None
    return Window(left, top, right - left, bottom - top)


def _window_tuple(window: Window | None) -> tuple[int, int, int, int]:
    if window is None:
        return (0, 0, 0, 0)
    return (
        int(window.col_off),
        int(window.row_off),
        int(window.width),
        int(window.height),
    )


def _neighbourhood_valid(valid: np.ndarray) -> np.ndarray:
    result = valid.copy()
    result[0, :] = False
    result[-1, :] = False
    result[:, 0] = False
    result[:, -1] = False
    result[1:, :] &= valid[:-1, :]
    result[:-1, :] &= valid[1:, :]
    result[:, 1:] &= valid[:, :-1]
    result[:, :-1] &= valid[:, 1:]
    return result


def _horizontal_pixel_metres(
    crs: CRS,
    affine: Affine,
    window: Window,
) -> tuple[float, float, str]:
    center_col = window.col_off + window.width / 2.0
    center_row = window.row_off + window.height / 2.0
    p0 = affine * (center_col + 0.5, center_row + 0.5)
    px = affine * (center_col + 1.5, center_row + 0.5)
    py = affine * (center_col + 0.5, center_row + 1.5)
    if crs.is_geographic:
        geod = crs.get_geod()
        _, _, dx = geod.inv(p0[0], p0[1], px[0], px[1])
        _, _, dy = geod.inv(p0[0], p0[1], py[0], py[1])
        return abs(float(dx)), abs(float(dy)), "geodesic_cell_vectors"
    axis = crs.axis_info
    conversion = float(axis[0].unit_conversion_factor) if axis else 1.0
    dx = math.hypot(px[0] - p0[0], px[1] - p0[1]) * conversion
    dy = math.hypot(py[0] - p0[0], py[1] - p0[1]) * conversion
    return abs(dx), abs(dy), "projected_axis_units"


def _slope_grid(elevation_m: np.ndarray, dx_m: float, dy_m: float) -> np.ndarray:
    if elevation_m.shape[0] < 3 or elevation_m.shape[1] < 3 or dx_m <= 0 or dy_m <= 0:
        return np.full(elevation_m.shape, np.nan, dtype=np.float64)
    finite = np.isfinite(elevation_m)
    filled = np.where(finite, elevation_m, 0.0)
    rise_y, rise_x = np.gradient(filled, dy_m, dx_m)
    slope = np.degrees(np.arctan(np.hypot(rise_x, rise_y)))
    slope[~_neighbourhood_valid(finite)] = np.nan
    return slope


class TerrainEvidenceService:
    """Read bounded DEM windows and return immutable evidence contracts."""

    def __init__(
        self,
        source: _ResolvedTerrainSource,
        *,
        config: TerrainEvidenceConfig | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        self.source = source
        self.config = config or TerrainEvidenceConfig()
        self.cache_dir = Path(cache_dir).resolve() if cache_dir is not None else None
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        # 同一服务实例内按投影几何哈希预计算：一个地块被多个候选引用时只算一次
        # （候选池是村簇，同一 parcel 会出现在大量候选里，避免重复 DEM 窗口读）。
        self._geometry_memo: dict[str, TerrainEvidence] = {}
        self.metadata = self._inspect_source()

    @classmethod
    def open(
        cls,
        *,
        planning_context: Any | None = None,
        catalog: Any | None = None,
        explicit_path: str | Path | None = None,
        allowed_roots: Sequence[str | Path] = (),
        config: TerrainEvidenceConfig | None = None,
        cache_dir: str | Path | None = None,
    ) -> "TerrainEvidenceService":
        source = resolve_dem_source(
            planning_context=planning_context,
            catalog=catalog,
            explicit_path=explicit_path,
            allowed_roots=allowed_roots,
        )
        return cls(source, config=config, cache_dir=cache_dir)

    def _inspect_source(self) -> TerrainRasterMetadata:
        path = self.source.path
        stat = path.stat()
        diagnostics: list[str] = []
        with rasterio.open(path) as dataset:
            crs = dataset.crs
            affine = dataset.transform
            determinant = affine.a * affine.e - affine.b * affine.d
            if crs is None:
                diagnostics.append("missing_crs")
            if not all(math.isfinite(value) for value in tuple(affine)[:6]):
                diagnostics.append("non_finite_transform")
            if abs(determinant) <= 1e-18:
                diagnostics.append("non_invertible_transform")
            axis_x = (affine.a, affine.d)
            axis_y = (affine.b, affine.e)
            norm_x = math.hypot(*axis_x)
            norm_y = math.hypot(*axis_y)
            if norm_x > 0.0 and norm_y > 0.0:
                normalized_dot = abs(
                    (axis_x[0] * axis_y[0] + axis_x[1] * axis_y[1])
                    / (norm_x * norm_y)
                )
                if normalized_dot > 1e-6:
                    diagnostics.append("non_orthogonal_pixel_axes")
            if dataset.width <= 0 or dataset.height <= 0:
                diagnostics.append("empty_raster")
            if dataset.count < self.config.band:
                diagnostics.append("configured_band_missing")
            if dataset.nodata is None:
                diagnostics.append("nodata_not_declared")
            elif not math.isfinite(float(dataset.nodata)):
                diagnostics.append("non_finite_nodata")
            bounds = dataset.bounds
            if not all(math.isfinite(value) for value in bounds):
                diagnostics.append("non_finite_bounds")
            parsed_crs = CRS.from_user_input(crs) if crs is not None else None
            fatal = {
                "missing_crs",
                "non_finite_transform",
                "non_invertible_transform",
                "non_orthogonal_pixel_axes",
                "empty_raster",
                "configured_band_missing",
                "non_finite_bounds",
            }
            return TerrainRasterMetadata(
                source_path=str(path),
                source_origin=self.source.origin,
                source_sha256=_sha256_file(path),
                source_size_bytes=stat.st_size,
                source_mtime_ns=stat.st_mtime_ns,
                crs=str(crs or ""),
                transform=tuple(float(value) for value in tuple(affine)[:6]),
                bounds=tuple(float(value) for value in bounds),
                width=dataset.width,
                height=dataset.height,
                band_count=dataset.count,
                dtype=str(dataset.dtypes[self.config.band - 1]) if dataset.count >= self.config.band else "",
                nodata=(
                    float(dataset.nodata)
                    if dataset.nodata is not None and math.isfinite(float(dataset.nodata))
                    else None
                ),
                pixel_size_x=math.hypot(affine.a, affine.d),
                pixel_size_y=math.hypot(affine.b, affine.e),
                is_geographic=bool(parsed_crs and parsed_crs.is_geographic),
                valid=not any(item in fatal for item in diagnostics),
                diagnostics=tuple(diagnostics),
            )

    def _cache_path(self, key: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{key.removeprefix('sha256:')}.json"

    def _read_cached(self, key: str, model: type[Any]) -> Any | None:
        path = self._cache_path(key)
        if path is None or not path.is_file():
            return None
        try:
            value = model.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(value, TerrainEvidence):
            if (
                value.provenance.cache_key != key
                or value.provenance.source_sha256 != self.metadata.source_sha256
            ):
                return None
            provenance = value.provenance.model_copy(update={"cache_hit": True})
            return value.model_copy(update={"provenance": provenance})
        if isinstance(value, TerrainPointSampleSet):
            if value.cache_key != key or value.source_sha256 != self.metadata.source_sha256:
                return None
            return value.model_copy(update={"cache_hit": True})
        return value

    def _write_cached(self, key: str, value: Any) -> None:
        path = self._cache_path(key)
        if path is None:
            return
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        temporary.write_text(value.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def analyze_geometry(
        self,
        subject_id: str,
        geometry: Any,
        *,
        geometry_crs: str,
    ) -> TerrainEvidence:
        diagnostics: list[str] = list(self.metadata.diagnostics)
        try:
            source_geometry = _coerce_geometry(geometry)
            if source_geometry.is_empty or not source_geometry.is_valid:
                raise ValueError("geometry is empty or invalid")
            source_crs = CRS.from_user_input(geometry_crs)
        except (TypeError, ValueError) as exc:
            return self._terminal_evidence(
                subject_id,
                status="invalid_geometry",
                geometry_crs=str(geometry_crs),
                geometry_digest=_sha256_payload({"invalid": str(geometry)}),
                diagnostics=diagnostics + [f"invalid_geometry:{exc}"],
            )

        with rasterio.open(self.source.path) as dataset:
            if not self.metadata.valid:
                return self._terminal_evidence(
                    subject_id,
                    status="invalid_raster",
                    geometry_crs=str(source_crs),
                    geometry_digest=_sha256_payload(mapping(source_geometry)),
                    diagnostics=diagnostics,
                )
            try:
                projected_geojson = transform_geom(
                    source_crs.to_string(),
                    dataset.crs,
                    json.loads(to_geojson(source_geometry)),
                    precision=15,
                )
                projected_geometry = normalize(shape(projected_geojson))
            except (TypeError, ValueError, rasterio.errors.RasterioError) as exc:
                return self._terminal_evidence(
                    subject_id,
                    status="invalid_geometry",
                    geometry_crs=str(source_crs),
                    geometry_digest=_sha256_payload(mapping(source_geometry)),
                    diagnostics=diagnostics + [f"geometry_transform_failed:{exc}"],
                )
            geometry_digest = "sha256:" + hashlib.sha256(projected_geometry.wkb).hexdigest()
            key = _sha256_payload(
                {
                    "schema": "terrain-evidence-1.0",
                    "source": self.metadata.source_sha256,
                    "subject_id": str(subject_id),
                    "geometry": geometry_digest,
                    "geometry_crs": str(source_crs),
                    "config": self.config.model_dump(mode="json"),
                }
            )
            memo_hit = self._geometry_memo.get(geometry_digest)
            if memo_hit is not None:
                # 同一地块几何复用已计算的证据；只重绑 subject/evidence_id。
                rebound = memo_hit.model_copy(update={
                    "subject_id": str(subject_id),
                    "evidence_id": f"terrain-{key.removeprefix('sha256:')[:24]}",
                })
                if rebound.provenance is not None:
                    rebound = rebound.model_copy(update={
                        "provenance": rebound.provenance.model_copy(update={
                            "cache_key": key,
                            "cache_hit": True,
                        }),
                    })
                # 保留 subject 级内容寻址缓存（测试断言每 subject 一文件）；
                # memo 只避免昂贵的 DEM 窗口读，不替代磁盘缓存。
                self._write_cached(key, rebound)
                return rebound
            cached = self._read_cached(key, TerrainEvidence)
            if cached is not None:
                self._geometry_memo[geometry_digest] = cached
                return cached

            raster_bounds = shape(
                {
                    "type": "Polygon",
                    "coordinates": [[
                        [dataset.bounds.left, dataset.bounds.bottom],
                        [dataset.bounds.right, dataset.bounds.bottom],
                        [dataset.bounds.right, dataset.bounds.top],
                        [dataset.bounds.left, dataset.bounds.top],
                        [dataset.bounds.left, dataset.bounds.bottom],
                    ]],
                }
            )
            if not projected_geometry.intersects(raster_bounds):
                result = self._terminal_evidence(
                    subject_id,
                    status="outside_raster",
                    geometry_crs=str(source_crs),
                    geometry_digest=geometry_digest,
                    diagnostics=diagnostics + ["geometry_outside_dem_bounds"],
                    cache_key=key,
                )
                self._write_cached(key, result)
                if result.status in {"ready", "no_valid_cells"}:
                    self._geometry_memo[geometry_digest] = result
                return result

            clipped = projected_geometry.intersection(raster_bounds)
            raw_window = from_bounds(*clipped.bounds, transform=dataset.transform)
            window = _integer_window(
                raw_window,
                dataset.width,
                dataset.height,
                self.config.window_padding_pixels,
            )
            cell_count = int(window.width * window.height) if window else 0
            if window is None or cell_count > self.config.max_window_cells:
                status = "window_too_large" if window is not None else "outside_raster"
                result = self._terminal_evidence(
                    subject_id,
                    status=status,
                    geometry_crs=str(source_crs),
                    geometry_digest=geometry_digest,
                    diagnostics=diagnostics + [f"window_cell_count:{cell_count}"],
                    cache_key=key,
                    window=window,
                )
                self._write_cached(key, result)
                return result

            data = dataset.read(
                [self.config.band],
                window=window,
                masked=True,
            )[0].astype(np.float64)
            window_transform = dataset.window_transform(window)
            selected = geometry_mask(
                [mapping(clipped)],
                out_shape=data.shape,
                transform=window_transform,
                all_touched=self.config.all_touched,
                invert=True,
            )
            data_values = np.asarray(data.filled(np.nan), dtype=np.float64)
            data_values *= self.config.elevation_unit_scale_to_m
            valid_elevation = selected & np.isfinite(data_values)
            dx_m, dy_m, scale_method = _horizontal_pixel_metres(
                CRS.from_user_input(dataset.crs),
                dataset.transform,
                window,
            )
            slope_grid = _slope_grid(data_values, dx_m, dy_m)
            valid_slope = selected & np.isfinite(slope_grid)
            selected_count = int(np.count_nonzero(selected))
            elevation = _statistics(
                data_values[valid_elevation],
                unit="m",
                total=selected_count,
            )
            slope = _statistics(
                slope_grid[valid_slope],
                unit="degree",
                total=selected_count,
            )
            status = "ready" if elevation.valid_cell_count else "no_valid_cells"
            if status != "ready":
                diagnostics.append("geometry_has_no_valid_dem_cells")
            relief = (
                elevation.maximum - elevation.minimum
                if elevation.maximum is not None and elevation.minimum is not None
                else None
            )
            provenance = self._provenance(
                geometry_crs=str(source_crs),
                geometry_digest=geometry_digest,
                window=window,
                scale_method=scale_method,
                pixel_metres=(dx_m, dy_m),
                cache_key=key,
            )
            result = TerrainEvidence(
                evidence_id=f"terrain-{key.removeprefix('sha256:')[:24]}",
                subject_id=str(subject_id),
                status=status,
                elevation=elevation,
                slope=slope,
                relief_m=relief,
                diagnostics=tuple(diagnostics),
                provenance=provenance,
            )
            self._write_cached(key, result)
            return result

    def analyze_geometries(
        self,
        subjects: Iterable[tuple[str, Any]],
        *,
        geometry_crs: str,
    ) -> tuple[TerrainEvidence, ...]:
        return tuple(
            self.analyze_geometry(subject_id, geometry, geometry_crs=geometry_crs)
            for subject_id, geometry in subjects
        )

    def sample_points(
        self,
        points: Sequence[tuple[float, float]],
        *,
        coordinate_crs: str,
    ) -> TerrainPointSampleSet:
        """Sample explicit coordinates and estimate slope from a local window."""

        source_crs = CRS.from_user_input(coordinate_crs)
        key = _sha256_payload(
            {
                "schema": "terrain-point-samples-1.0",
                "source": self.metadata.source_sha256,
                "points": [[float(x), float(y)] for x, y in points],
                "coordinate_crs": str(source_crs),
                "config": self.config.model_dump(mode="json"),
            }
        )
        cached = self._read_cached(key, TerrainPointSampleSet)
        if cached is not None:
            return cached
        samples: list[TerrainPointSample] = []
        with rasterio.open(self.source.path) as dataset:
            if not self.metadata.valid:
                raise TerrainSourceError("cannot sample an invalid DEM")
            xs, ys = transform(
                source_crs.to_string(),
                dataset.crs,
                [point[0] for point in points],
                [point[1] for point in points],
            )
            sampled = list(
                dataset.sample(
                    zip(xs, ys),
                    indexes=[self.config.band],
                    masked=True,
                )
            )
            for index, ((input_x, input_y), x, y, value) in enumerate(
                zip(points, xs, ys, sampled, strict=True)
            ):
                inside = (
                    dataset.bounds.left <= x <= dataset.bounds.right
                    and dataset.bounds.bottom <= y <= dataset.bounds.top
                )
                if not inside:
                    samples.append(
                        TerrainPointSample(
                            sample_id=f"sample-{index}",
                            input_coordinate=(float(input_x), float(input_y)),
                            raster_coordinate=(float(x), float(y)),
                            status="outside_raster",
                        )
                    )
                    continue
                row, column = dataset.index(x, y)
                elevation_value = np.ma.asarray(value).reshape(-1)[0]
                masked = bool(np.ma.getmaskarray(value).reshape(-1)[0])
                elevation_m = (
                    None
                    if masked
                    else float(elevation_value) * self.config.elevation_unit_scale_to_m
                )
                local_window = _integer_window(
                    Window(column, row, 1, 1),
                    dataset.width,
                    dataset.height,
                    1,
                )
                slope_value = None
                if local_window is not None:
                    local = dataset.read(
                        [self.config.band],
                        window=local_window,
                        masked=True,
                    )[0].astype(np.float64)
                    local_values = (
                        np.asarray(local.filled(np.nan))
                        * self.config.elevation_unit_scale_to_m
                    )
                    dx_m, dy_m, _ = _horizontal_pixel_metres(
                        CRS.from_user_input(dataset.crs),
                        dataset.transform,
                        local_window,
                    )
                    local_slope = _slope_grid(local_values, dx_m, dy_m)
                    local_row = row - int(local_window.row_off)
                    local_column = column - int(local_window.col_off)
                    candidate = float(local_slope[local_row, local_column])
                    if math.isfinite(candidate):
                        slope_value = candidate
                samples.append(
                    TerrainPointSample(
                        sample_id=f"sample-{index}",
                        input_coordinate=(float(input_x), float(input_y)),
                        raster_coordinate=(float(x), float(y)),
                        row=int(row),
                        column=int(column),
                        elevation_m=elevation_m,
                        slope_degrees=slope_value,
                        status="ready" if elevation_m is not None else "nodata",
                    )
                )
        result = TerrainPointSampleSet(
            sample_set_id=f"terrain-samples-{key.removeprefix('sha256:')[:24]}",
            coordinate_crs=str(source_crs),
            samples=tuple(samples),
            source_sha256=self.metadata.source_sha256,
            cache_key=key,
        )
        self._write_cached(key, result)
        return result

    def _provenance(
        self,
        *,
        geometry_crs: str,
        geometry_digest: str,
        window: Window | None,
        scale_method: str,
        pixel_metres: tuple[float, float],
        cache_key: str,
    ) -> TerrainEvidenceProvenance:
        return TerrainEvidenceProvenance(
            source_path=self.metadata.source_path,
            source_origin=self.metadata.source_origin,
            source_sha256=self.metadata.source_sha256,
            raster_crs=self.metadata.crs,
            geometry_crs=geometry_crs,
            geometry_sha256=geometry_digest,
            raster_transform=self.metadata.transform,
            raster_nodata=self.metadata.nodata,
            raster_band=self.config.band,
            window=_window_tuple(window),
            horizontal_scale_method=scale_method,
            horizontal_pixel_size_m=pixel_metres,
            cache_key=cache_key,
        )

    def _terminal_evidence(
        self,
        subject_id: str,
        *,
        status: str,
        geometry_crs: str,
        geometry_digest: str,
        diagnostics: Sequence[str],
        cache_key: str | None = None,
        window: Window | None = None,
    ) -> TerrainEvidence:
        key = cache_key or _sha256_payload(
            {
                "schema": "terrain-evidence-terminal-1.0",
                "source": self.metadata.source_sha256,
                "subject_id": str(subject_id),
                "geometry": geometry_digest,
                "status": status,
                "config": self.config.model_dump(mode="json"),
            }
        )
        provenance = self._provenance(
            geometry_crs=geometry_crs,
            geometry_digest=geometry_digest,
            window=window,
            scale_method=(
                "geodesic_cell_vectors"
                if self.metadata.is_geographic
                else "projected_axis_units"
            ),
            pixel_metres=(0.0, 0.0),
            cache_key=key,
        )
        return TerrainEvidence(
            evidence_id=f"terrain-{key.removeprefix('sha256:')[:24]}",
            subject_id=str(subject_id),
            status=status,
            elevation=_empty_stats("m"),
            slope=_empty_stats("degree"),
            diagnostics=tuple(diagnostics),
            provenance=provenance,
        )


__all__ = ["TerrainEvidenceService", "TerrainSourceError", "resolve_dem_source"]
