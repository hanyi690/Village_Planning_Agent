from __future__ import annotations

from app.contracts.domain.road_planning import (
    RoadArtifactEvidence,
    RoadEndpointEvidence,
    RoadEvidenceCatalog,
    RoadRoutingEvidence,
)
from app.contracts.workflow.parse_contracts import RoadTarget
from app.spatial.network.road_candidate_preparation import (
    prepare_road_candidate,
    prepare_road_candidates,
)


def _artifact(role: str, ref: str) -> RoadArtifactEvidence:
    return RoadArtifactEvidence(
        role=role,
        artifact_ref=ref,
        checksum="sha256:test-evidence",
    )


def _network_catalog() -> RoadEvidenceCatalog:
    return RoadEvidenceCatalog(
        current_network=_artifact("current_road_network", "artifact://road-network"),
        current_road_feature_ids={"ROAD-Y122"},
        current_road_segment_ids={"E000101", "E000102"},
    )


def _endpoint(role: str, entity_ref: str, coordinate: tuple[float, float]) -> RoadEndpointEvidence:
    return RoadEndpointEvidence(
        role=role,
        resolution_status="resolved",
        entity_ref=entity_ref,
        coordinate=coordinate,
        coordinate_crs="EPSG:4326",
        source_artifact_ref="artifact://grounding/place-resolution",
        source_feature_id=entity_ref,
        evidence_refs=[f"evidence://{entity_ref}"],
    )


def test_existing_road_intervention_requires_authoritative_feature_or_segment_binding() -> None:
    target = RoadTarget(
        target_id="road-upgrade-1",
        action="upgrade",
        road_planning_kind="existing_road_intervention",
        road_level="乡道",
        candidate_bsms=["ALL-VILLAGE-PARCELS"],
        path_bsms=["P001", "P002"],
        connects=["Y122乡道"],
    )

    result = prepare_road_candidate(target, _network_catalog())

    assert result.status == "unresolved"
    assert result.planning_input is None
    assert "ROAD_EXISTING_BINDING_MISSING" in {item.code for item in result.diagnostics}


def test_existing_road_intervention_rejects_unknown_current_road_ids() -> None:
    target = RoadTarget(
        target_id="road-repair-1",
        action="repair",
        road_planning_kind="existing_road_intervention",
        existing_road_segment_ids=["E999999"],
    )

    result = prepare_road_candidate(target, _network_catalog())

    assert result.status == "unresolved"
    assert "ROAD_EXISTING_SEGMENT_NOT_FOUND" in {item.code for item in result.diagnostics}


def test_existing_road_intervention_prepares_only_verified_segments() -> None:
    target = RoadTarget(
        target_id="road-harden-1",
        source_project_id="project-road-harden-1",
        action="harden",
        road_planning_kind="existing_road_intervention",
        existing_road_feature_ids=["ROAD-Y122"],
        existing_road_segment_ids=["E000101", "E000102"],
        roadbed_width_m=6.5,
        pavement_width_m=5.5,
        road_evidence_refs=["evidence://kg/road-y122"],
    )

    result = prepare_road_candidate(target, _network_catalog())

    assert result.status == "ready"
    assert result.planning_input is not None
    assert result.planning_input.planning_kind == "existing_road_intervention"
    assert result.planning_input.existing_road_segment_ids == ["E000101", "E000102"]
    assert result.planning_input.routing_evidence.current_network is not None


def test_new_corridor_does_not_treat_place_names_or_proxy_anchors_as_auditable_endpoints() -> None:
    target = RoadTarget(
        target_id="road-new-1",
        action="new",
        road_planning_kind="new_corridor",
        connects=["园寨村", "村南"],
        start_anchor=(116.01, 24.81),
        end_anchor=(116.02, 24.80),
        candidate_bsms=["P001", "P002"],
    )

    result = prepare_road_candidate(target, _network_catalog())

    assert result.status == "unresolved"
    assert result.planning_input is None
    assert "ROAD_ENDPOINT_PROVENANCE_MISSING" in {item.code for item in result.diagnostics}


def test_new_corridor_accepts_two_resolved_distinct_endpoints_with_provenance() -> None:
    target = RoadTarget(
        target_id="road-new-2",
        source_project_id="project-road-new-2",
        action="new",
        road_planning_kind="new_corridor",
        start_endpoint=_endpoint("start", "place://village-a", (116.01, 24.81)),
        end_endpoint=_endpoint("end", "place://village-b", (116.03, 24.79)),
        routing_evidence=RoadRoutingEvidence(
            dem=_artifact("dem", "artifact://terrain/dem"),
            land_friction=_artifact("land_friction", "artifact://suitability/land-friction"),
        ),
        roadbed_width_m=6,
        pavement_width_m=5,
    )

    result = prepare_road_candidate(target, _network_catalog())

    assert result.status == "ready"
    assert result.planning_input is not None
    assert result.planning_input.planning_kind == "new_corridor"
    assert result.planning_input.start_endpoint.entity_ref == "place://village-a"
    assert result.planning_input.end_endpoint.entity_ref == "place://village-b"
    assert result.planning_input.routing_evidence.dem is not None
    assert result.planning_input.routing_evidence.land_friction is not None


def test_new_corridor_can_resolve_legal_connection_entities_from_catalog() -> None:
    catalog = _network_catalog().model_copy(
        update={
            "endpoint_entities": {
                "place://village-a": _endpoint("start", "place://village-a", (116.01, 24.81)),
                "place://village-b": _endpoint("end", "place://village-b", (116.03, 24.79)),
            }
        }
    )
    target = RoadTarget(
        target_id="road-new-3",
        action="new",
        road_planning_kind="new_corridor",
        start_entity_ref="place://village-a",
        end_entity_ref="place://village-b",
    )

    result = prepare_road_candidate(target, catalog)

    assert result.status == "ready"
    assert result.planning_input is not None
    assert result.planning_input.start_endpoint.coordinate == (116.01, 24.81)
    assert result.planning_input.end_endpoint.coordinate == (116.03, 24.79)


def test_new_corridor_without_routing_artifact_evidence_is_unresolved() -> None:
    target = RoadTarget(
        target_id="road-new-4",
        action="new",
        road_planning_kind="new_corridor",
        start_endpoint=_endpoint("start", "place://village-a", (116.01, 24.81)),
        end_endpoint=_endpoint("end", "place://village-b", (116.03, 24.79)),
    )
    catalog = RoadEvidenceCatalog()

    result = prepare_road_candidate(target, catalog)

    assert result.status == "unresolved"
    assert "ROAD_ROUTING_EVIDENCE_MISSING" in {item.code for item in result.diagnostics}


def test_batch_preparation_never_replaces_unresolved_target_with_fallback_candidate() -> None:
    unresolved = RoadTarget(
        target_id="road-unresolved",
        action="new",
        road_planning_kind="new_corridor",
        connects=["全村", "村外"],
        candidate_bbox=(116.0, 24.7, 116.2, 24.9),
    )
    ready = RoadTarget(
        target_id="road-ready",
        action="repair",
        road_planning_kind="existing_road_intervention",
        existing_road_segment_ids=["E000101"],
    )

    batch = prepare_road_candidates([unresolved, ready], _network_catalog())

    assert [item.target_id for item in batch.ready_inputs] == ["road-ready"]
    assert batch.unresolved_target_ids == ["road-unresolved"]
    assert len(batch.results) == 2
