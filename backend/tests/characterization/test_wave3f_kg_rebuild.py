from __future__ import annotations

from types import SimpleNamespace

from rdflib import Literal

from app.data.model.canonical import VillageBundle, VillageMetadata
from app.data.model.spatial_types import (
    CurrentAnnotation,
    CurrentLandUseParcel,
    CurrentRoad,
)
from app.infrastructure.kg.builder import KGBuilder
from app.infrastructure.kg.manager import compute_layer1_cache_key, get_kg_manager
from app.infrastructure.kg.session_kg import _kg_layer1_parent
from app.infrastructure.kg.ontology import GeoPredicates, PLN
from app.infrastructure.kg.queries.spatial_ref import _resolve_exact_reference_geometries
from app.contracts.spatial.spatial_reference_contracts import RefObject, SpatialReferenceSpec


def _bundle(*, road_x: float = 1.0, point_x: float = 0.25) -> VillageBundle:
    bundle = VillageBundle(
        village_name="wave3f-fixture",
        metadata=VillageMetadata(village_name="wave3f-fixture"),
    )
    bundle.add(
        CurrentLandUseParcel(
            geometry={
                "type": "Polygon",
                "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]],
            },
            BSM="123456789012345678",
            dlbm="0101",
            area_sqm=4.0,
        )
    )
    bundle.add(
        CurrentRoad(
            geometry={
                "type": "MultiLineString",
                "coordinates": [[[
                    0.0,
                    0.0,
                ], [road_x, 1.0]]],
            },
            road_name="source-road",
            _raw={
                "source_feature_id": "http://village-planning.org/source-feature/road/1",
                "source_uri": "roads.geojson",
                "source_content_digest": "sha256:roads",
                "source_geometry_digest": f"sha256:road:{road_x}",
                "source_feature_index": 0,
            },
        )
    )
    bundle.add(
        CurrentAnnotation(
            geometry={"type": "Point", "coordinates": [point_x, 0.5]},
            text="站",
            category="现状设施点",
            _raw={
                "source_feature_id": "http://village-planning.org/source-feature/annotation/1",
                "source_uri": "annotation.geojson",
                "source_content_digest": "sha256:annotations",
                "source_geometry_digest": f"sha256:point:{point_x}",
                "source_feature_index": 0,
            },
        )
    )
    return bundle


def _source_uri(kg, source_id: str):
    return next(
        kg.g.subjects(PLN.source_feature_id, Literal(source_id)),
        None,
    )


def _source_wkt(kg, source_id: str) -> str:
    uri = _source_uri(kg, source_id)
    assert uri is not None
    geometry = kg.g.value(uri, GeoPredicates.hasGeometry)
    assert geometry is not None
    return str(kg.g.value(geometry, GeoPredicates.asWKT) or "")


def test_fresh_layer1_contains_authoritative_point_and_multiline_wkt() -> None:
    bundle = _bundle()
    kg = KGBuilder.build(bundle.village_name, bundle)

    annotation_id = "http://village-planning.org/source-feature/annotation/1"
    road_id = "http://village-planning.org/source-feature/road/1"
    assert _source_wkt(kg, annotation_id).startswith("POINT (")
    assert _source_wkt(kg, road_id).startswith("MULTILINESTRING (")

    spec = SpatialReferenceSpec(
        type="directional",
        relation="existing",
        reference=RefObject(
            kind="entity_type",
            filter={
                "rdf_type": "Road",
                "source_feature_ids": [road_id],
            },
        ),
    )
    geometries = _resolve_exact_reference_geometries(
        kg,
        spec,
        spec.reference,
        [road_id],
    )
    assert len(geometries) == 1
    assert geometries[0].source_ref == road_id
    assert geometries[0].wkt.startswith("MULTILINESTRING (")


def test_canonical_bundle_cache_digest_includes_typed_source_layers() -> None:
    first = _bundle(road_x=1.0, point_x=0.25)
    changed_road = _bundle(road_x=1.5, point_x=0.25)
    changed_point = _bundle(road_x=1.0, point_x=0.75)
    parcels = first.polygons.get("landuse_current")

    first_key = compute_layer1_cache_key(
        first.village_name, parcels, bundle=first
    )
    assert first_key is not None
    assert first_key != compute_layer1_cache_key(
        changed_road.village_name,
        changed_road.polygons.get("landuse_current"),
        bundle=changed_road,
    )
    assert first_key != compute_layer1_cache_key(
        changed_point.village_name,
        changed_point.polygons.get("landuse_current"),
        bundle=changed_point,
    )
    assert _kg_layer1_parent(first, "s1") != _kg_layer1_parent(changed_road, "s1")
    assert _kg_layer1_parent(first, "s1") != _kg_layer1_parent(changed_point, "s1")


def test_manager_rebuilds_when_canonical_source_digest_changes() -> None:
    manager = get_kg_manager()
    previous = manager.cache_enabled
    manager.cache_enabled = True
    first_session = "wave3f-first"
    second_session = "wave3f-second"
    try:
        first_kg, first_hit = manager.get_or_build_layer1(
            "wave3f-fixture", bundle=_bundle(road_x=1.0)
        )
        changed_kg, changed_hit = manager.get_or_build_layer1(
            "wave3f-fixture", bundle=_bundle(road_x=1.5)
        )
        assert first_hit is False
        assert changed_hit is False
        road_id = "http://village-planning.org/source-feature/road/1"
        assert _source_wkt(first_kg, road_id) != _source_wkt(
            changed_kg, road_id
        )
        manager.register_session(first_session, first_kg)
        manager.register_session(second_session, changed_kg)
    finally:
        manager.remove_session(first_session)
        manager.remove_session(second_session)
        manager.cache_enabled = previous


def test_bundle_without_parcels_still_has_deterministic_source_key() -> None:
    bundle = VillageBundle(village_name="point-only")
    bundle.add(
        CurrentAnnotation(
            geometry={"type": "Point", "coordinates": [1.0, 2.0]},
            text="站",
            category="现状设施点",
            _raw={"source_feature_id": "source:point-only:1"},
        )
    )
    key = compute_layer1_cache_key("point-only", [], bundle=bundle)
    assert key is not None
