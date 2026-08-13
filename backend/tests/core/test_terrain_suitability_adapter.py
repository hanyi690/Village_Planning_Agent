from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box, mapping

from app.contracts.spatial.grounding_contracts import CandidateSite, HardConstraintResult
from app.contracts.spatial.terrain_evidence import TerrainSuitabilityPolicy
from app.domain.suitability import (
    FactorAvailabilityPolicy,
    SuitabilityFactorPolicies,
    TerrainCandidateFeatureAdapter,
    VersionedSuitabilityPolicy,
    audit_suitability_evidence_availability,
)


class _Group:
    def __init__(self, **layers):
        self.layers = layers

    def get(self, key):
        return self.layers.get(key, [])


class _Context:
    def __init__(self, workspace, parcels=()):
        self.workspace = workspace
        self._parcels = list(parcels)

    def current_parcels(self):
        return list(self._parcels)


def _factor(required=False, on_unavailable="report_only"):
    return FactorAvailabilityPolicy(
        required=required,
        on_unavailable=on_unavailable,
    )


def _policy(*, hazard_required=False):
    return VersionedSuitabilityPolicy(
        policy_id="village-candidate-policy",
        policy_version="2026.08.13-1",
        terrain=TerrainSuitabilityPolicy(
            preferred_max_slope_degrees=10.0,
            hard_max_slope_degrees=50.0,
            minimum_valid_fraction=0.2,
            slope_statistic="p90",
        ),
        hazard_min_distance_m=100.0,
        road_preferred_distance_m=300.0,
        facility_preferred_distance_m=1000.0,
        factors=SuitabilityFactorPolicies(
            terrain=_factor(True, "block_candidate"),
            hazard=_factor(hazard_required, "block_candidate" if hazard_required else "report_only"),
            farmland_protection=_factor(),
            ecological_protection=_factor(),
            road_access=_factor(),
            facility_coverage=_factor(),
        ),
    )


def _write_plane(path, *, crs="EPSG:3857"):
    values = np.tile(np.arange(5, dtype=np.float32) * 10.0, (5, 1))
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=5,
        width=5,
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(0.0, 50.0, 10.0, 10.0),
    ) as dataset:
        dataset.write(values, 1)
    return path


def _workspace(*, dem=None, crs="EPSG:3857", points=None, lines=None, polygons=None, tables=None):
    return SimpleNamespace(
        rasters=SimpleNamespace(dem=dem),
        metadata=SimpleNamespace(crs=crs),
        points=points or _Group(),
        lines=lines or _Group(),
        polygons=polygons or _Group(),
        tables=tables or SimpleNamespace(population=None),
    )


def _candidate(*, wkt=True, passed=True, source_parcels=("BSM-1",)):
    return CandidateSite(
        site_id="SITE-1",
        source_parcels=list(source_parcels),
        available_geometry_wkt=box(0.0, 0.0, 50.0, 50.0).wkt if wkt else "",
        hard_constraint_result=HardConstraintResult(
            constraint_id="ground",
            passed=passed,
        ),
        target_ref="TARGET-1",
        evidence_refs=["ground:evidence-1"],
    )


def test_policy_is_versioned_and_terrain_cannot_be_configured_fail_open():
    policy = _policy()

    assert policy.ref == "village-candidate-policy@2026.08.13-1"
    assert policy.digest.startswith("sha256:")
    payload = policy.model_dump(mode="json")
    payload["factors"]["terrain"] = {
        "required": False,
        "on_unavailable": "report_only",
    }
    with pytest.raises(ValidationError, match="terrain factor must be required"):
        VersionedSuitabilityPolicy.model_validate(payload)


def test_valid_dem_builds_select_ready_terrain_features_with_provenance(tmp_path):
    dem = _write_plane(tmp_path / "plane.tif")
    context = _Context(_workspace(dem=SimpleNamespace(path=str(dem))))
    adapter = TerrainCandidateFeatureAdapter.from_context(
        context,
        _policy(),
        cache_dir=tmp_path / "cache",
    )

    feature = adapter.build_candidate(_candidate())

    assert feature.terrain.status == "available"
    assert feature.terrain.elevation_min_m == pytest.approx(0.0)
    assert feature.terrain.elevation_max_m == pytest.approx(40.0)
    assert feature.terrain.slope_p90_degrees == pytest.approx(45.0)
    assert feature.terrain.classification == "conditional"
    assert feature.terrain.score == pytest.approx(0.125)
    assert feature.terrain.hard_feasible is True
    assert feature.hard_feasible is True
    assert feature.terrain.evidence_ref in feature.evidence_refs
    assert feature.terrain.provenance is not None
    assert feature.terrain.provenance.source_sha256.startswith("sha256:")
    assert feature.policy_digest == _policy().digest
    assert feature.geometry_source == "candidate_wkt"


