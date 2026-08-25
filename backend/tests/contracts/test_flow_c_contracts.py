from __future__ import annotations

import ast
import inspect

import pytest
from pydantic import BaseModel, ValidationError

from app.contracts.ports.adjustment import (
    AdjustmentExecutionResult,
    ValidationAdjustmentExecutor,
)
from app.contracts.ports.external_search import ExternalSearchPort
from app.contracts.ports.media_evidence import MediaEvidencePort, VisualEvidencePort
from app.contracts.workflow.repair import (
    ExternalSearchRequest,
    ExternalSearchResult,
    IterationRecord,
    RelationEvidence,
    SearchFailure,
    ValidationAdjustment,
)
from app.evidence.model import (
    DemandPortfolio,
    ImageArtifact,
    ImageEvidence,
    ImageIngestRequest,
    ScenarioSnapshot,
    SuitabilitySurface,
    VisualAnalysisRequest,
    VisualFact,
    VisualReview,
    PortfolioDecision,
)


pytestmark = pytest.mark.contracts


def _digest(value: str) -> str:
    return f"sha256:{value * 64}"[:71]


def _artifact_ref() -> object:
    from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor

    return ArtifactDescriptor(
        digest=_digest("a"),
        descriptor_digest=_digest("b"),
        size_bytes=1,
        schema_id="test",
        schema_version="1.0",
        semantic_digest=_digest("c"),
        producer_stage="test",
        run_id="run-1",
        branch_id="main",
    )


def test_frozen_models_publish_strict_forbid_schema() -> None:
    models = [
        RelationEvidence,
        ValidationAdjustment,
        IterationRecord,
        ExternalSearchRequest,
        ExternalSearchResult,
        DemandPortfolio,
        SuitabilitySurface,
        PortfolioDecision,
        ImageArtifact,
        ImageEvidence,
        VisualFact,
        VisualReview,
        ScenarioSnapshot,
    ]

    for model in models:
        assert issubclass(model, BaseModel)
        assert model.model_config["strict"] is True
        assert model.model_config["extra"] == "forbid"
        assert "schema_version" in model.model_json_schema()["properties"]


def test_repair_and_visual_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RelationEvidence(
            subject_ref="facility-1",
            predicate="located_in",
            object_ref="village-1",
            source_refs=["evidence-1"],
            confidence=0.9,
            query_trace=[],
            unexpected="not-allowed",
        )

    with pytest.raises(ValidationError):
        ImageArtifact(
            artifact_ref="image-1",
            sha256="abc",
            storage_ref="cas:image-1",
            mime_type="image/png",
            width=10,
            height=10,
            source_ref="upload-1",
            unexpected="not-allowed",
        )


def test_contract_metadata_keeps_digest_parents_provenance_and_target_refs() -> None:
    adjustment = ValidationAdjustment(
        adjustment_id="adjustment-1",
        responsible_stage="VALIDATE",
        affected_target_refs=["target-1"],
        input_refs={"execution": _artifact_ref()},
        evidence_refs=["evidence-1"],
        bounded_params={"max_area_ha": 2.0},
        issue_fingerprint="issue-1",
        idempotency_key="idem-1",
        parent_digests={"execution": _digest("d")},
        provenance={"source": "contract-test"},
    )
    review = VisualReview(
        target_ref="target-1",
        planning_status="needs_adjustment",
        evidence_refs=["visual-evidence-1"],
        issue="planned boundary is not legible",
        adjustment_refs=[adjustment.adjustment_id],
        provenance={"source": "contract-test"},
    )

    assert adjustment.parent_digests["execution"].startswith("sha256:")
    assert adjustment.provenance["source"] == "contract-test"
    assert review.target_ref == "target-1"


