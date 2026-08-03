from app.modules.spatial_ops.custom_planning import (
    PENDING_ZONE_NAME,
    build_custom_planning_zone_layer,
    build_custom_zone_allocation_inputs,
    validate_custom_planning_zone_layer,
)


def _feature(bsm, coordinates, assigned_zone=""):
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
        "properties": {
            "BSM": bsm,
            "area_sqm": 10000,
            "assigned_zone": assigned_zone,
        },
    }


def test_custom_zone_inputs_add_pending_coverage_zone():
    landuse = {
        "type": "FeatureCollection",
        "features": [
            _feature("A", [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]),
            _feature("B", [[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]),
        ],
    }
    zones = [{
        "pln:category_name_zh": "产业发展区",
        "pln:category_code": "industry",
        "pln:target_bsms": ["A"],
        "pln:area_target_ha": 1.0,
        "pln:geometry": None,
    }]

    targets, candidates, metadata = build_custom_zone_allocation_inputs(landuse, zones)

    assert targets["产业发展区"] == 1.0
    assert candidates["产业发展区"] == ["A"]
    assert candidates[PENDING_ZONE_NAME] == ["B"]
    assert metadata[PENDING_ZONE_NAME]["zone_id"] == "CZ-PENDING"


def test_custom_zone_layer_is_grouped_by_global_allocation():
    allocated = {
        "type": "FeatureCollection",
        "features": [
            _feature("A", [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], "产业发展区"),
            _feature("B", [[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]], PENDING_ZONE_NAME),
        ],
    }
    metadata = {
        "产业发展区": {
            "zone_id": "CZ-01", "category_code": "industry", "color": "#f00",
            "target_area_ha": 1.0, "target_bsms": ["A"], "decided_by": "rule",
            "confidence": 0.8, "vocabulary_name": "test",
        },
        PENDING_ZONE_NAME: {
            "zone_id": "CZ-PENDING", "category_code": "pending", "color": "#999",
            "target_area_ha": 1.0, "target_bsms": ["B"], "decided_by": "coverage_repair",
            "confidence": 0.0, "vocabulary_name": "",
        },
    }

    layer = build_custom_planning_zone_layer(allocated, metadata)
    by_name = {feature["properties"]["zone_name"]: feature for feature in layer["features"]}

    assert set(by_name) == {"产业发展区", PENDING_ZONE_NAME}
    assert by_name["产业发展区"]["properties"]["status"] == "generated"
    assert by_name[PENDING_ZONE_NAME]["properties"]["requires_human_confirmation"] is True


def test_detached_custom_component_is_marked_pending():
    allocated = {
        "type": "FeatureCollection",
        "features": [
            _feature("A", [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], "产业发展区"),
            _feature("B", [[3, 0], [4, 0], [4, 1], [3, 1], [3, 0]], "产业发展区"),
        ],
    }
    metadata = {
        "产业发展区": {
            "zone_id": "CZ-01", "category_code": "industry", "color": "#f00",
            "target_area_ha": 2.0, "target_bsms": ["A", "B"], "decided_by": "rule",
            "confidence": 0.8, "vocabulary_name": "test",
        },
        PENDING_ZONE_NAME: {
            "zone_id": "CZ-PENDING", "category_code": "pending", "color": "#999",
            "target_area_ha": 0.0, "target_bsms": [], "decided_by": "coverage_repair",
            "confidence": 0.0, "vocabulary_name": "",
        },
    }

    layer = build_custom_planning_zone_layer(allocated, metadata)
    by_name = {feature["properties"]["zone_name"]: feature for feature in layer["features"]}

    assert by_name["产业发展区"]["properties"]["parcel_count"] == 1
    assert by_name[PENDING_ZONE_NAME]["properties"]["parcel_count"] == 1


def test_custom_zone_validation_detects_overlap():
    layer = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": _feature("A", [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]])["geometry"], "properties": {}},
            {"type": "Feature", "geometry": _feature("B", [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]])["geometry"], "properties": {}},
        ],
    }

    report = validate_custom_planning_zone_layer(layer)

    assert report["passed"] is False
    assert report["overlap_area_native"] > 0
