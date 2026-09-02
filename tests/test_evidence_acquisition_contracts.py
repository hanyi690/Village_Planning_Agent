import hashlib

import pytest
from pydantic import ValidationError

from app.contracts.evidence.acquisition_contracts import (
    EvidenceAcquisitionReceipt,
    EvidenceObservationSnapshot,
    ProviderPageRecord,
)
from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    EvidenceFact,
    EvidenceSource,
    ExplorationRequest,
    ExplorationResult,
)
from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.cognition_round import CognitionRound
from app.contracts.evidence.policy_contracts import EvidencePolicyRegistry
from app.contracts.evidence.provider_attempt import ProviderAttempt
from app.infrastructure.evidence_runtime.query_planner import build_query_plan
from app.infrastructure.evidence_runtime.artifact_store import retrieval_fingerprint
from app.contracts.evidence.retrieval_contracts import EvidenceRetrievalAuthority
from app.infrastructure.artifacts.runtime import ArtifactReplayError
from app.infrastructure.evidence_runtime.acquisition_executor import AcquisitionRouteExecutor
from app.modules.evidence.application import _acquisition_audit


def _request() -> ExplorationRequest:
    return ExplorationRequest(
        run_id="run-1",
        request_type="spatial_lookup",
        query="道路",
        stage="GROUND",
        query_purpose="fact_check",
        entity_scope=["roads"],
    )


def test_policy_registry_is_versioned_and_deterministic():
    first = EvidencePolicyRegistry.resolve("road_identity.v1")
    second = EvidencePolicyRegistry.resolve("road_identity", "1")

    assert first == second
    assert first.fingerprint == second.fingerprint
    assert first.required_source_authority == "authoritative"
    with pytest.raises(ValueError, match="unknown Evidence policy"):
        EvidencePolicyRegistry.resolve("road_identity.v9")


def test_compiled_requirement_has_stable_ref_and_policy():
    request = _request()
    requirement = request.model_copy(update={
        "requirements": [],
    })
    from app.modules.evidence.requirements import compile_requirements

    compiled = compile_requirements(requirement)
    assert compiled[0].requirement_ref == compiled[0].requirement_id
    assert compiled[0].purpose == "fact_check"
    assert compiled[0].policy_ref == "location_identity_support.v1"


def test_query_plan_is_immutable_and_changes_when_page_semantics_change():
    from app.modules.evidence.requirements import compile_requirements

    request = _request().model_copy(update={"requirements": list(compile_requirements(_request()))})
    plan = build_query_plan(request)
    changed = build_query_plan(request.model_copy(update={"candidate_limit": 8}))

    assert plan.query_plan_ref.startswith("evidence.query-plan.")
    assert len(plan.plan_fingerprint) == 64
    assert plan.plan_fingerprint != changed.plan_fingerprint
    assert plan.provider_routes
    with pytest.raises((TypeError, ValidationError)):
        plan.normalized_query = "changed"

    invalid = request.model_copy(update={
        "requirements": [
            request.requirements[0].model_copy(update={"policy_ref": "unknown.v9"})
        ]
    })
    with pytest.raises(ValueError, match="unknown Evidence policy"):
        build_query_plan(invalid)


def test_attempt_and_page_lineage_keeps_terminal_states_distinct():
    running = ProviderAttempt(
        attempt_ref="attempt-running",
        query_plan_ref="plan-1",
        query_ref="route-1",
        provider="data_catalog",
        stage="GROUND",
        status="RUNNING",
    )
    assert running.status == "RUNNING"

    page = ProviderPageRecord(
        page_ref="page-1",
        attempt_ref="attempt-1",
        query_fingerprint="a" * 64,
        provider="data_catalog",
        item_count=2,
        response_digest="b" * 64,
        attempt_status="SUCCESS_NONEMPTY",
        termination_reason="provider_exhausted",
    )
    empty = ProviderAttempt(
        attempt_ref="attempt-empty",
        query_plan_ref="plan-1",
        query_ref="route-1",
        provider="data_catalog",
        stage="GROUND",
        status="SUCCESS_EMPTY",
        page_record_refs=(page.page_ref,),
    )
    not_attempted = ProviderAttempt(
        attempt_ref="attempt-not-run",
        query_plan_ref="plan-1",
        query_ref="route-2",
        provider="external",
        stage="GROUND",
        status="NOT_ATTEMPTED",
    )

    assert empty.status != not_attempted.status
    with pytest.raises(ValidationError):
        ProviderAttempt(
            attempt_ref="invalid",
            provider="external",
            stage="GROUND",
            status="NOT_ATTEMPTED",
            page_record_refs=(page.page_ref,),
        )


