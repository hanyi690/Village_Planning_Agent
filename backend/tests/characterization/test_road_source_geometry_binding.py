from types import SimpleNamespace

from rdflib import Graph, RDF

from app.contracts.domain.l3_contracts import PlanningIntervention
from app.contracts.domain.planning_semantics import RoadPlanningParameters
from app.data.ingestion.compiler.spec_mapper import map_intervention_to_spec
from app.data.ingestion.ingest import ingest_feature
from app.domain.program.target_projection.compile import _to_road_target
from app.evidence.identity.source_feature_binding import (
    bind_existing_road_source_features,
)
from app.infrastructure.kg.builder.layer1_core import add_roads
from app.infrastructure.kg.ontology import EntityTypes, GeoPredicates, PLN


def _road(index: int) -> dict:
    return {
        "type": "Feature",
        "properties": {"Shape_Length": 100.0 + index},
        "geometry": {
            "type": "MultiLineString",
            "coordinates": [[[116.0 + index / 1000, 24.8], [116.001 + index / 1000, 24.801]]],
        },
    }


def _roads(count: int = 3) -> list[object]:
    features, warnings = ingest_feature(
        {"type": "FeatureCollection", "features": [_road(i) for i in range(count)]},
        "current_road",
        source_uri="file:///data/jintian/current/road.geojson",
    )
    assert warnings == []
    return features


def _existing_road_target(*, requirements=None, scale="") -> PlanningIntervention:
    return PlanningIntervention(
        intervention_id="road-existing",
        name="现状道路提升",
        category="road",
        asset_kind="road",
        execution_mode="spatial",
        expected_output_kind="line",
        intervention_action="upgrade",
        scale=scale,
        spatial_requirements=requirements or {},
        road_parameters=RoadPlanningParameters(
            action="upgrade",
            length_m=100.0,
        ),
    )


def test_current_road_builder_persists_source_identity_and_line_wkt():
    features = _roads(2)
    graph = Graph()
    add_roads(SimpleNamespace(g=graph), features, gtype_ref="current_road", entry=None, ctx=None)

    roads = list(graph.subjects(RDF.type, EntityTypes.Road))
    assert len(roads) == 2
    assert len({str(graph.value(road, PLN.source_feature_id)) for road in roads}) == 2
    for road in roads:
        source_id = str(graph.value(road, PLN.source_feature_id))
        assert source_id.startswith("http://village-planning.org/source-feature/v1/")
        geometry_node = graph.value(road, GeoPredicates.hasGeometry)
        assert geometry_node is not None
        assert str(graph.value(geometry_node, GeoPredicates.asWKT)).startswith("MULTILINESTRING")


def test_explicit_road_source_ids_promote_independent_line_specs():
    features = _roads(3)
    source_ids = [item._raw["source_feature_id"] for item in features[:2]]
    target = _existing_road_target(
        requirements={"existing_road_feature_ids": source_ids},
    )

    spec = map_intervention_to_spec(target, source_features={"road": features})

    assert spec is not None
    assert spec.type == "directional"
    assert spec.reference.filter["rdf_type"] == "Road"
    assert spec.reference.filter["source_feature_ids"] == source_ids


def test_road_count_binds_only_when_declared_count_matches_source_lines():
    features = _roads(3)
    target = _existing_road_target(
        requirements={"source_feature_count": 3},
    )

    ids = bind_existing_road_source_features(target, features)
    spec = map_intervention_to_spec(target, source_features={"road": features})

    assert ids == [item._raw["source_feature_id"] for item in features]
    assert spec is not None
    assert spec.type == "directional"
    assert spec.reference.filter["source_feature_ids"] == ids


def test_road_count_mismatch_stays_candidate_only_not_exact_line():
    features = _roads(3)
    target = _existing_road_target(scale="275条道路")

    assert bind_existing_road_source_features(target, features) == []
    spec = map_intervention_to_spec(target, source_features={"road": features})

    assert spec is not None
    assert spec.type != "directional"


def test_foreign_explicit_source_id_stays_candidate_only_when_source_is_available():
    features = _roads(2)
    target = _existing_road_target(
        requirements={"source_feature_ids": ["https://foreign.example/road/1"]},
    )

    spec = map_intervention_to_spec(target, source_features={"road": features})

    assert spec is not None
    assert spec.type != "directional"


def test_existing_road_feature_id_alias_promotes_exact_line_spec():
    features = _roads(2)
    source_id = features[0]._raw["source_feature_id"]
    target = _existing_road_target(
        requirements={"existing_road_feature_ids": [source_id]},
    )

    spec = map_intervention_to_spec(target, source_features={"road": features})

    assert spec is not None
    assert spec.type == "directional"
    assert spec.reference.filter["source_feature_ids"] == [source_id]


def test_typed_upgrade_action_can_bind_when_intervention_action_is_legacy_new():
    features = _roads(2)
    source_id = features[0]._raw["source_feature_id"]
    target = _existing_road_target(
        requirements={"source_feature_ids": [source_id]},
    ).model_copy(update={"intervention_action": "new"})

    spec = map_intervention_to_spec(target, source_features={"road": features})

    assert spec is not None
    assert spec.type == "directional"


def test_target_projection_preserves_existing_road_feature_id_alias():
    features = _roads(2)
    source_id = features[0]._raw["source_feature_id"]
    target = _existing_road_target(
        requirements={"existing_road_feature_ids": [source_id]},
    )

    projected = _to_road_target(target)

    assert projected.existing_road_feature_ids == [source_id]


def test_new_corridor_never_binds_current_road_lines_without_existing_action():
    features = _roads(3)
    target = PlanningIntervention(
        intervention_id="road-new",
        name="新建连接道路",
        category="road",
        asset_kind="road",
        execution_mode="spatial",
        expected_output_kind="line",
        intervention_action="new",
        spatial_requirements={"source_feature_count": 3},
        road_parameters=RoadPlanningParameters(action="new", length_m=100.0),
    )

    assert bind_existing_road_source_features(target, features) == []
