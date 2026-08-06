"""build_render_layers tests — DELIVER render_result derivation."""

from types import SimpleNamespace

from app.agent.deliver.render_layers import build_render_layers

_WKT = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"


def _layout(layer_type, name, features=None):
    return {
        "layerType": layer_type,
        "layerName": name,
        "data": {
            "type": "FeatureCollection",
            "features": features
            or [
                {
                    "type": "Feature",
                    "properties": {"name": name},
                    "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                }
            ],
        },
    }


def _planned_state():
    parcel = SimpleNamespace(
        bsm="BSM001",
        planning_land_use="0101",
        zone_type="农田保护区",
        operation="reclassify",
        area_ha=10.0,
        geometry=_WKT,
    )
    zone = SimpleNamespace(
        zone_type="农田保护区", name="一号片区", area_ha=20.0, geometry=_WKT
    )
    return SimpleNamespace(parcels=[parcel], zones=[zone], facilities=[], roads=[], axes=[])


def test_build_render_layers_collects_layout_configs_verbatim():
    planned_project = _layout("planned_project", "规划项目")
    function_zone = _layout("function_zone", "功能分区")
    layers = build_render_layers(
        None,
        [planned_project, function_zone],
    )
    types = [l["layerType"] for l in layers]
    assert "planned_project" in types
    assert "function_zone" in types
    for layer in layers:
        assert layer["data"]["type"] == "FeatureCollection"
        assert "features" in layer["data"]
        assert layer["geojson"] is layer["data"]


def test_build_render_layers_derives_function_zone_from_planned_state():
    layers = build_render_layers(_planned_state(), [])
    assert len(layers) == 1
    layer = layers[0]
    assert layer["layerType"] == "function_zone"
    assert layer["layerName"] == "功能分区"
    assert len(layer["data"]["features"]) == 2


def test_build_render_layers_layout_configs_win_over_planned_state():
    planned = _planned_state()
    layout_zone = _layout("function_zone", "功能分区")
    layout_zone["data"]["features"] = [{"type": "Feature", "properties": {}, "geometry": None}]
    layers = build_render_layers(planned, [layout_zone])
    zone_layers = [l for l in layers if l["layerType"] == "function_zone"]
    assert len(zone_layers) == 1
    assert zone_layers[0]["data"]["features"] == layout_zone["data"]["features"]


def test_build_render_layers_empty_inputs():
    assert build_render_layers(None, None) == []
    assert build_render_layers(None, []) == []
    assert build_render_layers(None, [], {}) == []


def test_build_render_layers_skips_malformed_entries():
    layers = build_render_layers(
        None,
        [
            "not-a-dict",
            {"layerType": "planned_project"},  # no data
            {"data": _layout("facility_point", "公共服务设施")["data"]},  # no layerType
            _layout("planned_road", "规划道路"),
        ],
    )
    assert [l["layerType"] for l in layers] == ["planned_road"]