def test_observation_snapshot_and_receipt_digest_are_replayable():
    snapshot = EvidenceObservationSnapshot(
        snapshot_ref="observation-snapshot-1",
        query_plan_ref="plan-1",
        query_plan_fingerprint="a" * 64,
        attempt_refs=("attempt-1",),
        source_refs=("data:roads",),
        complete=True,
    )
    receipt = EvidenceAcquisitionReceipt(
        receipt_ref="receipt-1",
        query_plan_ref="plan-1",
        query_plan_fingerprint="a" * 64,
        attempt_refs=("attempt-1", "attempt-not-run"),
        page_refs=("page-1",),
        observation_snapshot_ref=snapshot.snapshot_ref,
        observation_snapshot_digest=snapshot.digest,
        completion="complete",
        termination_reasons=("provider_exhausted",),
    )

    reloaded = EvidenceAcquisitionReceipt.model_validate(receipt.model_dump(mode="json"))
    assert reloaded.digest == receipt.digest
    assert snapshot.digest == EvidenceObservationSnapshot.model_validate(
        snapshot.model_dump(mode="json")
    ).digest


def test_incomplete_termination_cannot_claim_complete_acquisition():
    with pytest.raises(ValidationError, match="incomplete termination"):
        EvidenceAcquisitionReceipt(
            receipt_ref="receipt-incomplete",
            query_plan_ref="plan-1",
            query_plan_fingerprint="a" * 64,
            attempt_refs=("attempt-1",),
            page_refs=("page-1",),
            completion="complete",
            termination_reasons=("quota_exhausted",),
        )


def test_runtime_executor_materializes_local_fact_without_fake_page():
    from app.modules.evidence.requirements import compile_requirements

    request = _request().model_copy(update={
        "requirements": list(compile_requirements(_request()))
    })
    plan = build_query_plan(request)
    result = ExplorationResult(evidence_bundle=EvidenceBundle(
        request=request.query,
        facts=[EvidenceFact(
            fact_id="fact-road-1",
            statement="道路 source record",
            source_refs=["data:roads:road-1"],
            source_locator="data://roads/road-1",
            source_kind="data_catalog",
        )],
        sources=[EvidenceSource(
            source_type="gis_layer",
            reference="data:roads:road-1",
            authority="authoritative",
        )],
    ))

    class Context:
        stage = "GROUND"
        external_observation_snapshot = None

    executor = AcquisitionRouteExecutor(plan, stage="GROUND")
    route_results = []
    for route in plan.provider_routes:
        route_results.append(executor.complete_route(
            route,
            status="SUCCESS_NONEMPTY" if route.retriever == "data_catalog" else "SUCCESS_EMPTY",
            facts=result.evidence_bundle.facts if route.retriever == "data_catalog" else (),
            sources=result.evidence_bundle.sources if route.retriever == "data_catalog" else (),
        ))
    attempts, pages, snapshot, receipt = executor.finalize(route_results)
    result = result.model_copy(update={
        "provider_attempts": attempts,
        "page_records": pages,
        "observation_snapshot": snapshot,
        "acquisition_receipt": receipt,
    })
    attempts, pages, snapshot, receipt = _acquisition_audit(
        result,
        query_plan=plan,
        context=Context(),
    )

    assert snapshot.complete is True
    assert len(snapshot.records) == 1
    assert snapshot.records[0].source_ref == "data:roads:road-1"
    assert snapshot.records[0].attempt_ref in {item.attempt_ref for item in attempts}
    assert receipt.observation_snapshot_digest == snapshot.digest
    assert pages == ()


