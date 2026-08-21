"""Regression tests for source-backed KG business feature boundaries."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from rdflib import Graph, Literal, RDF

from app.data.model.spatial_types import (
    AdminBoundaryLine,
    ContourLine,
    CurrentRoad,
    ElevationPoint,
)
from app.infrastructure.kg.builder.layer1_core import add_roads
from app.infrastructure.kg.builder.layer1_extended import (
    add_buildings,
    add_boundaries,
    add_dem_raster,
    add_natural_resource_zones,
    add_protection_polygons,
    add_terrain_entities,
)
from app.infrastructure.kg.queries.cognition import (
    _build_context_block,
    get_village_cognition,
)
from app.infrastructure.kg.queries.semantic import get_village_semantic_summary
from app.infrastructure.kg.ontology import (
    BusinessFeatureSelector,
    EntityTypes,
    GeoPredicates,
    PLN,
    select_business_features,
)


def _raw(source_id: str, dataset: str = "roads.geojson") -> dict[str, str]:
    return {
        "source_feature_id": source_id,
        "source_uri": dataset,
        "source_dataset": dataset,
        "source_snapshot_ref": "snapshot:test-v1",
        "source_content_digest": "sha256:test-v1",
    }


def _line_feature(feature_type: type, source_id: str):
    return feature_type(
        geometry={
            "type": "LineString",
            "coordinates": [[113.0, 23.0], [113.01, 23.01]],
        },
        BSM=source_id,
        _raw=_raw(source_id),
    )


def _point_feature(source_id: str):
    return ElevationPoint(
        geometry={"type": "Point", "coordinates": [113.0, 23.0]},
        BSM=source_id,
        _raw=_raw(source_id, "elevation.geojson"),
    )


def _polygon_feature(source_id: str, dataset: str):
    return SimpleNamespace(
        geometry={
            "type": "Polygon",
            "coordinates": [[[113.0, 23.0], [113.01, 23.0], [113.01, 23.01], [113.0, 23.0]]],
        },
        bsm=source_id,
        ysdm="",
        _raw=_raw(source_id, dataset),
    )


def test_current_road_selector_requires_complete_gis_identity() -> None:
    graph = Graph()
    roads = [_line_feature(CurrentRoad, "road-1")]
    add_roads(SimpleNamespace(g=graph), roads, gtype_ref="current_road", entry=None, ctx=None)

    polluted_boundary = PLN.polluted_boundary
    graph.add((polluted_boundary, RDF.type, EntityTypes.Road))
    graph.add((polluted_boundary, PLN.source_feature_id, Literal("boundary-1")))
    graph.add((polluted_boundary, PLN.source_uri, Literal("boundary.geojson")))
    graph.add((polluted_boundary, PLN.source_content_digest, Literal("sha256:boundary")))

    selected = select_business_features(graph, BusinessFeatureSelector.current_road())

    assert len(selected) == 1
    assert graph.value(selected[0], PLN.source_feature_id) == Literal("road-1")
    assert polluted_boundary not in selected


@pytest.mark.parametrize(
    "missing_dimension",
    [
        "gis_type_ref",
        "semantic_group",
        "geometry_kind",
        "source_feature_id",
        "source_dataset",
        "source_snapshot",
    ],
)
def test_current_road_selector_rejects_missing_identity_dimension(missing_dimension: str) -> None:
    graph = Graph()
    subject = PLN.complete_road
    graph.add((subject, PLN.gis_type_ref, Literal("road")))
    graph.add((subject, PLN.semantic_group, Literal("transport")))
    graph.add((subject, PLN.geometry_kind, Literal("line")))
    graph.add((subject, PLN.source_feature_id, Literal("road-complete")))
    graph.add((subject, PLN.source_dataset, Literal("roads.geojson")))
    graph.add((subject, PLN.source_uri, Literal("roads.geojson")))
    graph.add((subject, PLN.source_snapshot_ref, Literal("snapshot:test-v1")))
    graph.add((subject, PLN.source_content_digest, Literal("sha256:test-v1")))

    if missing_dimension == "gis_type_ref":
        graph.remove((subject, PLN.gis_type_ref, None))
    elif missing_dimension == "semantic_group":
        graph.remove((subject, PLN.semantic_group, None))
    elif missing_dimension == "geometry_kind":
        graph.remove((subject, PLN.geometry_kind, None))
    elif missing_dimension == "source_feature_id":
        graph.remove((subject, PLN.source_feature_id, None))
    elif missing_dimension == "source_dataset":
        graph.remove((subject, PLN.source_dataset, None))
        graph.remove((subject, PLN.source_uri, None))
    elif missing_dimension == "source_snapshot":
        graph.remove((subject, PLN.source_snapshot_ref, None))
        graph.remove((subject, PLN.source_content_digest, None))

    assert subject not in select_business_features(graph, BusinessFeatureSelector.current_road())


@pytest.mark.parametrize(
    "predicate_group",
    [
        (PLN.source_feature_id,),
        (PLN.source_dataset, PLN.source_uri),
        (PLN.source_snapshot_ref, PLN.source_content_digest),
    ],
)
def test_current_road_selector_rejects_blank_source_identity_values(predicate_group) -> None:
    graph = Graph()
    subject = PLN.blank_identity_road
    graph.add((subject, PLN.gis_type_ref, Literal("road")))
    graph.add((subject, PLN.semantic_group, Literal("transport")))
    graph.add((subject, PLN.geometry_kind, Literal("line")))
    graph.add((subject, PLN.source_feature_id, Literal("road-complete")))
    graph.add((subject, PLN.source_dataset, Literal("roads.geojson")))
    graph.add((subject, PLN.source_uri, Literal("roads.geojson")))
    graph.add((subject, PLN.source_snapshot_ref, Literal("snapshot:test-v1")))
    graph.add((subject, PLN.source_content_digest, Literal("sha256:test-v1")))

    for predicate in predicate_group:
        graph.remove((subject, predicate, None))
        graph.add((subject, predicate, Literal("  ")))

    assert subject not in select_business_features(graph, BusinessFeatureSelector.current_road())


def test_business_selector_has_no_source_identity_bypass_and_facility_selector() -> None:
    selector = BusinessFeatureSelector.current_road()
    assert not hasattr(selector, "require_source_provenance")
    with pytest.raises(TypeError):
        BusinessFeatureSelector("road", "transport", "line", False)

    graph = Graph()
    facility = PLN.current_facility
    graph.add((facility, PLN.gis_type_ref, Literal("current_facility")))
    graph.add((facility, PLN.semantic_group, Literal("facility")))
    graph.add((facility, PLN.geometry_kind, Literal("point")))
    graph.add((facility, PLN.source_feature_id, Literal("facility-1")))
    graph.add((facility, PLN.source_uri, Literal("facilities.geojson")))
    graph.add((facility, PLN.source_snapshot_ref, Literal("snapshot:test-v1")))

    assert select_business_features(graph, BusinessFeatureSelector.current_facility()) == [facility]


def _add_count_fixture(graph: Graph) -> None:
    for subject, rdf_type, gis_type, group, kind, source_id in (
        (PLN.counted_road, EntityTypes.Road, "road", "transport", "line", "road-1"),
        (PLN.counted_facility, EntityTypes.Facility, "current_facility", "facility", "point", "facility-1"),
        (PLN.polluted_admin_line, EntityTypes.AdministrativeBoundary, "admin_boundary_line", "admin", "line", "admin-1"),
        (PLN.polluted_contour, EntityTypes.ContourLine, "contour_line", "terrain", "line", "contour-1"),
        (PLN.polluted_elevation, EntityTypes.Facility, "elevation_point", "terrain", "point", "elevation-1"),
    ):
        graph.add((subject, RDF.type, rdf_type))
        graph.add((subject, PLN.gis_type_ref, Literal(gis_type)))
        graph.add((subject, PLN.semantic_group, Literal(group)))
        graph.add((subject, PLN.geometry_kind, Literal(kind)))
        graph.add((subject, PLN.source_feature_id, Literal(source_id)))
        graph.add((subject, PLN.source_dataset, Literal("fixture.geojson")))
        graph.add((subject, PLN.source_snapshot_ref, Literal("snapshot:test-v1")))


def test_cognition_and_semantic_counts_exclude_polluted_road_and_facility_types() -> None:
    graph = Graph()
    _add_count_fixture(graph)
    kg = SimpleNamespace(g=graph)

    cognition = _build_context_block(kg, "测试村")
    semantic = get_village_semantic_summary(kg)

    assert cognition["entity_counts"]["Road"] == 1
    assert cognition["entity_counts"]["Facility"] == 1
    assert "1条道路" in cognition["overview"]
    assert "1个设施" in cognition["overview"]
    assert semantic["entity_counts"]["Road"] == 1
    assert semantic["entity_counts"]["Facility"] == 1

    typed = get_village_cognition(kg, "测试村").structured["fact_records"]
    assert typed
    road_fact = next(item for item in typed if item["source_collection_key"] == "current_road")
    assert road_fact["value"] == 1
    assert road_fact["counting_basis"] == "source_feature"
    assert road_fact["source_snapshot_ref"] == "snapshot:test-v1"
    assert road_fact["source_feature_ids"] == ["road-1"]
    assert all("polluted" not in item["source_feature_ids"] for item in typed)


def test_extended_line_and_point_features_keep_source_provenance_and_wkt() -> None:
    graph = Graph()
    boundary = _line_feature(AdminBoundaryLine, "boundary-1")
    contour = _line_feature(ContourLine, "contour-1")
    elevation = _point_feature("elevation-1")

    add_boundaries(
        SimpleNamespace(g=graph),
        {"admin_areas": [], "planning_scope": []},
        {"admin_boundaries": [boundary]},
    )
    add_terrain_entities(
        SimpleNamespace(g=graph),
        {"contour_lines": [contour]},
        {"elevation_points": [elevation]},
    )

    for source_id in ("boundary-1", "contour-1", "elevation-1"):
        subject = next(graph.subjects(PLN.source_feature_id, Literal(source_id)))
        assert graph.value(subject, PLN.source_dataset) is not None
        assert graph.value(subject, PLN.source_snapshot_ref) == Literal("snapshot:test-v1")
        geometry = graph.value(subject, GeoPredicates.hasGeometry)
        assert geometry is not None
        assert graph.value(geometry, GeoPredicates.asWKT) is not None

    boundary_subject = next(graph.subjects(PLN.source_feature_id, Literal("boundary-1")))
    contour_subject = next(graph.subjects(PLN.source_feature_id, Literal("contour-1")))
    elevation_subject = next(graph.subjects(PLN.source_feature_id, Literal("elevation-1")))
    assert (boundary_subject, RDF.type, EntityTypes.AdministrativeBoundary) in graph
    assert (contour_subject, RDF.type, EntityTypes.ContourLine) in graph
    assert (boundary_subject, RDF.type, EntityTypes.Road) not in graph
    assert (contour_subject, RDF.type, EntityTypes.Road) not in graph
    assert (elevation_subject, RDF.type, EntityTypes.Facility) in graph
    assert boundary_subject not in select_business_features(graph, BusinessFeatureSelector.current_road())
    assert contour_subject not in select_business_features(graph, BusinessFeatureSelector.current_road())
    assert elevation_subject not in select_business_features(graph, BusinessFeatureSelector.current_road())


def test_current_road_builder_rejects_non_line_source_geometry() -> None:
    graph = Graph()
    valid = _line_feature(CurrentRoad, "road-valid")
    invalid = SimpleNamespace(
        geometry={"type": "Point", "coordinates": [113.0, 23.0]},
        bsm="road-point",
        ysdm="",
        _raw=_raw("road-point"),
    )

    report = add_roads(
        SimpleNamespace(g=graph),
        [valid, invalid],
        gtype_ref="current_road",
        entry=None,
        ctx=None,
    )

    assert report["count"] == 1
    assert report["skipped_invalid_geometry"] == 1
    assert not list(graph.subjects(PLN.source_feature_id, Literal("road-point")))


def test_all_extended_source_features_keep_provenance_and_geometry_kind_wkt() -> None:
    graph = Graph()
    protection = _polygon_feature("protection-1", "protection.geojson")
    building = SimpleNamespace(
        geometry={"type": "Point", "coordinates": [113.0, 23.0]},
        bsm="building-1",
        ysdm="",
        _raw=_raw("building-1", "building.geojson"),
    )
    admin_area = _polygon_feature("admin-area-1", "admin.geojson")
    planning_scope = _polygon_feature("planning-scope-1", "scope.geojson")
    natural_resource = _polygon_feature("soil-1", "soil.geojson")

    add_protection_polygons(
        SimpleNamespace(g=graph),
        {"farmland_protection": [protection]},
    )
    add_buildings(
        SimpleNamespace(g=graph),
        [building],
        gtype_ref="current_building",
        entry=None,
        ctx=None,
    )
    add_boundaries(
        SimpleNamespace(g=graph),
        {"admin_areas": [admin_area], "planning_scope": [planning_scope]},
        {"admin_boundaries": []},
    )
    add_natural_resource_zones(
        SimpleNamespace(g=graph),
        {"soil_types": [natural_resource]},
    )

    for source_id in (
        "protection-1",
        "building-1",
        "admin-area-1",
        "planning-scope-1",
        "soil-1",
    ):
        subject = next(graph.subjects(PLN.source_feature_id, Literal(source_id)))
        assert graph.value(subject, PLN.source_dataset) is not None
        assert graph.value(subject, PLN.source_snapshot_ref) == Literal("snapshot:test-v1")
        geometry = graph.value(subject, GeoPredicates.hasGeometry)
        assert geometry is not None
        assert graph.value(geometry, GeoPredicates.asWKT) is not None


def test_dem_keeps_raster_identity_without_fabricated_source_wkt() -> None:
    graph = Graph()
    dem = SimpleNamespace(
        path="dem.tif",
        crs="EPSG:4326",
        bounds=(113.0, 23.0, 113.01, 23.01),
        width=10,
        height=10,
        resolution=1.0,
    )

    add_dem_raster(SimpleNamespace(g=graph), [dem], gtype_ref="dem", entry=None, ctx=None)

    subject = next(graph.subjects(PLN.gis_type_ref, Literal("dem")))
    assert graph.value(subject, GeoPredicates.hasGeometry) is None
