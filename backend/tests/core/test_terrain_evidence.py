from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from app.contracts.spatial.terrain_evidence import (
    TerrainEvidenceConfig,
    TerrainSuitabilityPolicy,
)
from app.domain.suitability import assess_terrain_suitability
from app.spatial.terrain import TerrainEvidenceService, TerrainSourceError


def _write_dem(
    path,
    values: np.ndarray,
    *,
    crs: str | None = "EPSG:3857",
    nodata: float | None = None,
    transform=None,
):
    affine = transform or from_origin(0.0, float(values.shape[0] * 10), 10.0, 10.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype=values.dtype,
        crs=crs,
        transform=affine,
        nodata=nodata,
    ) as dataset:
        dataset.write(values, 1)
    return path


def _projected_plane(tmp_path, *, cache=True):
    # Ten metres of rise per ten metres of run: interior slope is 45 degrees.
    values = np.tile(np.arange(5, dtype=np.float32) * 10.0, (5, 1))
    path = _write_dem(tmp_path / "plane.tif", values)
    return TerrainEvidenceService.open(
        explicit_path=path,
        allowed_roots=[tmp_path],
        cache_dir=tmp_path / "cache" if cache else None,
    )


def test_windowed_geometry_statistics_and_projected_slope(tmp_path):
    service = _projected_plane(tmp_path)

    evidence = service.analyze_geometry(
        "parcel-1",
        box(0.0, 0.0, 50.0, 50.0),
        geometry_crs="EPSG:3857",
    )

    assert evidence.status == "ready"
    assert evidence.elevation.valid_cell_count == 25
    assert evidence.elevation.minimum == pytest.approx(0.0)
    assert evidence.elevation.maximum == pytest.approx(40.0)
    assert evidence.slope.valid_cell_count == 9
    assert evidence.slope.mean == pytest.approx(45.0)
    assert evidence.relief_m == pytest.approx(40.0)
    assert evidence.provenance.horizontal_scale_method == "projected_axis_units"
    assert evidence.provenance.horizontal_pixel_size_m == pytest.approx((10.0, 10.0))
    assert evidence.provenance.window == (0, 0, 5, 5)


def test_cache_is_content_addressed_and_preserves_subject_lineage(tmp_path):
    service = _projected_plane(tmp_path)
    geometry = box(0.0, 0.0, 50.0, 50.0)

    first = service.analyze_geometry("parcel-1", geometry, geometry_crs="EPSG:3857")
    second = service.analyze_geometry("parcel-1", geometry, geometry_crs="EPSG:3857")
    other = service.analyze_geometry("parcel-2", geometry, geometry_crs="EPSG:3857")

    assert first.provenance.cache_hit is False
    assert second.provenance.cache_hit is True
    assert second.evidence_id == first.evidence_id
    assert other.subject_id == "parcel-2"
    assert other.evidence_id != first.evidence_id
    assert len(list((tmp_path / "cache").glob("*.json"))) == 2


def test_nodata_is_excluded_and_valid_fraction_remains_auditable(tmp_path):
    values = np.tile(np.arange(5, dtype=np.float32) * 10.0, (5, 1))
    values[2, 2] = -9999.0
    path = _write_dem(tmp_path / "nodata.tif", values, nodata=-9999.0)
    service = TerrainEvidenceService.open(
        explicit_path=path,
        allowed_roots=[tmp_path],
    )

    evidence = service.analyze_geometry(
        "parcel-nodata",
        box(0.0, 0.0, 50.0, 50.0),
        geometry_crs="EPSG:3857",
    )

    assert evidence.status == "ready"
    assert evidence.elevation.valid_cell_count == 24
    assert evidence.elevation.valid_fraction == pytest.approx(24 / 25)
    assert evidence.provenance.raster_nodata == -9999.0
    assert "nodata_not_declared" not in evidence.diagnostics


def test_missing_crs_is_fail_closed_as_typed_invalid_raster(tmp_path):
    path = _write_dem(
        tmp_path / "missing-crs.tif",
        np.ones((5, 5), dtype=np.float32),
        crs=None,
    )
    service = TerrainEvidenceService.open(
        explicit_path=path,
        allowed_roots=[tmp_path],
    )

    evidence = service.analyze_geometry(
        "parcel-invalid-raster",
        box(0.0, 0.0, 50.0, 50.0),
        geometry_crs="EPSG:3857",
    )

    assert service.metadata.valid is False
    assert "missing_crs" in service.metadata.diagnostics
    assert evidence.status == "invalid_raster"
    assert evidence.elevation.valid_cell_count == 0


