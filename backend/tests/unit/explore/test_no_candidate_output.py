"""Guardrail: retrieve_evidence must never output candidate BSMs, bbox, or intent."""
from __future__ import annotations

import inspect
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.modules.schema.contracts.evidence_contracts import (
    ExplorationRequest,
    EvidenceBundle,
    EvidenceFact,
    ExplorationResult,
)
from app.agent.explore.service import retrieve_evidence


_FORBIDDEN_ATTRS = (
    "candidate_bsm_list",
    "candidate_bbox",
    "intent",
    "bound_entities",
    "placement_decision",
)


def test_evidence_bundle_has_no_candidate_fields():
    """EvidenceBundle contract must not carry candidate/decision fields."""
    for attr in _FORBIDDEN_ATTRS:
        assert not hasattr(EvidenceBundle, attr), (
            f"EvidenceBundle must not have {attr}"
        )


def test_evidence_fact_has_no_candidate_fields():
    for attr in _FORBIDDEN_ATTRS:
        assert not hasattr(EvidenceFact, attr), (
            f"EvidenceFact must not have {attr}"
        )


def test_exploration_result_has_no_candidate_fields():
    for attr in _FORBIDDEN_ATTRS:
        assert not hasattr(ExplorationResult, attr), (
            f"ExplorationResult must not have {attr}"
        )


@pytest.mark.asyncio
async def test_retrieve_evidence_output_never_contains_candidates(mock_bundle):
    """End-to-end: retrieve_evidence result has zero candidate fields."""
    req = ExplorationRequest(
        run_id="r1", request_type="spatial_lookup", query="x",
        stage="L1", dimension_key="land_use",
    )
    with patch(
        "app.agent.explore.retrievers.report_retriever.ReportStore"
    ) as rs, patch(
        "app.agent.explore.retrievers.instruction_retriever.ReportStore"
    ) as is_, patch(
        "app.agent.explore.retrievers.kg_retriever.session_kg",
        return_value=None,
    ), patch(
        "app.agent.explore.retrievers.bundle_retriever.resolve_bundle",
        new=AsyncMock(return_value=mock_bundle),
    ), patch(
        "app.agent.explore.retrievers.bundle_retriever.group_stats",
        return_value={"polygons": {"current_landuse": {"count": 5, "labels": {}}}},
    ):
        rs.get_instance.return_value.get_layer_reports_with_sources = AsyncMock(return_value={})
        is_.get_instance.return_value.get_layer_reports_with_sources = AsyncMock(return_value={})
        result = await retrieve_evidence(req, session_id="s1", village_name="x")
    for attr in _FORBIDDEN_ATTRS:
        assert not hasattr(result, attr)
        assert not hasattr(result.evidence_bundle, attr)
        for fact in result.evidence_bundle.facts:
            assert not hasattr(fact, attr)


def test_service_does_not_import_legacy_explore_contracts():
    """service.py must not import ExplorationInstructionCollection."""
    source = inspect.getsource(
        __import__("app.agent.explore.service", fromlist=["retrieve_evidence"])
    )
    assert "ExplorationInstructionCollection" not in source
    assert "candidate_bsm" not in source
    assert "candidate_bbox" not in source
