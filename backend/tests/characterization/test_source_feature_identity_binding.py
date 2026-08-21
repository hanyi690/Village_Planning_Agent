from unittest.mock import patch

from rdflib import Graph, Literal, RDF

from app.contracts.domain.l3_contracts import PlanningIntervention
from app.contracts.domain.planning_semantics import FacilityPlanningParameters
from app.data.ingestion.ingest import ingest_feature
from app.evidence.identity.source_feature_binding import (
    bind_existing_facility_source_features,
)
from app.infrastructure.kg.builder.layer1_core import (
    add_annotations,
    add_facilities_from_annotations,
)
from app.infrastructure.kg.ontology import EntityTypes, GeoPredicates, PLN


def _feature(label: str, index: int) -> dict:
    return {
        "type": "Feature",
        "properties": {"注记": label, "分类": "现状设施点"},
        "geometry": {"type": "Point", "coordinates": [116.0 + index / 1000, 24.8]},
    }


def _payload() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            *[_feature("站", index) for index in range(3)],
            *[_feature("祠", index + 3) for index in range(13)],
        ],
    }


def _assert_source_backed_facilities(graph: Graph) -> None:
    facilities = list(graph.subjects(RDF.type, EntityTypes.Facility))
    assert len(facilities) == 16
    source_ids = [str(graph.value(item, PLN.source_feature_id)) for item in facilities]
    assert all(item.startswith("http://village-planning.org/source-feature/v1/") for item in source_ids)
    assert len(set(source_ids)) == 16
    for item in facilities:
        assert graph.value(item, PLN.source_uri) == Literal(
            "file:///data/jintian/annotation.geojson"
        )
        assert graph.value(item, PLN.source_content_digest)
        assert graph.value(item, PLN.source_feature_index) is not None
        assert graph.value(item, PLN.source_geometry_digest)
        geometry_node = graph.value(item, GeoPredicates.hasGeometry)
        assert geometry_node is not None
        assert str(graph.value(geometry_node, GeoPredicates.asWKT)).startswith("POINT")


def _ingested_features():
    features, warnings = ingest_feature(
        _payload(),
        "current_annotation",
        source_uri="file:///data/jintian/annotation.geojson",
    )
    assert warnings == []
    assert len(features) == 16
    return features


def _accepted_semantic_decisions(features):
    return {
        str(feature._raw["source_feature_id"]): {
            "status": "accepted",
            "semantic_type": "公交站" if feature.text == "站" else "祠堂",
        }
        for feature in features
    }


def test_annotation_ingestion_assigns_stable_source_identity_groups():
    features = _ingested_features()
    raw = [feature._raw for feature in features]

    assert len({item["source_feature_id"] for item in raw}) == 16
    assert [item["source_feature_index"] for item in raw] == list(range(16))


def test_annotation_ingestion_hashes_source_snapshot_once():
    with patch(
        "app.data.ingestion.source_identity.source_content_digest",
        wraps=__import__(
            "app.data.ingestion.source_identity",
            fromlist=["source_content_digest"],
        ).source_content_digest,
    ) as digest:
        _ingested_features()

    assert digest.call_count == 1


def test_add_facilities_from_annotations_preserves_source_ids_and_point_wkt():
    graph = Graph()
    add_facilities_from_annotations(type("KG", (), {"g": graph})(), _ingested_features())

    _assert_source_backed_facilities(graph)


def test_add_annotations_preserves_source_ids_and_point_wkt():
    graph = Graph()
    add_annotations(type("KG", (), {"g": graph})(), _ingested_features())

    _assert_source_backed_facilities(graph)


def test_typed_existing_groups_bind_exactly_three_stations_and_thirteen_halls():
    features = _ingested_features()
    stations = features[:3]
    halls = features[3:]

    station_target = PlanningIntervention(
        intervention_id="pub_fac_011",
        name="升级改造公交站亭",
        category="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        intervention_action="upgrade",
        scale="3处",
        spatial_requirements={"source_collection_key": "current_facility"},
        facility_parameters=FacilityPlanningParameters(
            facility_type="公交站亭",
            action="preserve",
            capacity=3,
        ),
    )
    hall_target = PlanningIntervention(
        intervention_id="CL-FAC-001",
        name="祠堂修缮加固",
        category="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        intervention_action="preserve",
        scale="13处",
        spatial_requirements={"source_collection_key": "current_facility"},
        facility_parameters=FacilityPlanningParameters(
            facility_type="文化展示设施",
            action="preserve",
            capacity=13,
        ),
    )

    hall_ids = bind_existing_facility_source_features(
        hall_target,
        halls,
        _accepted_semantic_decisions(halls),
    )

    station_ids = bind_existing_facility_source_features(
        station_target,
        stations,
        _accepted_semantic_decisions(stations),
    )

    assert len(station_ids) == 3
    assert len(hall_ids) == 13
    assert len(set(station_ids + hall_ids)) == 16


def test_collection_binding_does_not_use_quantity_as_identity_or_road_count():
    features = _ingested_features()
    bad_station_target = PlanningIntervention(
        intervention_id="bad-stations",
        name="升级公交站",
        category="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        intervention_action="upgrade",
        spatial_requirements={"source_collection_key": "current_facility"},
        facility_parameters=FacilityPlanningParameters(
            facility_type="公交站",
            action="preserve",
            capacity=4,
        ),
    )
    road_target = PlanningIntervention(
        intervention_id="road-count-mismatch",
        name="村道硬化",
        category="road",
        asset_kind="road",
        execution_mode="spatial",
        expected_output_kind="line",
        intervention_action="upgrade",
        road_parameters={"action": "upgrade", "length_m": 1000},
    )

    assert bind_existing_facility_source_features(bad_station_target, features[:3]) == []
    assert len(bind_existing_facility_source_features(
        bad_station_target,
        features[:3],
        _accepted_semantic_decisions(features[:3]),
    )) == 3
    assert bind_existing_facility_source_features(road_target, features) == []