def test_missing_dem_is_fail_closed_without_a_neutral_score():
    context = _Context(_workspace())
    adapter = TerrainCandidateFeatureAdapter.from_context(context, _policy())

    feature = adapter.build_candidate(_candidate())
    terrain_availability = next(item for item in feature.availability if item.factor == "terrain")

    assert feature.terrain.status == "missing"
    assert feature.terrain.score is None
    assert feature.terrain.hard_feasible is False
    assert feature.hard_feasible is False
    assert terrain_availability.code == "TERRAIN_DEM_MISSING"
    assert terrain_availability.blocks_candidate is True
    assert "TERRAIN_DEM_MISSING" in feature.blocking_codes


def test_invalid_dem_is_fail_closed_and_not_reported_as_missing(tmp_path):
    dem = _write_plane(tmp_path / "missing-crs.tif", crs=None)
    context = _Context(_workspace(dem=SimpleNamespace(path=str(dem))))
    adapter = TerrainCandidateFeatureAdapter.from_context(context, _policy())

    feature = adapter.build_candidate(_candidate())

    assert adapter.availability.for_factor("terrain").code == "TERRAIN_DEM_INVALID"
    assert feature.terrain.status == "invalid"
    assert feature.terrain.score is None
    assert feature.hard_feasible is False
    assert "TERRAIN_DEM_INVALID" in feature.blocking_codes


def test_unreadable_dem_content_is_typed_invalid_instead_of_crashing(tmp_path):
    dem = tmp_path / "corrupt.tif"
    dem.write_text("not a geotiff", encoding="utf-8")
    context = _Context(_workspace(dem=SimpleNamespace(path=str(dem))))

    adapter = TerrainCandidateFeatureAdapter.from_context(context, _policy())
    feature = adapter.build_candidate(_candidate())

    assert adapter.availability.for_factor("terrain").status == "invalid"
    assert adapter.availability.for_factor("terrain").code == "TERRAIN_DEM_INVALID"
    assert feature.terrain.status == "invalid"
    assert feature.terrain.score is None
    assert feature.hard_feasible is False


def test_exact_bundle_parcels_supply_geometry_when_candidate_wkt_is_absent(tmp_path):
    dem = _write_plane(tmp_path / "plane.tif")
    parcel = SimpleNamespace(bsm="BSM-1", geometry=mapping(box(0.0, 0.0, 50.0, 50.0)))
    context = _Context(
        _workspace(dem=SimpleNamespace(path=str(dem))),
        parcels=[parcel],
    )
    adapter = TerrainCandidateFeatureAdapter.from_context(context, _policy())

    feature = adapter.build_candidate(_candidate(wkt=False))

    assert feature.geometry_source == "bundle_source_parcels"
    assert feature.terrain.status == "available"
    assert feature.hard_feasible is True


def test_missing_source_parcel_does_not_union_a_partial_candidate(tmp_path):
    dem = _write_plane(tmp_path / "plane.tif")
    existing = SimpleNamespace(bsm="BSM-1", geometry=mapping(box(0.0, 0.0, 20.0, 20.0)))
    context = _Context(
        _workspace(dem=SimpleNamespace(path=str(dem))),
        parcels=[existing],
    )
    adapter = TerrainCandidateFeatureAdapter.from_context(context, _policy())

    feature = adapter.build_candidate(
        _candidate(wkt=False, source_parcels=("BSM-1", "BSM-MISSING"))
    )

    assert feature.geometry_source == "unavailable"
    assert feature.terrain.status == "invalid"
    assert feature.terrain.score is None
    assert "CANDIDATE_SOURCE_PARCEL_NOT_FOUND:BSM-MISSING" in feature.blocking_codes


def test_grounding_hard_constraint_failure_remains_blocking_after_terrain_passes(tmp_path):
    dem = _write_plane(tmp_path / "plane.tif")
    context = _Context(_workspace(dem=SimpleNamespace(path=str(dem))))
    adapter = TerrainCandidateFeatureAdapter.from_context(context, _policy())

    feature = adapter.build_candidate(_candidate(passed=False))

    assert feature.terrain.hard_feasible is True
    assert feature.grounding_hard_feasible is False
    assert feature.hard_feasible is False
    assert "GROUND_HARD_CONSTRAINTS_FAILED" in feature.blocking_codes


