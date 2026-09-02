import hashlib

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.evidence.evidence_contracts import ExplorationRequest
from app.contracts.evidence.retrieval_artifact_contracts import EvidenceRetrievalArtifact
from app.contracts.evidence.retrieval_contracts import (
    EvidenceRetrievalAuthority,
    EvidenceRetrievalBootstrapRefs,
    EvidenceRetrievalOutcome,
)
from app.infrastructure.evidence_runtime.artifact_store import _result_semantics
from app.modules.evidence.proposals import build_evidence_proposals

from test_evidence_proposals import _requirement, _result


def _ref(seed: str, *, schema_id: str = "Test") -> ArtifactRef:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    value = f"sha256:{digest}"
    return ArtifactRef(
        digest=value,
        descriptor_digest=value,
        semantic_digest=value,
        size_bytes=0,
        schema_id=schema_id,
        schema_version="1",
        producer_stage="test",
        run_id="run-1",
        branch_id="main",
    )


def _artifact(result, batch) -> EvidenceRetrievalArtifact:
    authority = EvidenceRetrievalAuthority(
        session_id="session-1",
        workflow_run_id="run-1",
        branch_id="main",
        context_version="context-1",
        context_fingerprint="context-1",
        data_catalog_ref=_ref("catalog"),
        data_catalog_digest="catalog-digest",
        data_snapshot_ref=_ref("data"),
        data_snapshot_digest="data-digest",
        world_model_artifact_ref=_ref("world"),
        world_model_snapshot_ref="wm-7",
        world_model_snapshot_digest="wm-7",
        evidence_snapshot_ref=_ref("evidence"),
        external_observations_ref=_ref("external"),
        external_cache_digest="cache-digest",
        gap_ledger_ref=_ref("gaps"),
        world_model_mode="v2_only",
    )
    request = ExplorationRequest(
        run_id="run-1",
        request_type="fact_check",
        query=result.evidence_bundle.request,
        requirements=[_requirement("identity")],
    )
    return EvidenceRetrievalArtifact(
        artifact_id="retrieval-1",
        fingerprint="a" * 64,
        canonical_request=request,
        evidence_bundle=result.evidence_bundle,
        evidence_packet=result.evidence_packet,
        coverage=result.coverage,
        outcome=EvidenceRetrievalOutcome(status="sufficient"),
        authority=authority,
        bootstrap_refs=EvidenceRetrievalBootstrapRefs(
            evidence_snapshot_ref=authority.evidence_snapshot_ref,
            external_observations_ref=authority.external_observations_ref,
            gap_ledger_ref=authority.gap_ledger_ref,
        ),
        proposal_batch=batch,
    )


def test_exploration_result_and_retrieval_artifact_reload_proposals():
    result = _result(_requirement("identity"))
    batch = build_evidence_proposals(
        result,
        round_id="round-1",
        wm_epoch="wm-7",
        parent_world_model_digest="wm-7",
        evidence_artifact_ref="evidence-retrieval:1",
    )
    result = result.model_copy(update={"proposal_batch": batch})
    artifact = _artifact(result, batch)

    reloaded_result = type(result).model_validate(result.model_dump(mode="json"))
    reloaded_artifact = type(artifact).model_validate(artifact.model_dump(mode="json"))

    assert reloaded_result.proposal_batch == batch
    assert reloaded_artifact.proposal_batch == batch


def test_retrieval_semantics_change_when_proposal_batch_changes():
    result = _result(_requirement("identity"))
    batch = build_evidence_proposals(
        result,
        round_id="round-1",
        wm_epoch="wm-7",
        parent_world_model_digest="wm-7",
    )
    artifact = _artifact(result, batch)
    changed_batch = batch.model_copy(update={"round_id": "round-2"})
    changed_artifact = artifact.model_copy(update={"proposal_batch": changed_batch})

    assert _result_semantics(changed_artifact) != _result_semantics(artifact)