def test_executor_separates_data_world_and_optional_external_lineage():
    requirement = {
        "requirement_id": "road-identity",
        "statement": "道路 identity",
        "kind": "identity",
        "policy_ref": "road_identity.v1",
        "scope": ["roads"],
    }
    request = ExplorationRequest(
        run_id="run-road",
        request_type="fact_check",
        query="道路 identity",
        context_refs=["source:external"],
        requirements=[requirement],
        entity_scope=["roads"],
    )
    plan = build_query_plan(request)
    executor = AcquisitionRouteExecutor(plan, stage="GROUND")
    data_route = next(item for item in plan.provider_routes if item.retriever == "data_catalog")
    world_route = next(item for item in plan.provider_routes if item.retriever == "kg")
    external_route = next(item for item in plan.provider_routes if item.retriever == "external") \
        if any(item.retriever == "external" for item in plan.provider_routes) else None
    data_fact = EvidenceFact(
        fact_id="data-road",
        statement="DATA source record road-1",
        source_refs=["data:roads:road-1"],
        source_kind="data_resource_catalog",
        fields={
            "source_feature_ref": "road-1",
            "geometry_authority": "data_resource_catalog",
        },
    )
    world_fact = EvidenceFact(
        fact_id="world-road",
        statement="WorldEntity road-entity represents road-1",
        source_refs=["world:road-entity"],
        fact_type="kg_world_entity",
        source_kind="kg",
        fields={"entity_ref": "road-entity"},
    )
    representation_fact = EvidenceFact(
        fact_id="world-road-representation",
        statement="WorldEntity road-entity links to DATA representation",
        source_refs=["world:road-entity"],
        fact_type="world_representation",
        source_kind="kg",
        fields={"entity_ref": "road-entity", "representation_ref": "rep-road-1"},
    )
    rows = [
        executor.complete_route(
            data_route,
            status="SUCCESS_NONEMPTY",
            facts=[data_fact],
            sources=[EvidenceSource(
                source_type="gis_layer",
                reference="data:roads:road-1",
                authority="authoritative",
            )],
        ),
        executor.complete_route(
            world_route,
            status="SUCCESS_NONEMPTY",
            facts=[world_fact, representation_fact],
            sources=[EvidenceSource(
                source_type="kg",
                reference="world:road-entity",
                authority="semantic",
            )],
        ),
    ]
    if external_route is not None:
        rows.append(executor.complete_route(
            external_route,
            status="NOT_ATTEMPTED",
            reason_code="optional_external_not_requested",
        ))
    attempts, pages, snapshot, receipt = executor.finalize(rows)

    assert {item.attempt_kind for item in attempts[:2]} == {"local_data", "current_world"}
    assert {item.observation_kind for item in snapshot.records} == {
        "DATA_SOURCE_RECORD",
        "CURRENT_WORLD_ENTITY",
        "CURRENT_WORLD_REPRESENTATION",
    }
    assert pages == ()
    assert receipt.incomplete_required_routes == ()
    if external_route is not None:
        assert external_route.route_ref in receipt.optional_unattempted_routes


def test_retrieval_cas_uses_business_digests_not_physical_snapshot_handles():
    def ref(seed: str) -> ArtifactRef:
        digest = hashlib.sha256(seed.encode()).hexdigest()
        return ArtifactRef(
            digest=f"sha256:{digest}",
            descriptor_digest=f"sha256:{digest}",
            semantic_digest=f"sha256:{digest}",
            size_bytes=0,
            schema_id="Test",
            schema_version="1",
            producer_stage="test",
            run_id="run-1",
            branch_id="main",
        )

    authority = EvidenceRetrievalAuthority(
        session_id="session-1",
        workflow_run_id="run-1",
        branch_id="main",
        context_version="context-1",
        context_fingerprint="context-digest-1",
        data_catalog_ref=ref("catalog-0"),
        data_catalog_digest="D0",
        data_snapshot_ref=ref("data-0"),
        data_snapshot_digest="D0",
        world_model_artifact_ref=ref("world-handle-0"),
        world_model_snapshot_ref="S0",
        world_model_snapshot_digest="C0",
        evidence_snapshot_ref=ref("evidence-0"),
        external_observations_ref=ref("external-0"),
        external_cache_digest="P0",
        gap_ledger_ref=ref("gap-0"),
        world_model_mode="v2_only",
        cognition_round=CognitionRound(
            round_id="round-1",
            round_number=0,
            wm_epoch="wm-epoch-1",
            parent_world_model_snapshot_ref="S0",
            parent_world_model_snapshot_digest="C0",
            requirement_set_digest="requirements-1",
        ),
    )
    request = _request()
    plan = build_query_plan(request)
    base = retrieval_fingerprint(authority, request, query_plan=plan)
    physical_world_change = authority.model_copy(update={
        "world_model_artifact_ref": ref("world-handle-1"),
        "world_model_snapshot_ref": "S1",
    })
    assert retrieval_fingerprint(physical_world_change, request, query_plan=plan) == base
    assert retrieval_fingerprint(
        authority.model_copy(update={"world_model_snapshot_digest": "C1"}),
        request,
        query_plan=plan,
    ) != base

    assert retrieval_fingerprint(
        authority.model_copy(update={"data_snapshot_digest": "D1"}),
        request,
        query_plan=plan,
    ) != base
    assert retrieval_fingerprint(
        authority,
        request.model_copy(update={"candidate_limit": 8}),
        query_plan=build_query_plan(request.model_copy(update={"candidate_limit": 8})),
    ) != base


def test_application_fails_closed_without_runtime_acquisition_audit():
    plan = build_query_plan(_request())

    class Context:
        stage = "GROUND"

    with pytest.raises(ArtifactReplayError, match="must produce"):
        _acquisition_audit(
            ExplorationResult(evidence_bundle=EvidenceBundle(request="roads")),
            query_plan=plan,
            context=Context(),
        )