def test_external_search_failure_is_typed_and_replayable() -> None:
    request = ExternalSearchRequest(
        query_purpose="fact_check",
        normalized_entities=[{"canonical_name": "社前村", "aliases": ["社前"]}],
        entity_scope=["village"],
        source_policy={"allow_external": True},
        allowed_domains=["example.org"],
        allowed_categories=["government"],
        freshness={"max_age_days": 30},
        search_mode="neural",
        result_limit=5,
        content_mode="highlights",
        budget={"max_cost": 1.0, "max_latency_ms": 2000},
        parent_refs=["sha256:parent"],
        idempotency_key="search-1",
        provenance={"source": "contract-test"},
    )
    result = ExternalSearchResult(
        provider="fake",
        request_id="request-1",
        resolved_search_mode="neural",
        result_records=[],
        evidence_refs=[],
        retrieval_status="timeout",
        latency_ms=2000,
        cost={"amount": 0.0},
        cache_policy="live",
        failure=SearchFailure(
            code="provider_timeout",
            message="provider did not respond within the budget",
            retryable=True,
            local_fallback_allowed=True,
        ),
        provenance={"request_id": request.idempotency_key},
    )

    assert result.retrieval_status == "timeout"
    assert result.failure is not None
    assert result.failure.local_fallback_allowed is True


def test_success_result_cannot_hide_a_typed_failure() -> None:
    with pytest.raises(ValidationError):
        ExternalSearchResult(
            provider="fake",
            request_id="request-1",
            resolved_search_mode="neural",
            result_records=[],
            evidence_refs=[],
            retrieval_status="success",
            failure=SearchFailure(
                code="unexpected",
                message="must not be attached to success",
                retryable=False,
                local_fallback_allowed=False,
            ),
            provenance={},
        )


def test_ports_are_provider_agnostic_and_substitutable() -> None:
    class FakeMedia:
        async def ingest(self, request: ImageIngestRequest) -> ImageArtifact:
            return ImageArtifact(
                artifact_ref="image-1",
                sha256="abc",
                storage_ref="cas:image-1",
                mime_type=request.mime_type,
                width=10,
                height=10,
                source_ref=request.source_ref,
            )

    class FakeVision:
        async def analyze(
            self,
            artifact_ref: str,
            request: VisualAnalysisRequest,
        ) -> ImageEvidence:
            return ImageEvidence(
                evidence_id="evidence-1",
                image_ref=artifact_ref,
                layout=[],
                legend=[],
                labels=[],
                confidence=0.5,
                spatial_status="unresolved",
                temporal_status="unresolved",
                review_status="human_required",
                provenance={"dimension": request.dimension},
            )

    class FakeSearch:
        async def search(self, request: ExternalSearchRequest) -> ExternalSearchResult:
            return ExternalSearchResult(
                provider="fake",
                request_id=request.idempotency_key,
                resolved_search_mode=request.search_mode,
                result_records=[],
                evidence_refs=[],
                retrieval_status="empty",
                failure=SearchFailure(
                    code="no_results",
                    message="no source-backed result",
                    retryable=False,
                    local_fallback_allowed=True,
                ),
                provenance={"source": "fake"},
            )

    class FakeAdjustment:
        async def apply(self, state: object, report: object) -> AdjustmentExecutionResult:
            return AdjustmentExecutionResult(status="rejected", output_refs={})

    assert isinstance(FakeMedia(), MediaEvidencePort)
    assert isinstance(FakeVision(), VisualEvidencePort)
    assert isinstance(FakeSearch(), ExternalSearchPort)
    assert isinstance(FakeAdjustment(), ValidationAdjustmentExecutor)


def test_public_flow_c_modules_do_not_use_any_annotation() -> None:
    modules = [
        "app.contracts.workflow.repair",
        "app.contracts.ports.adjustment",
        "app.contracts.ports.external_search",
        "app.contracts.ports.media_evidence",
        "app.evidence.model",
        "app.evidence.model.media",
        "app.evidence.model.planning",
    ]

    for module_name in modules:
        module = __import__(module_name, fromlist=["*"])
        tree = ast.parse(inspect.getsource(module))
        assert not any(
            isinstance(node, ast.Name) and node.id == "Any"
            for node in ast.walk(tree)
        ), module_name
