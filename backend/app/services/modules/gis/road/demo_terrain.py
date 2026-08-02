"""Build a reproducible terrain grid for the isolated road-planning demo.

The elevation source is a public 1-arc-second SRTM HGT tile.  The generated
grid is cropped and resampled in the project's metric CRS without rasterio so
the demo remains lightweight and deterministic.
"""

from __future__ import annotations

import gzip
import json
import math
from pathlib import Path
from typing import Any, Dict, Tuple

import geopandas as gpd
import numpy as np
from PIL import Image, TiffImagePlugin
from pyproj import Transformer
from shapely import contains_xy
from shapely.geometry import box, mapping
from shapely.ops import unary_union


SRTM_SIZE = 3601
SRTM_TILE_WEST = 116.0
SRTM_TILE_NORTH = 25.0
SOURCE_URL = "https://elevation-tiles-prod.s3.amazonaws.com/skadi/N24/N24E116.hgt.gz"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_hgt(path: Path) -> np.ndarray:
    with gzip.open(path, "rb") as handle:
        data = np.frombuffer(handle.read(), dtype=">i2")
    if data.size != SRTM_SIZE * SRTM_SIZE:
        raise ValueError(f"unexpected SRTM tile size: {data.size}")
    return data.reshape((SRTM_SIZE, SRTM_SIZE)).astype(np.float32)


def _bilinear_srtm(elevation: np.ndarray, longitude: np.ndarray, latitude: np.ndarray) -> np.ndarray:
    column = np.clip((longitude - SRTM_TILE_WEST) * 3600.0, 0.0, 3600.0)
    row = np.clip((SRTM_TILE_NORTH - latitude) * 3600.0, 0.0, 3600.0)
    c0 = np.floor(column).astype(np.int32)
    r0 = np.floor(row).astype(np.int32)
    c1 = np.minimum(c0 + 1, 3600)
    r1 = np.minimum(r0 + 1, 3600)
    dc, dr = column - c0, row - r0
    values = (
        elevation[r0, c0] * (1.0 - dc) * (1.0 - dr)
        + elevation[r0, c1] * dc * (1.0 - dr)
        + elevation[r1, c0] * (1.0 - dc) * dr
        + elevation[r1, c1] * dc * dr
    )
    values[values <= -32000] = np.nan
    if np.isnan(values).any():
        fallback = float(np.nanmedian(values))
        values = np.nan_to_num(values, nan=fallback)
    return values.astype(np.float32)


def _land_cost(code: str) -> float:
    code = str(code or "")
    if code in {"2126", "2200"}:  # village/regional transport land
        return 0.8
    if code.startswith("31"):  # water
        return 80.0
    if code in {"2121", "2122", "2124", "2125"}:  # built land
        return 25.0
    if code.startswith("11"):  # cultivated land
        return 8.0
    if code.startswith("12"):  # garden land
        return 6.0
    if code.startswith("13"):  # forest land
        return 3.0
    if code.startswith("14"):
        return 2.5
    return 2.0


def _rasterize_land_cost(
    landuse: gpd.GeoDataFrame, x_values: np.ndarray, y_values: np.ndarray
) -> np.ndarray:
    result = np.full((len(y_values), len(x_values)), 2.0, dtype=np.float32)
    for _, row in landuse.sort_values("DLBM", kind="stable").iterrows():
        geometry = row.geometry
        if geometry is None or geometry.is_empty:
            continue
        minx, miny, maxx, maxy = geometry.bounds
        columns = np.flatnonzero((x_values >= minx) & (x_values <= maxx))
        rows = np.flatnonzero((y_values >= miny) & (y_values <= maxy))
        if not len(columns) or not len(rows):
            continue
        xx, yy = np.meshgrid(x_values[columns], y_values[rows])
        mask = contains_xy(geometry, xx, yy)
        window = result[np.ix_(rows, columns)]
        window[mask] = np.maximum(window[mask], _land_cost(row.get("DLBM")))
        result[np.ix_(rows, columns)] = window
    return result


