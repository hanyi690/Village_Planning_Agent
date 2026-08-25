from types import SimpleNamespace

from rdflib import Graph, Literal, RDF, URIRef

from app.contracts.domain.l3_contracts import PlanningIntervention
from app.contracts.spatial.spatial_reference_contracts import (
    CandidateSet,
    GeometryRef,
    ResolvedSpatialRef,
    SpatialReferenceSpec,
)
from app.domain.ground.aggregate import build_candidate_sites
from app.data.ingestion.compiler.spec_mapper import map_intervention_to_spec
from app.infrastructure.kg.ontology import EntityTypes, GeoPredicates, PLN
from app.infrastructure.kg.queries.spatial_ref import resolve_candidates
from app.spatial.grounding.resolver import SpatialResolver


def _context(*, port=None):
    return SimpleNamespace(
        workspace=SimpleNamespace(),
        kg=SimpleNamespace(),
        gazetteer=None,
        evidence_graph=None,
        constraint_index=None,
        ports=SimpleNamespace(spatial_query=port),
        current_parcels=lambda: [
            SimpleNamespace(
                bsm="P-1",
                area_sqm=10000,
                geometry={
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
            ),
            SimpleNamespace(
                bsm="P-2",
                area_sqm=10000,
                geometry={
                    "type": "Polygon",
                    "coordinates": [[[2, 0], [3, 0], [3, 1], [2, 1], [2, 0]]],
                },
            ),
        ],
    )


def test_multiple_source_points_remain_independent_executable_candidates():
    resolved = ResolvedSpatialRef(
        final_bsms=["P-1", "P-2"],
        reference_geometries=[
            GeometryRef(
                wkt="POINT (0.25 0.25)",
                source_ref="kg:facility:1",
                source_bsms=["P-1"],
                feature_kind="Facility",
            ),
            GeometryRef(
                wkt="POINT (2.25 0.25)",
                source_ref="kg:facility:2",
                source_bsms=["P-2"],
                feature_kind="Facility",
            ),
        ],
        confidence=0.95,
        provenance={"path": "kg:source_features"},
    )

    candidates = build_candidate_sites(
        SpatialReferenceSpec(type="directional", target_id="shelter-set"),
        resolved,
        0,
        _context(),
        target_kind="facility",
        expected_output_kind="point",
    )

    assert len(candidates) == 2
    assert [item.geometry.kind for item in candidates] == ["point", "point"]
    assert all(item.geometry.granularity == "exact_feature" for item in candidates)
    assert all(item.geometry.role == "execution_geometry" for item in candidates)
    assert all(item.geometry.is_executable for item in candidates)
    assert [item.geometry.source_ref for item in candidates] == [
        "kg:facility:1",
        "kg:facility:2",
    ]
    assert [item.geometry.source_bsms for item in candidates] == [["P-1"], ["P-2"]]
    assert len({item.candidate_id for item in candidates}) == 2
    assert all(item.geometry.generation_operation == "grounded_source_feature" for item in candidates)


def test_multiple_source_lines_are_not_unioned_into_one_line_or_polygon():
    resolved = ResolvedSpatialRef(
        reference_geometries=[
            GeometryRef(wkt="LINESTRING (0 0, 1 1)", source_ref="kg:road:1"),
            GeometryRef(wkt="LINESTRING (2 0, 3 1)", source_ref="kg:road:2"),
        ],
        confidence=0.95,
        provenance={"path": "kg:source_features"},
    )

    candidates = build_candidate_sites(
        SpatialReferenceSpec(type="directional", target_id="road-set"),
        resolved,
        0,
        _context(),
        target_kind="road",
        expected_output_kind="line",
    )

    assert len(candidates) == 2
    assert [item.geometry.kind for item in candidates] == ["line", "line"]
    assert [item.geometry.wkt for item in candidates] == [
        "LINESTRING (0 0, 1 1)",
        "LINESTRING (2 0, 3 1)",
    ]
    assert all(item.geometry.role == "execution_geometry" for item in candidates)
    assert all("unary_union" not in item.geometry.generation_operation for item in candidates)


def test_resolver_preserves_source_geometry_list_and_does_not_pick_one():
    class _Port:
        def resolve_candidates(self, run_id, spec):
            return CandidateSet(
                ref_bsms=["P-1", "P-2"],
                ref_geometries=[
                    GeometryRef(wkt="POINT (0.25 0.25)", source_ref="kg:facility:1"),
                    GeometryRef(wkt="POINT (2.25 0.25)", source_ref="kg:facility:2"),
                ],
            )

    spec = SpatialReferenceSpec(type="directional", target_id="shelter-set")
    resolved = SpatialResolver(_context(port=_Port())).resolve_spec(spec)

    assert resolved.final_bsms == ["P-1", "P-2"]
    assert resolved.reference_geometry_wkt is None
    assert [item.source_ref for item in resolved.reference_geometries] == [
        "kg:facility:1",
        "kg:facility:2",
    ]
    assert resolved.provenance["source_geometry_count"] == 2


def test_kg_multi_feature_mode_requires_explicit_source_backed_opt_in():
    graph = Graph()
    entities = []
    for number, wkt in ((1, "POINT (0 0)"), (2, "POINT (1 1)")):
        entity = URIRef(f"http://example.test/facility/{number}")
        geometry = URIRef(f"http://example.test/geometry/{number}")
        graph.add((entity, RDF.type, EntityTypes.Facility))
        graph.add((entity, PLN.name, Literal("避难点")))
        graph.add((entity, PLN.bsm, Literal(f"P-{number}")))
        graph.add((entity, GeoPredicates.hasGeometry, geometry))
        graph.add((geometry, GeoPredicates.asWKT, Literal(wkt)))
        entities.append(entity)
    kg = SimpleNamespace(g=graph)

    multi_spec = SpatialReferenceSpec(
        type="directional",
        reference={
            "kind": "entity_type",
            "filter": {
                "rdf_type": "Facility",
                "label_contains": "避难点",
                "allow_multiple_exact": True,
            },
        },
        target_id="shelter-set",
    )
    result = resolve_candidates(kg, multi_spec)

    assert [item.source_ref for item in result.ref_geometries] == [str(item) for item in entities]
    assert [item.source_bsms for item in result.ref_geometries] == [["P-1"], ["P-2"]]

    generic_spec = multi_spec.model_copy(
        deep=True,
    )
    generic_spec.reference.filter.pop("allow_multiple_exact", None)
    generic_result = resolve_candidates(kg, generic_spec)
    assert generic_result.ref_geometries == []


def test_kg_explicit_source_feature_ids_are_resolved_without_label_guessing():
    graph = Graph()
    entity = URIRef("http://example.test/road/one")
    geometry = URIRef("http://example.test/geometry/road-one")
    graph.add((entity, RDF.type, EntityTypes.Road))
    graph.add((entity, PLN.name, Literal("道路甲")))
    graph.add((entity, GeoPredicates.hasGeometry, geometry))
    graph.add((geometry, GeoPredicates.asWKT, Literal("LINESTRING (0 0, 1 1)")))
    kg = SimpleNamespace(g=graph)

    spec = SpatialReferenceSpec(
        type="directional",
        reference={
            "kind": "entity_type",
            "filter": {
                "rdf_type": "Road",
                "source_feature_ids": [str(entity)],
                "allow_multiple_exact": True,
            },
        },
        target_id="road-one",
    )
    result = resolve_candidates(kg, spec)

    assert len(result.ref_geometries) == 1
    assert result.ref_geometries[0].wkt == "LINESTRING (0 0, 1 1)"


def test_target_projection_passes_only_explicit_source_feature_ids():
    intervention = PlanningIntervention(
        intervention_id="facility-existing-set",
        name="现状设施维护",
        category="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        intervention_action="repair",
        # The location text is deliberately generic and must not participate
        # in the exact-feature spec once explicit source IDs are present.
        spatial_requirements={
            "location": "全村",
            "source_feature_ids": [
                "http://example.test/facility/1",
                "http://example.test/facility/2",
            ],
        },
    )

    spec = map_intervention_to_spec(intervention)

    assert spec is not None
    assert spec.type == "directional"
    assert spec.reference is not None
    assert spec.reference.filter == {
        "rdf_type": "Facility",
        "source_feature_ids": [
            "http://example.test/facility/1",
            "http://example.test/facility/2",
        ],
        "allow_multiple_exact": True,
    }
    assert "label_contains" not in spec.reference.filter


def test_source_feature_ids_do_not_promote_new_asset_or_malformed_values():
    base = {
        "location": "全村",
        "source_feature_ids": ["http://example.test/facility/1"],
    }
    new_intervention = PlanningIntervention(
        intervention_id="facility-new",
        name="新设施",
        category="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        intervention_action="new",
        spatial_requirements=base,
    )
    malformed_intervention = PlanningIntervention(
        intervention_id="facility-bad-source-ids",
        name="现状设施维护",
        category="facility",
        execution_mode="spatial",
        expected_output_kind="point",
        intervention_action="repair",
        spatial_requirements={"location": "全村", "source_feature_ids": "not-a-list"},
    )

    new_spec = map_intervention_to_spec(new_intervention)
    malformed_spec = map_intervention_to_spec(malformed_intervention)

    assert new_spec is not None
    assert new_spec.type != "directional"
    assert malformed_spec is not None
    assert malformed_spec.type != "directional"
