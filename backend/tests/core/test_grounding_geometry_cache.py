from types import SimpleNamespace

import app.spatial.grounding.grounding as grounding
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex


def _parcel(bsm, lon):
    return SimpleNamespace(
        bsm=bsm,
        geometry={
            "type": "Polygon",
            "coordinates":[[
                [lon, 23.0], [lon + 0.001, 23.0],
                [lon + 0.001, 23.001], [lon, 23.001], [lon, 23.0],
            ]],
        },
    )


def test_centroid_cache_reuses_geometry_across_queries(monkeypatch):
    parcels = [_parcel("bsm-1", 113.0), _parcel("bsm-2", 113.01)]
    original = grounding._parcel_centroid
    calls = []

    def counted(parcel):
        calls.append(parcel.bsm)
        return original(parcel)

    monkeypatch.setattr(grounding, "_parcel_centroid", counted)
    cache = grounding.build_parcel_centroid_cache(parcels)

    first = grounding.query_parcels_near_entity(
        parcels, (113.0, 23.0), max_distance_m=500, centroid_cache=cache
    )
    second = grounding.query_parcels_near_entity(
        parcels, (113.0, 23.0), max_distance_m=500, centroid_cache=cache
    )

    assert first == second == ["bsm-1"]
    assert calls == ["bsm-1", "bsm-2"]


def test_place_evidence_index_materializes_parcel_centroids_once(monkeypatch):
    parcels = [_parcel(f"bsm-{idx}", 113.0 + idx * 0.001) for idx in range(8)]
    pois = [
        SimpleNamespace(
            text=f"poi-{idx}",
            category="现状设施点",
            geometry={"type": "Point", "coordinates": [113.0, 23.0]},
        )
        for idx in range(30)
    ]
    context = SimpleNamespace(
        session_id="s-cache",
        version=1,
        kg_version=1,
        gazetteer=None,
        location_facts=[],
        kg=None,
        workspace=SimpleNamespace(
            points={"annotations_current": pois},
            polygons={"landuse_current": parcels},
        ),
    )
    context.current_parcels = lambda: list(parcels)
    original = grounding._parcel_centroid
    calls = []

    def counted(parcel):
        calls.append(parcel.bsm)
        return original(parcel)

    monkeypatch.setattr(grounding, "_parcel_centroid", counted)
    index = PlaceEvidenceIndex.build(context)

    # All 30 POIs share one point -> one co-located place (ER semantics).
    assert len(index.entries) == 1
    merged = index.entries[0]
    assert merged.role == "facility"
    assert len(merged.entity_refs) == len(pois)
    assert merged.source_bsms  # near-parcel BSMs merged onto the point
    assert sorted(calls) == [f"bsm-{idx}" for idx in range(8)]


def test_large_parcel_is_hit_by_point_and_bbox_geometry_not_centroid():
    large = SimpleNamespace(
        bsm="large-parcel",
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [113.0, 23.0], [113.0, 23.02],
                [113.02, 23.02], [113.02, 23.0], [113.0, 23.0],
            ]],
        },
    )

    # The point is near the parcel edge but roughly 1.5 km from its centroid.
    assert grounding.query_parcels_near_entity(
        [large],
        (113.019, 23.019),
        max_distance_m=20,
    ) == ["large-parcel"]
    assert grounding.query_parcels_in_bbox(
        [large],
        (113.018, 23.018, 113.021, 23.021),
    ) == ["large-parcel"]


def test_strtree_index_keeps_bundle_geometry_as_final_predicate():
    large = SimpleNamespace(
        bsm="large-parcel",
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [113.0, 23.0], [113.0, 23.02],
                [113.02, 23.02], [113.02, 23.0], [113.0, 23.0],
            ]],
        },
    )
    index = grounding.build_parcel_spatial_index([large])

    assert index is not None
    assert grounding.query_parcels_near_entity(
        [large],
        (113.019, 23.019),
        max_distance_m=20,
        spatial_index=index,
    ) == ["large-parcel"]
    assert grounding.query_parcels_in_bbox(
        [large],
        (113.018, 23.018, 113.021, 23.021),
        spatial_index=index,
    ) == ["large-parcel"]


def test_place_evidence_index_binds_poi_inside_large_parcel():
    large = SimpleNamespace(
        bsm="large-parcel",
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [113.0, 23.0], [113.0, 23.02],
                [113.02, 23.02], [113.02, 23.0], [113.0, 23.0],
            ]],
        },
    )
    poi = SimpleNamespace(
        text="祠堂",
        category="现状设施点",
        geometry={"type": "Point", "coordinates": [113.019, 23.019]},
        bsm="facility-1",
    )
    context = SimpleNamespace(
        session_id="large-parcel-poi",
        version=1,
        kg_version=1,
        gazetteer=None,
        location_facts=[],
        kg=None,
        workspace=SimpleNamespace(
            points={"facilities_current": [poi], "annotations_current": []},
            polygons={"landuse_current": [large]},
        ),
    )
    context.current_parcels = lambda: [large]

    index = PlaceEvidenceIndex.build(context)
    entry = next(item for item in index.entries if item.canonical_name == "祠堂")
    assert entry.source_bsms == ["large-parcel"]
