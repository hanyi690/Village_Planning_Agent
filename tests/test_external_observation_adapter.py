from rdflib import Graph, RDF

from app.contracts.evidence.external_observation_contracts import (
    ExternalObservation,
    ExternalObservationSnapshot,
)
from app.infrastructure.kg.adapters.external_observation_adapter import (
    project_external_observations,
)
from app.infrastructure.kg.ontology import PLN


def test_adapter_keeps_support_cluster_separate_from_world_entity_types():
    snapshot = ExternalObservationSnapshot(
        snapshot_id="snap-kg",
        observations=[
            ExternalObservation(
                observation_id="a-1",
                provider="amap",
                stage="l1",
                observed_name="村道",
                observed_type="road",
                location_wgs84=(113.0, 23.0),
                cluster_id="cluster-1",
            ),
            ExternalObservation(
                observation_id="t-1",
                provider="tianditu",
                stage="l1",
                observed_name="道路",
                observed_type="road",
                location_wgs84=(113.0001, 23.0001),
                cluster_id="cluster-1",
            ),
        ],
    )
    graph = Graph()
    supports = project_external_observations(graph, snapshot)
    assert len(supports) == 1
    support_uri = next(graph.subjects(RDF.type, PLN.ExternalObservationSupport))
    assert len(list(graph.objects(support_uri, PLN.externalObservation))) == 2
    assert not list(graph.subjects(RDF.type, PLN.Road))
    assert not list(graph.subjects(RDF.type, PLN.Parcel))
