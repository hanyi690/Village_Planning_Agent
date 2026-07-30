"""Tests for dynamic LayerGroup _layers dict + VillageBundle.add()."""


def test_layer_group_add_and_get():
    from app.modules.schema.types.canonical import PolygonLayerGroup
    from app.modules.schema.types.spatial_types import CurrentLandUseParcel

    group = PolygonLayerGroup()
    p = CurrentLandUseParcel(
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        bsm="001", dlbm="0101",
    )
    group.add(p)
    parcels = group.get("landuse_current")
    assert len(parcels) == 1
    assert parcels[0].bsm == "001"


def test_unknown_layer_type_goes_to_inferred():
    from app.modules.schema.types.canonical import PolygonLayerGroup
    from app.modules.schema.types.spatial_types import PolygonFeature

    feat = PolygonFeature(
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        layer_type="unknown_type",
    )
    group = PolygonLayerGroup()
    group.add(feat)
    inferred = group.get("inferred")
    assert len(inferred) == 1


def test_village_bundle_add_routes_by_geometry():
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.schema.types.spatial_types import (
        CurrentLandUseParcel, CurrentRoad, CurrentFacility,
    )

    bundle = VillageBundle(village_name="test")
    parcel = CurrentLandUseParcel(
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        bsm="001",
    )
    road = CurrentRoad(
        geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        bsm="002",
    )
    facility = CurrentFacility(
        geometry={"type": "Point", "coordinates": [0.5, 0.5]},
        bsm="003",
    )
    bundle.add(parcel)
    bundle.add(road)
    bundle.add(facility)
    assert len(bundle.polygons.get("landuse_current")) == 1
    assert len(bundle.lines.get("roads_current")) == 1
    assert len(bundle.points.get("facilities_current")) == 1


def test_village_bundle_boundary():
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.schema.types.spatial_types import AdminArea

    bundle = VillageBundle(village_name="test")
    a = AdminArea(
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        bsm="001",
    )
    bundle.add(a)
    assert bundle.boundary is not None
    assert len(bundle.boundary.bsm) == 20
    assert bundle.boundary.bsm.isdigit()


def test_to_geojson_dict_from_layers():
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.schema.types.spatial_types import CurrentLandUseParcel, WaterFeature

    bundle = VillageBundle(village_name="test")
    p = CurrentLandUseParcel(
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        bsm="001", dlbm="0101",
    )
    w = WaterFeature(
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        bsm="002",
    )
    bundle.add(p)
    bundle.add(w)
    result = bundle.to_geojson_dict()
    assert "landuse_current_geojson" in result
    assert "water_geojson" in result


def test_parcel_count_from_layers():
    from app.modules.schema.types.canonical import VillageBundle
    from app.modules.schema.types.spatial_types import (
        CurrentLandUseParcel, PlannedLandUseParcel,
    )

    bundle = VillageBundle(village_name="test")
    bundle.add(CurrentLandUseParcel(
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        bsm="001",
    ))
    bundle.add(PlannedLandUseParcel(
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        bsm="002",
    ))
    assert bundle.parcel_count == 2