from types import SimpleNamespace

from shapely import wkt
from shapely.geometry import box

from app.contracts.spatial.grounding_contracts import CandidateSite, GroundingResult, HardConstraintResult
from app.domain.suitability.service import build_suitability_surface
from app.domain.suitability.subgeometry import derive_planning_subgeometry
from app.spatial.model.crs_engine import project_geometry


def test_subgeometry_uses_metric_crs_for_wgs84_bundle_geometry() -> None:
    source = box(116.0, 23.0, 116.001, 23.0008)

    result = derive_planning_subgeometry(
        source.wkt,
        source_crs="EPSG:4326",
        target_area_ha=0.6,
    )

    assert result is not None
    assert result.operation == "obb_subdivide"
    assert result.metric_crs.startswith("EPSG:")
    assert 0.5 <= result.planning_area_ha <= 0.7
    assert 0.0 < result.coverage_ratio < 1.0
    output = wkt.loads(result.geometry_wkt)
    assert source.buffer(1e-9).covers(output)

    metric_source = project_geometry(source, "EPSG:4326", result.metric_crs)
    metric_output = project_geometry(output, "EPSG:4326", result.metric_crs)
    assert metric_output.area <= metric_source.area


def test_subgeometry_applies_allowed_and_avoid_geometry_before_split() -> None:
    source = box(0.0, 0.0, 100.0, 100.0)
    result = derive_planning_subgeometry(
        source.wkt,
        source_crs="EPSG:3857",
        target_area_ha=0.5,
        allowed_geometry_wkt=box(0.0, 0.0, 100.0, 80.0).wkt,
        avoid_geometry_wkts=[box(0.0, 0.0, 20.0, 80.0).wkt],
    )

    assert result is not None
    assert result.feasible
    assert "intersected_allowed_geometry" in result.diagnostics
    assert "subtracted_avoid_geometry" in result.diagnostics
    output = wkt.loads(result.geometry_wkt)
    assert output.intersection(box(0.0, 0.0, 20.0, 80.0)).area == 0.0
    assert result.planning_area_ha <= 0.5 * 1.05


def test_subgeometry_fails_closed_when_requested_area_is_unavailable() -> None:
    result = derive_planning_subgeometry(
        box(0.0, 0.0, 100.0, 100.0).wkt,
        source_crs="EPSG:3857",
        target_area_ha=2.0,
    )

    assert result is not None
    assert not result.feasible
    assert result.geometry_wkt
    assert "planning_area_insufficient" in result.diagnostics


def test_suitability_promotes_clipped_geometry_for_site_area_target() -> None:
    source = box(0.0, 0.0, 400.0, 200.0)
    parcel = SimpleNamespace(
        bsm="P-LARGE",
        geometry={
            "type": "Polygon",
            "coordinates": [list(source.exterior.coords)],
        },
        area_sqm=80_000.0,
    )

    class Context:
        workspace = SimpleNamespace(
            metadata=SimpleNamespace(crs="EPSG:3857"),
            lines={"roads_current": []},
            points={"facilities_current": [], "hazard_points": []},
            polygons={
                "farmland_protection": [],
                "ecological_redline": [],
            },
            tables=SimpleNamespace(population=None),
            rasters={},
        )

        def current_parcels(self):
            return [parcel]

    grounding = GroundingResult(
        candidates=[
            CandidateSite(
                site_id="site:T1",
                target_ref="T1",
                source_parcels=["P-LARGE"],
                available_geometry_wkt=source.wkt,
                hard_constraint_result=HardConstraintResult(passed=True),
            )
        ]
    )
    intent = SimpleNamespace(
        site_area_targets=[
            SimpleNamespace(
                target_id="T1",
                expected_output_kind="polygon",
                materialization_role="site_footprint",
                footprint_area_m2=6_000.0,
                area_ha=None,
            )
        ],
        zone_targets=[],
    )

    surface = build_suitability_surface(grounding, Context(), plan_intent=intent)

    candidate = surface.candidates[0]
    assert candidate.geometry_operation == "obb_subdivide"
    assert candidate.source_area_ha == 8.0
    assert 0.55 <= candidate.available_area_ha <= 0.65
    assert 0.06 <= candidate.coverage_ratio <= 0.09
    assert wkt.loads(candidate.available_geometry_wkt).area <= source.area
