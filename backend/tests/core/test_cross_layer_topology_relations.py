from types import SimpleNamespace

from app.spatial.query.bridge import compute_cross_layer_relations


def _feature(bsm: str, geometry: dict, **extra):
    return SimpleNamespace(bsm=bsm, geometry=geometry, **extra)


def test_cross_layer_topology_emits_indexed_point_relations_without_merging() -> None:
    bundle = SimpleNamespace(
        polygons={
            "landuse_current": [
                _feature(
                    "parcel-1",
                    {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [0, 0.001], [0.001, 0.001], [0.001, 0], [0, 0]]],
                    },
                )
            ]
        },
        points={
            "facilities_current": [
                _feature("facility-1", {"type": "Point", "coordinates": [0.0005, 0.0005]}),
                _feature("facility-2", {"type": "Point", "coordinates": [0.0005, 0.0005]}),
            ]
        },
        lines={},
    )

    relations = compute_cross_layer_relations(bundle)

    assert ("http://village-planning.org/ontology#facility_facility-1",
            "http://village-planning.org/ontology#facility_facility-2") in relations["same_coordinate"]
    assert relations["co_located"]
    assert relations["near"]
    assert relations["located_in"]
    assert relations["_meta"]["same_coordinate"]["crs"] == "EPSG:3857"


def test_cross_layer_topology_materializes_road_parcel_intersection() -> None:
    bundle = SimpleNamespace(
        polygons={
            "landuse_current": [
                _feature(
                    "parcel-1",
                    {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [0, 0.001], [0.001, 0.001], [0.001, 0], [0, 0]]],
                    },
                )
            ]
        },
        points={},
        lines={
            "roads_current": [
                _feature(
                    "road-1",
                    {
                        "type": "LineString",
                        "coordinates": [[-0.0001, 0.0005], [0.0011, 0.0005]],
                    },
                )
            ]
        },
    )

    relations = compute_cross_layer_relations(bundle)

    assert (
        "http://village-planning.org/ontology#road_road-1",
        "http://village-planning.org/ontology#parcel_parcel-1",
        0.0,
    ) in relations["intersects"]
