"""Prepare an auditable Stage-4 terrain/friction grid from real GIS inputs."""

from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import reproject
from shapely import make_valid
from shapely.geometry import box, mapping
from shapely.ops import unary_union

from app.contracts.execute.road_planning import RoadArtifactEvidence

from .road_land_cost import ROAD_LAND_WEIGHT_RULE_VERSION, road_land_weight


class TerrainGridPreparationError(ValueError):
    """Raised when real source evidence cannot produce a safe routing grid."""


@dataclass(frozen=True)
class TerrainGridPreparationResult:
    grid_path: Path
    report_path: Path
    checksum: str
    evidence: RoadArtifactEvidence
    report: dict[str, Any]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _cache_key(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_geometry(value: Any) -> Any:
    if value is None or value.is_empty:
        return None
    return make_valid(value) if not value.is_valid else value


def _slope_grid(elevation: np.ndarray, cell_size_m: float) -> np.ndarray:
    finite = np.isfinite(elevation)
    if elevation.shape[0] < 3 or elevation.shape[1] < 3 or not finite.any():
        return np.full(elevation.shape, np.nan, dtype=np.float32)
    filled = np.where(finite, elevation, 0.0)
    rise_y, rise_x = np.gradient(filled, cell_size_m, cell_size_m)
    slope = np.degrees(np.arctan(np.hypot(rise_x, rise_y)))
    neighbourhood = finite.copy()
    neighbourhood[0, :] = False
    neighbourhood[-1, :] = False
    neighbourhood[:, 0] = False
    neighbourhood[:, -1] = False
    neighbourhood[1:, :] &= finite[:-1, :]
    neighbourhood[:-1, :] &= finite[1:, :]
    neighbourhood[:, 1:] &= finite[:, :-1]
    neighbourhood[:, :-1] &= finite[:, 1:]
    slope[~neighbourhood] = np.nan
    return slope.astype(np.float32)


def _write_deterministic_npz(path: Path, arrays: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name in sorted(arrays):
            stream = io.BytesIO()
            np.lib.format.write_array(
                stream,
                np.asanyarray(arrays[name]),
                allow_pickle=False,
            )
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, stream.getvalue(), compress_type=zipfile.ZIP_DEFLATED)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _land_shapes(
    landuse: gpd.GeoDataFrame,
) -> tuple[list[tuple[dict[str, Any], float]], dict[str, int]]:
    code_field = "DLBM" if "DLBM" in landuse.columns else (
        "SDDLBM" if "SDDLBM" in landuse.columns else None
    )
    name_field = "DLMC" if "DLMC" in landuse.columns else (
        "SDDLMC" if "SDDLMC" in landuse.columns else None
    )
    shapes: list[tuple[dict[str, Any], float]] = []
    counts: dict[str, int] = {}
    for _, row in landuse.iterrows():
        geometry = _valid_geometry(row.geometry)
        if geometry is None:
            continue
        weight = float(
            road_land_weight(
                row.get(name_field) if name_field else None,
                row.get(code_field) if code_field else None,
            )
        )
        shapes.append((mapping(geometry), weight))
        key = f"{weight:g}"
        counts[key] = counts.get(key, 0) + 1
    return shapes, dict(sorted(counts.items()))


def prepare_terrain_friction_grid(
    *,
    dem_path: str | Path,
    boundary_path: str | Path,
    landuse_path: str | Path,
    output_dir: str | Path,
    metric_crs: str = "EPSG:4527",
    cell_size_m: float = 30.0,
    minimum_valid_fraction: float = 0.80,
    maximum_cell_count: int = 4_000_000,
) -> TerrainGridPreparationResult:
    """Build the combined grid expected by ``terrain_router.load_terrain_context``.

    Every output value is derived from the supplied DEM, village boundary, and
    current land-use artifact. Existing vector and raster candidate scoring use
    the same versioned land-weight function.
    """

    if cell_size_m <= 0:
        raise ValueError("cell_size_m must be positive")
    if not 0 < minimum_valid_fraction <= 1:
        raise ValueError("minimum_valid_fraction must be in (0, 1]")
    dem = Path(dem_path).expanduser().resolve()
    boundary_file = Path(boundary_path).expanduser().resolve()
    landuse_file = Path(landuse_path).expanduser().resolve()
    for path in (dem, boundary_file, landuse_file):
        if not path.is_file():
            raise FileNotFoundError(path)

    checksums = {
        "dem": _sha256_file(dem),
        "boundary": _sha256_file(boundary_file),
        "landuse": _sha256_file(landuse_file),
    }
    parameters = {
        "metric_crs": metric_crs,
        "cell_size_m": float(cell_size_m),
        "minimum_valid_fraction": float(minimum_valid_fraction),
        "maximum_cell_count": int(maximum_cell_count),
        "land_cost_rule": ROAD_LAND_WEIGHT_RULE_VERSION,
    }
    key = _cache_key({"inputs": checksums, "parameters": parameters})
    root = Path(output_dir).expanduser().resolve()
    grid_path = root / f"terrain_friction_{key[:20]}.npz"
    report_path = root / f"terrain_friction_{key[:20]}.report.json"
    if grid_path.is_file() and report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        checksum = _sha256_file(grid_path)
        if checksum == report.get("grid_checksum"):
            return TerrainGridPreparationResult(
                grid_path=grid_path,
                report_path=report_path,
                checksum=checksum,
                evidence=RoadArtifactEvidence(
                    role="land_friction",
                    artifact_ref=grid_path.as_uri(),
                    checksum=checksum,
                ),
                report=report,
            )

    boundary = gpd.read_file(boundary_file)
    landuse = gpd.read_file(landuse_file)
    if boundary.crs is None or landuse.crs is None:
        raise TerrainGridPreparationError("boundary and landuse require declared CRS")
    boundary = boundary[boundary.geometry.notna() & ~boundary.geometry.is_empty].copy()
    landuse = landuse[landuse.geometry.notna() & ~landuse.geometry.is_empty].copy()
    if boundary.empty:
        raise TerrainGridPreparationError("boundary contains no usable geometry")
    if landuse.empty:
        raise TerrainGridPreparationError("landuse contains no usable geometry")

    with rasterio.open(dem) as source:
        if source.crs is None or source.count < 1:
            raise TerrainGridPreparationError("DEM requires a CRS and at least one band")
        source_boundary = boundary.to_crs(source.crs)
        source_union = unary_union(
            [geometry for geometry in source_boundary.geometry.map(_valid_geometry) if geometry is not None]
        )
        if source_union.is_empty or not source_union.intersects(box(*source.bounds)):
            raise TerrainGridPreparationError("DEM does not overlap the planning boundary")

        metric_boundary = boundary.to_crs(metric_crs)
        boundary_union = unary_union(
            [geometry for geometry in metric_boundary.geometry.map(_valid_geometry) if geometry is not None]
        )
        if boundary_union.is_empty:
            raise TerrainGridPreparationError("planning boundary is empty after reprojection")
        min_x, min_y, max_x, max_y = boundary_union.bounds
        width = max(1, int(math.ceil((max_x - min_x) / cell_size_m)))
        height = max(1, int(math.ceil((max_y - min_y) / cell_size_m)))
        cell_count = width * height
        if cell_count > maximum_cell_count:
            raise TerrainGridPreparationError(
                f"terrain grid would contain {cell_count} cells, above {maximum_cell_count}"
            )
        transform = from_origin(min_x, max_y, cell_size_m, cell_size_m)
        elevation = np.full((height, width), np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(source, 1),
            destination=elevation,
            src_transform=source.transform,
            src_crs=source.crs,
            src_nodata=source.nodata,
            dst_transform=transform,
            dst_crs=metric_crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )

    inside = rasterize(
        [(mapping(boundary_union), 1)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype="uint8",
    ).astype(bool)
    valid_inside = inside & np.isfinite(elevation)
    inside_count = int(inside.sum())
    valid_fraction = float(valid_inside.sum() / inside_count) if inside_count else 0.0
    if inside_count == 0 or valid_fraction < minimum_valid_fraction:
        raise TerrainGridPreparationError(
            "DEM valid coverage inside planning boundary is "
            f"{valid_fraction:.3f}, below {minimum_valid_fraction:.3f}"
        )

    slope = _slope_grid(elevation, cell_size_m)
    metric_landuse = landuse.to_crs(metric_crs)
    shapes, source_weight_counts = _land_shapes(metric_landuse)
    if not shapes:
        raise TerrainGridPreparationError("landuse produced no rasterizable geometry")
    default_weight = float(road_land_weight(None, None))
    land_cost = rasterize(
        shapes,
        out_shape=(height, width),
        transform=transform,
        fill=default_weight,
        dtype="float32",
    ).astype(np.float32)

    arrays = {
        "cell_size_m": np.asarray(cell_size_m, dtype=np.float64),
        "elevation_m": elevation.astype(np.float32),
        "inside_boundary": inside.astype(bool),
        "land_cost": land_cost,
        "metric_crs": np.asarray(metric_crs),
        "slope_deg": slope,
        "x_min": np.asarray(min_x, dtype=np.float64),
        "y_max": np.asarray(max_y, dtype=np.float64),
    }
    _write_deterministic_npz(grid_path, arrays)
    checksum = _sha256_file(grid_path)
    inside_cost = land_cost[inside]
    unique_costs, cost_counts = np.unique(inside_cost, return_counts=True)
    report = {
        "schema_version": "road-terrain-friction-grid-v1",
        "status": "ready",
        "cache_key": key,
        "grid_path": str(grid_path),
        "grid_checksum": checksum,
        "input_checksums": checksums,
        "metric_crs": metric_crs,
        "cell_size_m": float(cell_size_m),
        "shape": [height, width],
        "cell_count": cell_count,
        "inside_cell_count": inside_count,
        "valid_elevation_fraction_inside": valid_fraction,
        "finite_slope_fraction_inside": float(np.isfinite(slope[inside]).mean()),
        "land_cost_rule": ROAD_LAND_WEIGHT_RULE_VERSION,
        "land_cost_source_feature_counts": source_weight_counts,
        "land_cost_cell_counts": {
            f"{float(value):g}": int(count)
            for value, count in zip(unique_costs, cost_counts, strict=True)
        },
        "parameters": parameters,
        "limitations": [
            "The grid is a planning-level terrain/friction surface, not an engineering survey.",
            "Hard spatial constraints remain independently applied by Stage 4.",
        ],
    }
    _write_json(report_path, report)
    return TerrainGridPreparationResult(
        grid_path=grid_path,
        report_path=report_path,
        checksum=checksum,
        evidence=RoadArtifactEvidence(
            role="land_friction",
            artifact_ref=grid_path.as_uri(),
            checksum=checksum,
        ),
        report=report,
    )


__all__ = [
    "TerrainGridPreparationError",
    "TerrainGridPreparationResult",
    "prepare_terrain_friction_grid",
]
