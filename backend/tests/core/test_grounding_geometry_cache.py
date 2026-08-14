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
