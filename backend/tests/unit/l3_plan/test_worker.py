"""L3 PLAN worker tests.

Proves ``analyze_l3_dimension``:
  1. calls retrieve_evidence (smoke, heavy I/O patched out by mock_worker_deps),
  2. sends an ExplorationRequest with stage == "L3",
  3. returns the standard L3 state shape,
  4. does NOT reference the L1 analysis node implementation (L3 subgraph
     independence per docs/architecture/agent-graph.md).
"""
from __future__ import annotations

import inspect

import pytest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from app.modules.schema.contracts.evidence_contracts import (
    ExplorationResult,
    EvidenceBundle,
    SpatialCognitionEvidence,
)


def _state(dim_key: str = "land_use_planning") -> dict:
    return {
        "dimension_key": dim_key,
        "session_id": "s1",
        "phase": "layer3",
        "config": {"village_name": "田坑村", "village_data": ""},
        "completed_dimensions": {"layer1": [], "layer2": [], "layer3": []},
        "messages": [],
    }


@pytest.mark.asyncio
async def test_analyze_l3_dimension_calls_retrieve_evidence(mock_worker_deps):
    fake_result = ExplorationResult(
        evidence_bundle=EvidenceBundle(request="x", facts=[], sources=[]),
        spatial_cognition=SpatialCognitionEvidence(village_overview="test"),
    )
    with patch(
        "app.agent.l3_plan.worker.retrieve_evidence",
        new=AsyncMock(return_value=fake_result),
    ) as mock_retrieve:
        from app.agent.l3_plan.worker import analyze_l3_dimension

        state = _state()
        try:
            result = await analyze_l3_dimension(state)
        except Exception:
            result = None
        mock_retrieve.assert_called_once()
        assert result is not None
        assert "completed_dimensions" in result


@pytest.mark.asyncio
async def test_analyze_l3_dimension_uses_stage_l3_request(mock_worker_deps):
    from app.agent.l3_plan.worker import analyze_l3_dimension
    from app.agent.l3_plan import worker as worker_mod

    await analyze_l3_dimension(_state())

    req = worker_mod.retrieve_evidence.call_args[0][0]
    assert req.stage == "L3"
    assert req.dimension_key == "land_use_planning"
    assert req.query_purpose == "context_injection"


@pytest.mark.asyncio
async def test_analyze_l3_dimension_returns_standard_state_shape(mock_worker_deps):
    from app.agent.l3_plan.worker import analyze_l3_dimension

    result = await analyze_l3_dimension(_state())

    assert result["completed_dimensions"] == {"layer3": ["land_use_planning"]}
    assert len(result["pending_reports"]) == 1
    report = result["pending_reports"][0]
    assert report["dimension_key"] == "land_use_planning"
    assert report["layer"] == 3
    assert result["layer_char_counts"] == {3: 4}
    assert isinstance(result["messages"][0], AIMessage)


def test_l3_worker_does_not_import_l1_analysis_node():
    import app.agent.l3_plan.worker as mod

    source = inspect.getsource(mod)
    assert "l1_observe" not in source
    assert "analysis_node" not in source
