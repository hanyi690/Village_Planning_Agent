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


def _render_feature(geometry, **properties):
    return {"type": "Feature", "properties": properties, "geometry": geometry}


def _render_layer(layer_type, layer_name, features, color="#64748b"):
    payload = {"type": "FeatureCollection", "features": features}
    return {
        "layer_type": layer_type,
        "layer_name": layer_name,
        "geojson": payload,
        "color": color,
    }


def test_comparison_renderer_distinguishes_authoritative_planning_outputs(tmp_path):
    from app.infrastructure.rendering.html_render import render_interactive_map
    from app.infrastructure.rendering.static_render import render_comparison_preview

    boundary = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1000, 0], [1000, 800], [0, 800], [0, 0]]],
    }
    base = _render_feature(boundary, DLMC="耕地", BSM="P001")
    changed = _render_feature(
        {
            "type": "Polygon",
            "coordinates": [[[350, 250], [550, 250], [550, 430], [350, 430], [350, 250]]],
        },
        planning_land_use="公共服务设施用地",
        change_status="modified",
        BSM="P001",
    )
    layers = [
        _render_layer("current_landuse", "现状地类", [base]),
        _render_layer("complete_planned_landuse", "完整期末地类", [changed]),
        _render_layer("planned_changes", "规划变更地块", [changed], "#dc2626"),
        _render_layer(
            "planned_road",
            "规划道路",
            [
                _render_feature(
                    {"type": "LineString", "coordinates": [[80, 120], [900, 680]]},
                    name="产业联络路",
                    road_level="乡道",
                    action="new",
                ),
                _render_feature(
                    {"type": "LineString", "coordinates": [[120, 700], [850, 160]]},
                    name="村道提升段",
                    road_level="村道",
                    action="upgrade",
                ),
            ],
            "#d97706",
        ),
        _render_layer(
            "planning_zone",
            "规划分区",
            [_render_feature(boundary, zone_name="农业生产区")],
            "#16a34a",
        ),
        _render_layer(
            "planned_project_point",
            "规划项目点",
            [
                _render_feature({"type": "Point", "coordinates": [420, 340]}, project_name="综合服务中心"),
                _render_feature({"type": "Point", "coordinates": [640, 520]}, project_name="农产品展销点"),
            ],
            "#b91c1c",
        ),
        _render_layer(
            "facility_point",
            "公共服务设施",
            [
                _render_feature({"type": "Point", "coordinates": [300, 520]}, name="卫生室"),
                _render_feature({"type": "Point", "coordinates": [700, 300]}, name="文化活动室"),
            ],
            "#1d4ed8",
        ),
        _render_layer("boundary", "村域边界", [_render_feature(boundary)], "#0f172a"),
    ]

    result = render_comparison_preview(layers, str(tmp_path), "渲染测试样图")

    assert result["status"] == "completed"
    assert result["planned_road_count"] == 2
    assert result["planned_zone_count"] == 1
    assert result["planned_point_count"] == 4
    assert result["labelled_point_count"] == 4
    assert result["change_badge_count"] == 1
    assert result["missing_outputs"] == []
    assert result["road_styles"] == ["乡道 · 新建", "村道 · 改造"]
    assert result["scale_bar"]["distance_m"] > 0
    assert result["panels"]["planned"]["north_arrow"] is True
    assert result["panels"]["planned"]["layout"]["legend_overlaps_map"] is False
    assert result["panels"]["planned"]["layout"]["title_reserved_above_map"] is True
    assert (tmp_path / "planning_preview.png").stat().st_size > 20_000

    html_result = render_interactive_map(layers, str(tmp_path), "渲染测试样图")
    document = (tmp_path / "planning_map.html").read_text(encoding="utf-8")
    assert html_result["status"] == "completed"
    assert 'stroke-dasharray="14 8"' in document
    assert "PLANNED_ROAD_NOT_GENERATED" not in document
    assert "PLANNED_ZONE_NOT_GENERATED" not in document


def test_comparison_renderer_reports_missing_roads_and_zones(tmp_path):
    from app.infrastructure.rendering.static_render import render_comparison_preview

    polygon = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
    }
    feature = _render_feature(polygon, DLMC="耕地", change_status="preserved")
    layers = [
        _render_layer("current_landuse", "现状地类", [feature]),
        _render_layer("complete_planned_landuse", "完整期末地类", [feature]),
        _render_layer("boundary", "村域边界", [_render_feature(polygon)]),
    ]

    result = render_comparison_preview(layers, str(tmp_path), "无空间成果样图")

    assert result["status"] == "completed"
    assert result["missing_outputs"] == ["规划道路", "规划分区"]
    assert result["planned_road_count"] == 0
    assert result["planned_zone_count"] == 0
    assert result["planned_change_count"] == 0
    assert result["change_badge_count"] == 0
    assert "规划道路" not in result["panels"]["planned"]["legend_items"]
    assert "规划分区" not in result["panels"]["planned"]["legend_items"]

    from app.infrastructure.rendering.html_render import render_interactive_map

    render_interactive_map(layers, str(tmp_path), "无空间成果样图")
    document = (tmp_path / "planning_map.html").read_text(encoding="utf-8")
    assert "PLANNED_ROAD_NOT_GENERATED" in document
    assert "PLANNED_ZONE_NOT_GENERATED" in document