def _write_geotiff(
    path: Path,
    values: np.ndarray,
    x_min: float,
    y_max: float,
    pixel_width: float,
    pixel_height: float,
    *,
    epsg: int,
    nodata: float = -9999.0,
) -> None:
    """Write a small float GeoTIFF with the minimum GeoTIFF tags QGIS needs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(values.astype(np.float32), mode="F")
    tags = TiffImagePlugin.ImageFileDirectory_v2()
    tags[33550] = (float(pixel_width), float(pixel_height), 0.0)  # ModelPixelScaleTag
    tags[33922] = (0.0, 0.0, 0.0, float(x_min), float(y_max), 0.0)  # ModelTiepointTag
    if epsg == 4326:
        tags[34735] = (
            1, 1, 0, 3,
            1024, 0, 1, 2,       # geographic model
            1025, 0, 1, 1,       # pixel is area
            2048, 0, 1, 4326,    # EPSG:4326
        )
    else:
        tags[34735] = (
            1, 1, 0, 3,
            1024, 0, 1, 1,       # projected model
            1025, 0, 1, 1,       # pixel is area
            3072, 0, 1, int(epsg),
        )
    tags[42113] = str(nodata)  # GDAL_NODATA: exclude outside-village cells in QGIS
    image.save(path, format="TIFF", compression="tiff_lzw", tiffinfo=tags)


def _build_wgs84_display_rasters(
    source: np.ndarray,
    village_wgs84: Any,
    *,
    margin_m: float,
    pixel_size_degree: float = 1.0 / 3600.0,
) -> Tuple[np.ndarray, np.ndarray, float, float, float]:
    """Build north-up WGS84 rasters that overlay XYZ satellite tiles directly."""
    minx, miny, maxx, maxy = village_wgs84.bounds
    centre_latitude = (miny + maxy) / 2.0
    latitude_margin = margin_m / 111_320.0
    longitude_margin = margin_m / (111_320.0 * max(0.1, math.cos(math.radians(centre_latitude))))
    x_min = math.floor((minx - longitude_margin) / pixel_size_degree) * pixel_size_degree
    y_max = math.ceil((maxy + latitude_margin) / pixel_size_degree) * pixel_size_degree
    width = int(math.ceil((maxx + longitude_margin - x_min) / pixel_size_degree))
    height = int(math.ceil((y_max - (miny - latitude_margin)) / pixel_size_degree))
    longitude = x_min + (np.arange(width, dtype=np.float64) + 0.5) * pixel_size_degree
    latitude = y_max - (np.arange(height, dtype=np.float64) + 0.5) * pixel_size_degree
    xx, yy = np.meshgrid(longitude, latitude)
    elevation = _bilinear_srtm(source, xx, yy)
    north_south_metres = pixel_size_degree * 111_320.0
    east_west_metres = north_south_metres * math.cos(math.radians(centre_latitude))
    gradient_y, gradient_x = np.gradient(
        elevation,
        north_south_metres,
        east_west_metres,
    )
    slope = np.degrees(np.arctan(np.hypot(gradient_x, gradient_y))).astype(np.float32)
    inside = contains_xy(village_wgs84, xx, yy)
    elevation[~inside] = np.nan
    slope[~inside] = np.nan
    return elevation, slope, x_min, y_max, pixel_size_degree


def _write_demo_building_footprints(
    landuse: gpd.GeoDataFrame, output_path: Path, metric_crs: str
) -> int:
    code_field = "DLBM" if "DLBM" in landuse.columns else "SDDLBM"
    codes = landuse[code_field].fillna("").astype(str)
    parcels = landuse.loc[codes.isin({"2121", "2122", "2124", "2125"})].copy()
    sort_field = "BSM" if "BSM" in parcels.columns else code_field
    features = []
    for index, (_, row) in enumerate(parcels.sort_values(sort_field, kind="stable").iterrows(), 1):
        parcel = row.geometry
        if parcel is None or parcel.is_empty or parcel.area < 40.0:
            continue
        centre = parcel.representative_point()
        width = 10.0 + float(index % 4) * 2.0
        depth = 8.0 + float(index % 3) * 2.0
        footprint = box(
            centre.x - width / 2.0,
            centre.y - depth / 2.0,
            centre.x + width / 2.0,
            centre.y + depth / 2.0,
        ).intersection(parcel)
        if footprint.is_empty or footprint.area < 20.0:
            continue
        features.append(
            {
                "type": "Feature",
                "id": f"DB{len(features) + 1:04d}",
                "geometry": mapping(footprint),
                "properties": {
                    "building_id": f"DB{len(features) + 1:04d}",
                    "data_mode": "demo_proxy",
                    "geometry_role": "synthetic_building_footprint_for_obstacle_testing",
                    "source_parcel_code": str(row.get(code_field) or ""),
                    "is_real_building": False,
                },
            }
        )
    _write_json(
        output_path,
        {
            "type": "FeatureCollection",
            "name": "demo_building_footprints",
            "data_mode": "demo_proxy",
            "crs": {"type": "name", "properties": {"name": metric_crs}},
            "features": features,
        },
    )
    return len(features)


def build_demo_terrain_grid(
    *,
    srtm_hgt_gz_path: Path,
    boundary_path: Path,
    landuse_path: Path,
    output_dir: Path,
    metric_crs: str = "EPSG:4527",
    cell_size_m: float = 30.0,
    margin_m: float = 150.0,
) -> Dict[str, Any]:
    """Create DEM, slope, land-cost, boundary mask, and QGIS rasters."""
    if not srtm_hgt_gz_path.exists():
        raise FileNotFoundError(srtm_hgt_gz_path)
    if cell_size_m <= 0 or margin_m < 0:
        raise ValueError("cell_size_m must be > 0 and margin_m must be >= 0")
    boundary = gpd.read_file(boundary_path).to_crs(metric_crs)
    landuse = gpd.read_file(landuse_path).to_crs(metric_crs)
    village = unary_union([geometry for geometry in boundary.geometry if geometry is not None and not geometry.is_empty])
    minx, miny, maxx, maxy = village.bounds
    x_min = math.floor((minx - margin_m) / cell_size_m) * cell_size_m
    y_max = math.ceil((maxy + margin_m) / cell_size_m) * cell_size_m
    width = int(math.ceil((maxx + margin_m - x_min) / cell_size_m))
    height = int(math.ceil((y_max - (miny - margin_m)) / cell_size_m))
    x_values = x_min + (np.arange(width, dtype=np.float64) + 0.5) * cell_size_m
    y_values = y_max - (np.arange(height, dtype=np.float64) + 0.5) * cell_size_m
    xx, yy = np.meshgrid(x_values, y_values)
    to_wgs84 = Transformer.from_crs(metric_crs, "EPSG:4326", always_xy=True)
    longitude, latitude = to_wgs84.transform(xx, yy)
    source = _read_hgt(srtm_hgt_gz_path)
    elevation = _bilinear_srtm(source, np.asarray(longitude), np.asarray(latitude))
    gradient_y, gradient_x = np.gradient(elevation, cell_size_m, cell_size_m)
    slope = np.degrees(np.arctan(np.hypot(gradient_x, gradient_y))).astype(np.float32)
    inside = contains_xy(village, xx, yy).astype(np.uint8)
    land_cost = _rasterize_land_cost(landuse, x_values, y_values)
    elevation[inside == 0] = np.nan
    slope[inside == 0] = np.nan

    output_dir.mkdir(parents=True, exist_ok=True)
    grid_path = output_dir / "demo_terrain_grid.npz"
    np.savez_compressed(
        grid_path,
        elevation_m=elevation,
        slope_deg=slope,
        land_cost=land_cost,
        inside_boundary=inside,
        x_min=np.array(x_min),
        y_max=np.array(y_max),
        cell_size_m=np.array(cell_size_m),
        metric_crs=np.array(metric_crs),
    )
    dem_path = output_dir / "demo_dem_epsg4527.tif"
    slope_path = output_dir / "demo_slope_deg_epsg4527.tif"
    qgis_dem_path = output_dir / "demo_dem_wgs84.tif"
    qgis_slope_path = output_dir / "demo_slope_deg_wgs84.tif"
    building_path = output_dir / "demo_building_footprints.geojson"
    building_count = _write_demo_building_footprints(landuse, building_path, metric_crs)
    display_dem = np.nan_to_num(elevation, nan=-9999.0)
    display_slope = np.nan_to_num(slope, nan=-9999.0)
    _write_geotiff(
        dem_path,
        display_dem,
        x_min,
        y_max,
        cell_size_m,
        cell_size_m,
        epsg=4527,
    )
    _write_geotiff(
        slope_path,
        display_slope,
        x_min,
        y_max,
        cell_size_m,
        cell_size_m,
        epsg=4527,
    )
    village_wgs84 = unary_union(
        [
            geometry
            for geometry in boundary.to_crs("EPSG:4326").geometry
            if geometry is not None and not geometry.is_empty
        ]
    )
    qgis_elevation, qgis_slope, qgis_x_min, qgis_y_max, qgis_pixel_size = (
        _build_wgs84_display_rasters(
            source,
            village_wgs84,
            margin_m=margin_m,
        )
    )
    _write_geotiff(
        qgis_dem_path,
        np.nan_to_num(qgis_elevation, nan=-9999.0),
        qgis_x_min,
        qgis_y_max,
        qgis_pixel_size,
        qgis_pixel_size,
        epsg=4326,
    )
    _write_geotiff(
        qgis_slope_path,
        np.nan_to_num(qgis_slope, nan=-9999.0),
        qgis_x_min,
        qgis_y_max,
        qgis_pixel_size,
        qgis_pixel_size,
        epsg=4326,
    )
    valid_elevation = elevation[np.isfinite(elevation)]
    valid_slope = slope[np.isfinite(slope)]
    report = {
        "data_mode": "demo_proxy",
        "dem_role": "real_public_terrain_for_software_demo",
        "location_role": "proxy_locations_not_verified_place_coordinates",
        "source_dataset": "SRTM 1 arc-second HGT tile N24E116",
        "source_url": SOURCE_URL,
        "source_file": str(srtm_hgt_gz_path),
        "metric_crs": metric_crs,
        "cell_size_m": cell_size_m,
        "width": width,
        "height": height,
        "elevation_min_m": round(float(valid_elevation.min()), 3),
        "elevation_max_m": round(float(valid_elevation.max()), 3),
        "elevation_mean_m": round(float(valid_elevation.mean()), 3),
        "slope_mean_deg": round(float(valid_slope.mean()), 3),
        "slope_p95_deg": round(float(np.percentile(valid_slope, 95)), 3),
        "synthetic_building_footprint_count": building_count,
        "outputs": {
            "routing_grid": str(grid_path),
            "metric_dem": str(dem_path),
            "metric_slope": str(slope_path),
            "qgis_dem": str(qgis_dem_path),
            "qgis_slope": str(qgis_slope_path),
            "demo_building_footprints": str(building_path),
        },
        "warning": "Terrain is public SRTM data, but demand/facility coordinates remain demo proxies. Not for construction or approval.",
    }
    _write_json(output_dir / "demo_terrain_report.json", report)
    return report


__all__ = ["build_demo_terrain_grid"]