def test_outside_geometry_and_oversized_window_do_not_read_full_raster(tmp_path):
    service = _projected_plane(tmp_path, cache=False)
    outside = service.analyze_geometry(
        "outside",
        box(100.0, 100.0, 110.0, 110.0),
        geometry_crs="EPSG:3857",
    )
    limited = TerrainEvidenceService.open(
        explicit_path=service.source.path,
        allowed_roots=[tmp_path],
        config=TerrainEvidenceConfig(max_window_cells=9),
    )
    oversized = limited.analyze_geometry(
        "oversized",
        box(0.0, 0.0, 50.0, 50.0),
        geometry_crs="EPSG:3857",
    )

    assert outside.status == "outside_raster"
    assert oversized.status == "window_too_large"
    assert "window_cell_count:25" in oversized.diagnostics


def test_rasterio_point_sampling_returns_elevation_slope_and_cache(tmp_path):
    service = _projected_plane(tmp_path)

    first = service.sample_points([(15.0, 35.0), (100.0, 100.0)], coordinate_crs="EPSG:3857")
    second = service.sample_points([(15.0, 35.0), (100.0, 100.0)], coordinate_crs="EPSG:3857")

    assert first.samples[0].status == "ready"
    assert first.samples[0].elevation_m == pytest.approx(10.0)
    assert first.samples[0].slope_degrees == pytest.approx(45.0)
    assert first.samples[1].status == "outside_raster"
    assert second.cache_hit is True


def test_explicit_path_requires_an_allowed_root(tmp_path):
    path = _write_dem(tmp_path / "safe.tif", np.ones((3, 3), dtype=np.float32))

    with pytest.raises(TerrainSourceError, match="allowed root"):
        TerrainEvidenceService.open(explicit_path=path)
    with pytest.raises(TerrainSourceError, match="outside"):
        TerrainEvidenceService.open(
            explicit_path=path,
            allowed_roots=[tmp_path / "different-root"],
        )


def test_planning_context_raster_has_priority_without_catalog_or_path(tmp_path):
    path = _write_dem(tmp_path / "context.tif", np.ones((3, 3), dtype=np.float32))
    context = SimpleNamespace(
        workspace=SimpleNamespace(
            rasters=SimpleNamespace(dem=SimpleNamespace(path=str(path)))
        )
    )

    service = TerrainEvidenceService.open(planning_context=context)

    assert service.metadata.source_origin == "planning_context"
    assert service.metadata.source_path == str(path.resolve())


def test_suitability_uses_explicit_policy_not_raster_engine_thresholds(tmp_path):
    evidence = _projected_plane(tmp_path).analyze_geometry(
        "parcel-policy",
        box(0.0, 0.0, 50.0, 50.0),
        geometry_crs="EPSG:3857",
    )
    conditional_policy = TerrainSuitabilityPolicy(
        preferred_max_slope_degrees=10.0,
        hard_max_slope_degrees=50.0,
        minimum_valid_fraction=0.5,
        slope_statistic="p90",
    )
    hard_policy = conditional_policy.model_copy(
        update={"hard_max_slope_degrees": 40.0}
    )

    conditional = assess_terrain_suitability(evidence, conditional_policy)
    unsuitable = assess_terrain_suitability(evidence, hard_policy)

    assert conditional.classification == "conditional"
    assert conditional.hard_feasible is True
    assert conditional.score == pytest.approx(0.125)
    assert unsuitable.classification == "unsuitable"
    assert unsuitable.hard_feasible is False
    assert "terrain_slope_exceeds_hard_maximum" in unsuitable.reasons


@pytest.mark.integration
def test_configured_project_dem_is_read_through_catalog(tmp_path):
    from app.data.catalog import DataCatalog

    service = TerrainEvidenceService.open(
        catalog=DataCatalog(),
        cache_dir=tmp_path / "real-dem-cache",
    )
    left, bottom, right, top = service.metadata.bounds
    sample = service.sample_points(
        [((left + right) / 2.0, (bottom + top) / 2.0)],
        coordinate_crs=service.metadata.crs,
    )

    assert service.metadata.valid is True
    assert service.metadata.source_origin == "catalog"
    assert service.metadata.source_sha256.startswith("sha256:")
    assert service.metadata.is_geographic is True
    assert sample.samples[0].status == "ready"
    assert sample.samples[0].elevation_m is not None
    assert sample.samples[0].slope_degrees is not None

