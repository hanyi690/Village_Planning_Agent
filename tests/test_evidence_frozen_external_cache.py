from types import SimpleNamespace

from app.contracts.evidence.evidence_contracts import ExplorationRequest
from app.contracts.evidence.external_observation_contracts import (
    ExternalObservation,
    ExternalObservationSnapshot,
)
from app.contracts.evidence.provider_attempt import (
    ProviderAttempt,
)
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.infrastructure.evidence_runtime.acquisition_executor import (
    AcquisitionRouteExecutor,
)
from app.infrastructure.evidence_runtime.frozen_cache_adapter import (
    read_frozen_external_cache,
)
from app.infrastructure.evidence_runtime.query_planner import build_query_plan


def _plan() -> tuple[object, object]:
    requirement = EvidenceRequirement(
        requirement_id="external-road",
        statement="道路外源观察",
        kind="identity",
        source_families=("external_map_cache",),
        policy_ref="road_identity.v1",
    )
    request = ExplorationRequest(
        run_id="run-external",
        request_type="fact_check",
        query="道路",
        requirements=[requirement],
    )
    plan = build_query_plan(request)
    route = next(item for item in plan.provider_routes if item.retriever == "external")
    return plan, route


def _snapshot(origin_status: str) -> ExternalObservationSnapshot:
    origin_attempt = ProviderAttempt(
        attempt_ref="evidence.attempt.amap-origin",
        provider="amap",
        stage="GROUND",
        query_fingerprint="a" * 64,
        status=origin_status,
        item_count=1,
        response_digest="b" * 64,
    )
    observation = ExternalObservation(
        observation_id="amap-observation-1",
        provider="amap",
        stage="GROUND",
        status="success_nonempty",
        attempted=True,
        observed_name="测试道路",
        observed_type="road",
        source_record_ref="amap-record-1",
        location_wgs84=(120.0, 30.0),
        coordinate_source_crs="EPSG:4326",
        coordinate_target_crs="EPSG:4326",
    )
    return ExternalObservationSnapshot(
        snapshot_id="external-cache-1",
        project_name="test",
        observations=[observation],
        provider_attempts=(origin_attempt,),
        complete=origin_status == "SUCCESS_NONEMPTY",
    )


def test_frozen_cache_success_preserves_quota_origin_as_incomplete():
    plan, route = _plan()
    result = read_frozen_external_cache(
        SimpleNamespace(external_observation_snapshot=_snapshot("QUOTA_EXHAUSTED")),
        plan,
        route,
        query="",
        entity_scope=(),
    )
    attempts = result.route_result.attempt
    pages = result.route_result.page_records
    assert attempts.attempt_kind == "frozen_cache"
    assert attempts.provider == "frozen_cache"
    assert attempts.provider_name == ""
    assert attempts.status == "SUCCESS_NONEMPTY"
    assert attempts.page_record_refs == ()
    assert result.route_result.observations[0].observation_kind == "EXTERNAL_OBSERVATION"
    assert result.route_result.observations[0].origin_provider == "amap"
    assert result.route_result.observations[0].origin_attempt_ref == "evidence.attempt.amap-origin"
    assert result.route_result.observations[0].origin_status == "QUOTA_EXHAUSTED"
    assert result.route_result.observations[0].resource_ref == ""
    assert result.route_result.observations[0].representation_ref == ""
    assert pages == ()

    _, _, snapshot, receipt = AcquisitionRouteExecutor(plan).finalize([result.route_result])
    assert receipt.cache_read_complete is True
    assert receipt.origin_completeness == "incomplete"
    assert snapshot.records[0].cache_digest == _snapshot("QUOTA_EXHAUSTED").digest


def test_complete_and_empty_frozen_cache_have_complete_cache_read_only():
    plan, route = _plan()
    complete = read_frozen_external_cache(
        SimpleNamespace(external_observation_snapshot=_snapshot("SUCCESS_NONEMPTY")),
        plan,
        route,
    )
    _, _, _, complete_receipt = AcquisitionRouteExecutor(plan).finalize([complete.route_result])
    assert complete_receipt.cache_read_complete is True
    assert complete_receipt.origin_completeness == "complete"

    empty_snapshot = _snapshot("SUCCESS_EMPTY").model_copy(update={"observations": []})
    empty = read_frozen_external_cache(
        SimpleNamespace(external_observation_snapshot=empty_snapshot),
        plan,
        route,
    )
    _, pages, _, empty_receipt = AcquisitionRouteExecutor(plan).finalize([empty.route_result])
    assert empty.route_result.attempt.status == "SUCCESS_EMPTY"
    assert empty_receipt.cache_read_complete is True
    assert empty_receipt.origin_completeness == "complete"
    assert pages == ()

