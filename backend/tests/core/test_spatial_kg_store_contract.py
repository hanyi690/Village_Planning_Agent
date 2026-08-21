from rdflib import Graph, Literal, RDF, URIRef
from types import SimpleNamespace

from app.infrastructure.kg.ontology import EntityTypes, PLN, Relations
from app.infrastructure.kg.spatial_store import (
    POSTGIS_KG_SCHEMA_SQL,
    RdfSpatialKGIndex,
)
from app.infrastructure.kg.builder.base import PlanningKG
from app.infrastructure.kg.builder import KGBuilder
from app.infrastructure.kg.queries.cognition import get_village_cognition
from app.data.model.canonical import VillageBundle, VillageMetadata
from app.data.model.spatial_types import CurrentAnnotation
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex


def test_rdf_spatial_index_supports_identity_and_relation_lookup() -> None:
    graph = Graph()
    facility = URIRef("http://example.test/facility-1")
    village = URIRef("http://example.test/village-1")
    graph.add((facility, RDF.type, EntityTypes.Facility))
    graph.add((facility, PLN.name, Literal("祠堂")))
    graph.add((facility, PLN.bsm, Literal("441426211000000001")))
    graph.add((facility, PLN.source_feature_id, Literal("source:facility:1")))
    graph.add((village, RDF.type, EntityTypes.ResidentialCluster))
    graph.add((village, PLN.name, Literal("社前村")))
    graph.add((facility, Relations.serves, village))

    index = RdfSpatialKGIndex()
    index.rebuild(graph)

    by_bsm = index.find_entities(feature_bsm="441426211000000001")
    assert [item.entity_ref for item in by_bsm] == [str(facility)]
    assert index.find_entities(name="祠堂")[0].source_feature_id == "source:facility:1"
    relations = index.find_relations(subject_ref=str(facility), predicate=str(Relations.serves))
    assert len(relations) == 1
    assert relations[0].object_ref == str(village)


def test_postgis_schema_keeps_entities_and_topology_in_one_snapshot_store() -> None:
    schema = "\n".join(POSTGIS_KG_SCHEMA_SQL)
    assert "CREATE TABLE IF NOT EXISTS kg_entities" in schema
    assert "CREATE TABLE IF NOT EXISTS kg_relations" in schema
    assert "USING GIST (geometry)" in schema
    assert "snapshot_digest" in schema


def test_generated_bundle_facility_is_a_queryable_kg_business_feature() -> None:
    bundle = VillageBundle(
        village_name="金田村",
        metadata=VillageMetadata(adcode_12="441426110000"),
    )
    bundle.add(
        CurrentAnnotation(
            geometry={"type": "Point", "coordinates": [116.0, 24.0]},
            text="祠堂",
            category="现状设施点",
        )
    )

    kg = KGBuilder.build("金田村", bundle)
    facilities = list(kg.g.subjects(RDF.type, EntityTypes.Facility))
    assert len(facilities) == 1
    facility = facilities[0]
    assert str(kg.g.value(facility, PLN.bsm)) == "44142611000000000001"
    assert str(kg.g.value(facility, PLN.source_feature_id)).startswith(
        "bundle:current_facility:"
    )
    assert str(kg.g.value(facility, PLN.source_snapshot_ref)) == bundle.spatial_snapshot_digest()

    cognition = get_village_cognition(kg, "金田村")
    assert cognition.semantic["context_block"]["entity_counts"]["Facility"] == 1
    assert kg.find_entities(feature_bsm="44142611000000000001")[0].source_layer == "current_facility"


def test_turtle_restore_rebuilds_the_index_used_by_evidence_retrieval() -> None:
    bundle = VillageBundle(
        village_name="金田村",
        metadata=VillageMetadata(adcode_12="441426110000"),
    )
    bundle.add(
        CurrentAnnotation(
            geometry={"type": "Point", "coordinates": [116.0, 24.0]},
            text="祠堂",
            category="现状设施点",
        )
    )

    source = KGBuilder.build("金田村", bundle)
    restored = PlanningKG.from_turtle(
        source.to_turtle(),
        village_name="金田村",
    )

    matches = restored.find_entities(name="祠堂")
    assert len(matches) == 1
    assert matches[0].source_layer == "current_facility"


def test_facility_entry_keeps_feature_bsm_separate_from_related_parcels() -> None:
    point = SimpleNamespace(
        text="祠堂",
        category="现状设施点",
        layer_type="facilities_current",
        bsm="441426211000000123",
        geometry={"type": "Point", "coordinates": [116.0, 24.0]},
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(
            get=lambda key: [point] if key == "facilities_current" else []
        )
    )
    context = SimpleNamespace(
        workspace=workspace,
        location_facts=[],
        gazetteer=None,
        kg=None,
        version=1,
        kg_version=1,
        session_id="test",
        current_parcels=lambda: [],
    )
    index = PlaceEvidenceIndex.build(context)
    result = index.resolve_mention("祠堂", role="facility")

    assert result.status == "resolved"
    assert result.candidates[0].feature_bsm == "441426211000000123"
    assert result.candidates[0].source_layer == "facilities_current"
    assert result.candidates[0].related_parcel_bsms == []


def test_planning_kg_can_switch_storage_without_changing_topology_api() -> None:
    kg = PlanningKG("社前村")
    local = kg.spatial_index

    class StubStore:
        def find_entities(self, **filters):
            return [filters]

        def find_relations(self, **filters):
            return [filters]

    store = StubStore()
    kg.attach_spatial_store(store)

    assert kg.spatial_storage_backend == "StubStore"
    assert kg.find_entities(name="祠堂") == [{"name": "祠堂"}]
    assert kg.find_relations(predicate="near") == [{"predicate": "near"}]

    kg.detach_spatial_store()
    assert kg.spatial_store is local
    assert kg.spatial_storage_backend == "rdf_memory"
