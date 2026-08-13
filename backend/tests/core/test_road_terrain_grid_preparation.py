from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from app.spatial.network.terrain_grid_preparation import (
    TerrainGridPreparationError,
    prepare_terrain_friction_grid,
)
from app.spatial.network.terrain_router import _chaikin, _minimum_curve_radius


def _write_fc(path: Path, features: list[dict]) -> Path:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
                "features": features,
            }
        ),
        encoding="utf-8",
    )
    return path


def _polygon(x0: float, y0: float, x1: float, y1: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
        ],
    }


def _feature(geometry: dict, **properties: object) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _write_dem(path: Path) -> Path:
    rows = np.arange(80, dtype="float32")[:, None]
    cols = np.arange(80, dtype="float32")[None, :]
    elevation = 100.0 + rows * 0.2 + cols * 0.1
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=80,
        height=80,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(0.0, 0.02, 0.00025, 0.00025),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(elevation, 1)
    return path


def test_prepare_grid_uses_real_dem_boundary_and_existing_land_weight_rules(
    tmp_path: Path,
) -> None:
    dem = _write_dem(tmp_path / "dem.tif")
    boundary = _write_fc(
        tmp_path / "boundary.geojson",
        [_feature(_polygon(0.002, 0.002, 0.018, 0.018), bsm="boundary")],
    )
    landuse = _write_fc(
        tmp_path / "landuse.geojson",
        [
            _feature(_polygon(0.002, 0.002, 0.010, 0.018), DLBM="2126"),
            _feature(_polygon(0.010, 0.002, 0.018, 0.018), DLBM="3101"),
        ],
    )

    first = prepare_terrain_friction_grid(
        dem_path=dem,
        boundary_path=boundary,
        landuse_path=landuse,
        output_dir=tmp_path / "terrain-grid",
        metric_crs="EPSG:3857",
        cell_size_m=50.0,
    )
    second = prepare_terrain_friction_grid(
        dem_path=dem,
        boundary_path=boundary,
        landuse_path=landuse,
        output_dir=tmp_path / "terrain-grid",
        metric_crs="EPSG:3857",
        cell_size_m=50.0,
    )

    assert first.grid_path == second.grid_path
    assert first.checksum == second.checksum
    assert first.evidence.role == "land_friction"
    assert first.evidence.checksum == first.checksum
    with np.load(first.grid_path, allow_pickle=False) as payload:
        assert {
            "elevation_m",
            "slope_deg",
            "land_cost",
            "inside_boundary",
            "x_min",
            "y_max",
            "cell_size_m",
            "metric_crs",
        }.issubset(payload.files)
        inside = payload["inside_boundary"].astype(bool)
        elevation = payload["elevation_m"]
        slope = payload["slope_deg"]
        cost = payload["land_cost"]
        assert inside.any()
        assert np.isfinite(elevation[inside]).mean() > 0.95
        assert np.isfinite(slope[inside]).mean() > 0.80
        assert np.any(np.isclose(cost[inside], 0.5))
        assert np.any(np.isclose(cost[inside], 50.0))
        assert str(payload["metric_crs"]) == "EPSG:3857"
    report = json.loads(first.report_path.read_text(encoding="utf-8"))
    assert report["status"] == "ready"
    assert report["land_cost_rule"] == "road_land_weight_v1"
    assert report["input_checksums"]["dem"].startswith("sha256:")
    assert report["grid_checksum"] == first.checksum


def test_prepare_grid_fails_closed_when_dem_does_not_cover_boundary(
    tmp_path: Path,
) -> None:
    dem = _write_dem(tmp_path / "dem.tif")
    boundary = _write_fc(
        tmp_path / "boundary.geojson",
        [_feature(_polygon(10.0, 10.0, 10.01, 10.01))],
    )
    landuse = _write_fc(
        tmp_path / "landuse.geojson",
        [_feature(_polygon(10.0, 10.0, 10.01, 10.01), DLBM="2126")],
    )

    with pytest.raises(TerrainGridPreparationError, match="does not overlap"):
        prepare_terrain_friction_grid(
            dem_path=dem,
            boundary_path=boundary,
            landuse_path=landuse,
            output_dir=tmp_path / "terrain-grid",
            metric_crs="EPSG:3857",
            cell_size_m=50.0,
        )


def test_curve_radius_ignores_subcell_smoothing_vertices() -> None:
    grid_path = [
        (0.0, 0.0),
        (10.0, 0.0),
        (20.0, 10.0),
        (30.0, 10.0),
        (40.0, 20.0),
        (50.0, 20.0),
    ]
    smoothed = LineString(_chaikin(grid_path, 2))

    vertex_radius = _minimum_curve_radius(smoothed)
    planning_radius = _minimum_curve_radius(smoothed, resolution_m=10.0)

    assert vertex_radius is not None and vertex_radius < 15.0
    assert planning_radius is not None and planning_radius > 15.0
