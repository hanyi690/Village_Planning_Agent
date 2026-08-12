from types import SimpleNamespace

from app.domain.delivery.render_layers import build_delivery_render_layers
from app.domain.delivery.delivery_validator import (
    assess_render_quality,
)
from app.infrastructure.export.delivery_snapshot import (
    build_delivery_spatial_snapshot_from_gis_data,
    canonical_gis_data_from_workspace,
)
import pytest


def _parcel(bsm: str, landuse: str, geometry: str, project_ref: str = ""):
    return SimpleNamespace(
        bsm=bsm,
        planning_land_use=landuse,
        zone_type=landuse,
        area_ha=1.0,
        operation="reclassify",
        derived_from_bsms=[bsm],
        geometry=geometry,
        project_ref=project_ref,
    )


def test_delivery_render_uses_current_layer_from_data_bundle(tmp_path):
    current = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"bsm": "P001", "dlbm": "0101"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"bsm": "P002", "dlbm": "0301"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10, 0], [20, 0], [20, 10], [10, 10], [10, 0]]],
                },
            },
        ],
    }
    workspace = SimpleNamespace(to_delivery_inputs=lambda: {"landuse_current_geojson": current})
    effective = canonical_gis_data_from_workspace(workspace)
    snapshot = build_delivery_spatial_snapshot_from_gis_data(
        effective,
        planned_geojson={"type": "FeatureCollection", "features": []},
        output_dir=tmp_path / "snapshot",
    )
    layers = build_delivery_render_layers(snapshot)

    types = {layer.get("layerType") or layer.get("layer_type") for layer in layers}
    assert "current_landuse" in types
    assert "complete_planned_landuse" in types
    planned = next(
        layer
        for layer in layers
        if (layer.get("layerType") or layer.get("layer_type")) == "complete_planned_landuse"
    )
    assert len(planned["geojson"]["features"]) == 2

    from app.infrastructure.rendering.static_render import render_comparison_preview

    preview = render_comparison_preview(layers, str(tmp_path), "render-quality")
    assert preview["status"] == "completed"
    assert preview["panel_count"] == 2
    assert preview["planned_change_count"] == 0
    assert preview["planned_point_count"] == 0
    quality = assess_render_quality(layers)
    assert quality["status"] == "passed"
    assert quality["current_feature_count"] == 2
    assert quality["complete_planned_feature_count"] == 2


def test_delivery_data_layer_rejects_missing_current_landuse():
    with pytest.raises(ValueError, match="lacks landuse_current_geojson"):
        canonical_gis_data_from_workspace(SimpleNamespace(to_delivery_inputs=lambda: {}))


def test_delivery_exposes_project_footprint_and_small_location_point():
    from app.domain.delivery.render_layers import build_planned_overlay_layers

    layers = build_planned_overlay_layers(SimpleNamespace(parcels=[_parcel(
        "P001",
        "产业用地",
        "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))",
        project_ref="project-north",
    )]))
    by_type = {
        layer["layerType"]: layer
        for layer in layers
    }
    assert len(by_type["planned_project"]["geojson"]["features"]) == 1
    point = by_type["planned_project_point"]["geojson"]["features"][0]
    assert point["geometry"]["type"] == "Point"
    assert point["properties"]["project_ref"] == "project-north"
    assert point["properties"]["marker_size"] == "small"


def test_delivery_rejects_placeholder_development_axis_geometry():
    layers = [
        {
            "layerType": "current_landuse",
            "geojson": {"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {}, "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                }},
            ]},
        },
        {
            "layerType": "complete_planned_landuse",
            "geojson": {"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {}, "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                }},
            ]},
        },
        {
            "layerType": "development_axis",
            "geojson": {"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {}, "geometry": {
                    "type": "Point", "coordinates": [0, 0],
                }},
            ]},
        },
    ]

    quality = assess_render_quality(layers)

    assert quality["status"] == "failed"
    assert quality["placeholder_geometry_count"] == 1


def test_delivery_style_reads_lowercase_source_landuse_fields():
    from app.spatial.delivery import classification_color

    assert classification_color({"dlmc": "水域"}) == "#6fb7d6"


def test_delivery_snapshot_repairs_source_topology_and_drops_axis_placeholder(tmp_path):
    invalid = {
        "type": "MultiPolygon",
        "coordinates": [[[
            [0, 0], [2, 2], [0, 2], [2, 0], [0, 0]
        ]]],
    }
    gis_data = {
        "landuse_current_geojson": {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {"BSM": "P1"}, "geometry": invalid}],
        },
        "planned_axis_geojson": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"target_id": "axis-1"},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }],
        },
    }

    snapshot = build_delivery_spatial_snapshot_from_gis_data(
        gis_data,
        planned_geojson={"type": "FeatureCollection", "features": []},
        output_dir=tmp_path / "snapshot",
    )
    quality = assess_render_quality(build_delivery_render_layers(snapshot))

    assert quality["status"] == "passed"
    assert quality["invalid_geometry_count"] == 0
    assert quality["placeholder_geometry_count"] == 0
