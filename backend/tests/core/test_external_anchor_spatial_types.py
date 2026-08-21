"""External anchor routing must preserve spatial meaning before KG build."""

from __future__ import annotations

from types import SimpleNamespace

from rdflib import Graph, Literal, RDF

from app.data.catalog.external_anchors import (
    ExternalAnchorPipeline,
    ExternalFeature,
    FeatureCategory,
)
from app.data.model.canonical import VillageBundle
from app.infrastructure.kg.builder.layer1_core import add_annotations
from app.infrastructure.kg.ontology import EntityTypes, PLN


def _feature(category: FeatureCategory, geometry: dict) -> ExternalFeature:
    return ExternalFeature(
        name="外部名称",
        name_norm="外部名称",
        lon=113.0,
        lat=23.0,
        coord_system="wgs84",
        category=category,
        source="fixture",
        raw={"name": "外部名称"},
        geometry=geometry,
    )


def test_external_line_categories_do_not_share_current_road_layer() -> None:
    bundle = VillageBundle(village_name="测试村")
    pipeline = ExternalAnchorPipeline()

    counts = pipeline._stage5_inject(
        bundle,
        [
            _feature(FeatureCategory.ROAD_LINE, {
                "type": "LineString",
                "coordinates": [[113.0, 23.0], [113.01, 23.01]],
            }),
            _feature(FeatureCategory.WATER_LINE, {
                "type": "LineString",
                "coordinates": [[113.0, 23.0], [113.02, 23.02]],
            }),
            _feature(FeatureCategory.ROAD_NAMED, {
                "type": "Point",
                "coordinates": [113.0, 23.0],
            }),
        ],
    )

    assert counts == {
        "external_roads": 1,
        "water_lines": 1,
        "annotations_current": 1,
    }
    assert not bundle.lines.get("roads_current")
    assert len(bundle.lines.get("external_roads")) == 1
    assert len(bundle.lines.get("water_lines")) == 1


def test_external_named_road_point_is_place_reference_not_road() -> None:
    bundle = VillageBundle(village_name="测试村")
    pipeline = ExternalAnchorPipeline()
    pipeline._stage5_inject(
        bundle,
        [_feature(FeatureCategory.ROAD_NAMED, {
            "type": "Point",
            "coordinates": [113.0, 23.0],
        })],
    )
    graph = Graph()

    add_annotations(SimpleNamespace(g=graph), bundle.points.get("annotations_current"))

    subject = next(graph.subjects(PLN.name, Literal("外部名称")))
    assert (subject, RDF.type, EntityTypes.PlaceRef) in graph
    assert (subject, RDF.type, EntityTypes.Road) not in graph
    assert graph.value(subject, PLN.gis_type_ref) == Literal("external_road_name")
    assert graph.value(subject, PLN.geometry_kind) == Literal("point")
