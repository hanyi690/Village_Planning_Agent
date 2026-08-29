from app.contracts.evidence.external_observation_contracts import (
    ExternalObservation,
    ExternalObservationSnapshot,
)
from app.infrastructure.evidence_runtime.retrievers.cached_map_retriever import (
    retrieve_from_cached_map,
)


class _Context:
    def __init__(self, snapshot):
        self.external_observation_snapshot = snapshot


def test_cached_map_projection_is_advisory_and_lineage_bearing():
    snapshot = ExternalObservationSnapshot(
        snapshot_id="snap-1",
        observations=[
            ExternalObservation(
                observation_id="obs-1",
                provider="amap",
                stage="02_l1_place_names",
                scope_bucket="project_local",
                observed_name="金田村卫生室",
                aliases=["卫生室"],
                observed_type="facility",
                location_wgs84=(113.1, 23.1),
                raw_response_ref="cache://amap/raw/1",
                source_record_ref="amap:record:1",
            )
        ],
    )
    facts, sources, trace = retrieve_from_cached_map(
        _Context(snapshot), query="卫生室", entity_scope=["facilities"]
    )
    assert len(facts) == len(sources) == 1
    assert facts[0].fact_type == "external_map_observation"
    assert facts[0].planning_use == "grounding"
    assert facts[0].spatial_refs == ["external-observation:obs-1"]
    assert sources[0].authority == "advisory"
    assert sources[0].snapshot_ref == "snap-1"
    assert trace["cache_only"] is True


def test_cached_map_projection_respects_scope_without_http():
    snapshot = ExternalObservationSnapshot(
        snapshot_id="snap-2",
        observations=[
            ExternalObservation(
                observation_id="road-1",
                provider="tianditu",
                stage="01_admin_scope",
                scope_bucket="project_local",
                observed_name="村道",
                observed_type="road",
            ),
            ExternalObservation(
                observation_id="water-1",
                provider="tianditu",
                stage="01_admin_scope",
                scope_bucket="project_local",
                observed_name="池塘",
                observed_type="waterbody",
            ),
        ],
    )
    facts, _, _ = retrieve_from_cached_map(
        _Context(snapshot), query="", entity_scope=["roads"]
    )
    assert [fact.fields["observation_id"] for fact in facts] == ["road-1"]
