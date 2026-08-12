import json
from types import SimpleNamespace

from app.agent.deliver.render_layers import build_delivery_render_layers
from app.modules.spatial_ops.output.export_package import export_delivery_package
from app.tools.gis.html_render import render_interactive_map
from app.tools.gis.static_render import render_map_preview
from app.modules.spatial_ops.io import build_delivery_spatial_snapshot_from_gis_data


def _polygon(x0, y0, x1, y1):
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def _feature(bsm, geometry, **properties):
    return {
        "type": "Feature",
        "properties": {"BSM": bsm, **properties},
        "geometry": geometry,
    }


def _current_landuse():
    return {
        "type": "FeatureCollection",
        "features": [
            _feature("P001", _polygon(0, 0, 1, 1), DLBM="0101", area_sqm=10000),
            _feature("P002", _polygon(1, 0, 2, 1), DLBM="0201", area_sqm=20000),
        ],
    }


def test_delivery_layers_include_complete_planned_and_control_aliases(tmp_path):
    gis_data = {
        "boundary_geojson": {
            "type": "FeatureCollection",
            "features": [_feature("boundary", _polygon(0, 0, 2, 1))],
        },
        "landuse_current_geojson": _current_landuse(),
        "road_geojson": {"type": "FeatureCollection", "features": []},
        "annotation_geojson": {"type": "FeatureCollection", "features": []},
        "ecological_redline_geojson": {
            "type": "FeatureCollection",
            "features": [_feature("eco", _polygon(0, 0, 0.5, 0.5))],
        },
        "farmland_protection_geojson": {
            "type": "FeatureCollection",
            "features": [_feature("farm", _polygon(0, 0, 0.5, 0.5))],
        },
        "construction_zone_geojson": {
            "type": "FeatureCollection",
            "features": [_feature("construction", _polygon(1, 0, 1.5, 0.5))],
        },
    }

    snapshot = build_delivery_spatial_snapshot_from_gis_data(
        gis_data,
        planned_geojson={"type": "FeatureCollection", "features": []},
        output_dir=tmp_path / "snapshot",
    )
    layers = build_delivery_render_layers(snapshot)
    layer_types = {layer.get("layer_type") or layer.get("layerType") for layer in layers}
    planned = next(
        layer
        for layer in layers
        if (layer.get("layer_type") or layer.get("layerType"))
        == "complete_planned_landuse"
    )

    assert {"current_landuse", "complete_planned_landuse", "boundary", "input_constraint"} <= layer_types
    assert len(planned["geojson"]["features"]) == 2
    assert planned["layerName"] == "完整期末地类（含未修改地块）"
    assert planned["style"]["line-color"] == "#475569"
    assert planned["style"]["fill-opacity"] < 0.25


def test_export_uses_the_same_complete_planned_snapshot_for_landuse_and_balance(tmp_path):
    gis_data = {
        "boundary_geojson": {"type": "FeatureCollection", "features": []},
        "landuse_current_geojson": _current_landuse(),
        "road_geojson": {"type": "FeatureCollection", "features": []},
        "annotation_geojson": {"type": "FeatureCollection", "features": []},
        "ecological_redline_geojson": {"type": "FeatureCollection", "features": []},
        "farmland_protection_geojson": {"type": "FeatureCollection", "features": []},
        "construction_zone_geojson": {"type": "FeatureCollection", "features": []},
    }
    allocated = {
        "type": "FeatureCollection",
        "features": [
            _feature(
                "P001",
                _polygon(0, 0, 1, 1),
                DLBM="0101",
                area_sqm=10000,
                planning_land_use="0201",
            )
        ],
    }

    snapshot = build_delivery_spatial_snapshot_from_gis_data(
        gis_data,
        planned_geojson=_current_landuse(),
        output_dir=tmp_path / "snapshot",
    )
    result = export_delivery_package(
        layout_configs=[],
        snapshot=snapshot,
        village_name="test-village",
        output_dir=str(tmp_path),
    )

    planned_path = tmp_path / "planned" / "landuse.geojson"
    balance_path = tmp_path / "tables" / "land_balance.json"
    planned = json.loads(planned_path.read_text(encoding="utf-8"))
    balance = json.loads(balance_path.read_text(encoding="utf-8"))
    assert len(planned["features"]) == 2
    assert balance["total_area_ha"] == 3.0
    assert "current/road.geojson" in result["exported_files"]


def test_map_files_use_boundary_extent_and_html_layer_toggles(tmp_path):
    layers = [
        {
            "layer_type": "boundary",
            "layer_name": "boundary",
            "geojson": {"type": "FeatureCollection", "features": [_feature("b", _polygon(0, 0, 2, 1))]},
        },
        {
            "layer_type": "complete_planned_landuse",
            "layer_name": "完整期末地类",
            "geojson": {
                "type": "FeatureCollection",
                "features": [_feature("outlier", _polygon(100, 100, 101, 101))],
            },
        },
    ]

    png = render_map_preview(layers, str(tmp_path), "test-village")
    html = render_interactive_map(layers, str(tmp_path), "test-village")

    assert png["extent"] == [0.0, 0.0, 2.0, 1.0]
    assert html["extent"] == [0.0, 0.0, 2.0, 1.0]
    document = (tmp_path / "planning_map.html").read_text(encoding="utf-8")
    assert 'type="checkbox"' in document
    assert 'data-target="layer-0"' in document