def test_bundle_sources_produce_machine_readable_source_only_diagnostics(tmp_path):
    dem = _write_plane(tmp_path / "plane.tif")
    point_feature = SimpleNamespace(geometry=mapping(Point(5.0, 5.0)))
    facility = SimpleNamespace(
        geometry=mapping(Point(6.0, 6.0)),
        service_radius=800.0,
    )
    polygon_feature = SimpleNamespace(geometry=mapping(box(0.0, 0.0, 10.0, 10.0)))
    road_feature = SimpleNamespace(geometry=mapping(LineString([(0.0, 0.0), (10.0, 10.0)])))
    population = SimpleNamespace(
        rows=[{"village": "cluster-a", "population": 100, "lon": 5.0, "lat": 5.0}]
    )
    context = _Context(
        _workspace(
            dem=SimpleNamespace(path=str(dem)),
            points=_Group(
                hazard_points=[point_feature],
                facilities_current=[facility],
                annotations_current=[point_feature],
            ),
            lines=_Group(roads_current=[road_feature]),
            polygons=_Group(
                farmland_protection=[polygon_feature],
                ecological_redline=[polygon_feature],
            ),
            tables=SimpleNamespace(population=population),
        )
    )
    report = audit_suitability_evidence_availability(
        context,
        _policy(),
        terrain_service=TerrainCandidateFeatureAdapter.from_context(
            context, _policy()
        ).terrain_service,
    )

    assert report.for_factor("terrain").status == "available"
    assert report.for_factor("hazard").status == "source_only"
    assert report.for_factor("farmland_protection").usable_count == 1
    assert report.for_factor("ecological_protection").usable_count == 1
    assert report.for_factor("road_access").usable_count == 1
    facility_diag = report.for_factor("facility_coverage")
    assert facility_diag.status == "source_only"
    assert facility_diag.code == "FACILITY_COVERAGE_SOURCE_AVAILABLE_FEATURE_NOT_COMPUTED"
    assert facility_diag.details["positive_service_radius_count"] == 1
    assert facility_diag.details["geolocated_demand_count"] == 1
    assert all(item.status != "available" for item in report.diagnostics[1:])


def test_required_uncomputed_factor_blocks_instead_of_receiving_neutral_weight(tmp_path):
    dem = _write_plane(tmp_path / "plane.tif")
    hazard = SimpleNamespace(geometry=mapping(Point(5.0, 5.0)))
    context = _Context(
        _workspace(
            dem=SimpleNamespace(path=str(dem)),
            points=_Group(hazard_points=[hazard]),
        )
    )
    adapter = TerrainCandidateFeatureAdapter.from_context(
        context,
        _policy(hazard_required=True),
    )

    feature = adapter.build_candidate(_candidate())
    hazard_diag = next(item for item in feature.availability if item.factor == "hazard")

    assert feature.terrain.score == pytest.approx(0.125)
    assert hazard_diag.status == "source_only"
    assert hazard_diag.blocks_candidate is True
    assert feature.hard_feasible is False
    assert "HAZARD_SOURCE_AVAILABLE_FEATURE_NOT_COMPUTED" in feature.blocking_codes
    assert "0.5" not in feature.model_dump_json()


def test_population_rows_without_coordinates_do_not_fake_facility_coverage_inputs(tmp_path):
    dem = _write_plane(tmp_path / "plane.tif")
    facility = SimpleNamespace(
        geometry=mapping(Point(6.0, 6.0)),
        service_radius=800.0,
    )
    context = _Context(
        _workspace(
            dem=SimpleNamespace(path=str(dem)),
            points=_Group(facilities_current=[facility]),
            tables=SimpleNamespace(
                population=SimpleNamespace(
                    rows=[{"village": "cluster-a", "population": 100}]
                )
            ),
        )
    )
    adapter = TerrainCandidateFeatureAdapter.from_context(context, _policy())

    diagnostic = adapter.availability.for_factor("facility_coverage")

    assert diagnostic.code == "FACILITY_COVERAGE_INPUTS_INCOMPLETE"
    assert diagnostic.details["population_row_count"] == 1
    assert diagnostic.details["geolocated_demand_count"] == 0
    assert "geolocated demand points" in diagnostic.missing_fields
