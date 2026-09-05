from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from app.infrastructure.structured_runtime.consensus import (
    run_structured_consensus,
)


class _Output(BaseModel):
    role: str
    reason: str


@pytest.mark.asyncio
async def test_consensus_keeps_two_typed_passes_and_accepts_domain_validator():
    spec = SimpleNamespace(contract_key="data.temporal_role", model="test-model")
    outputs = [_Output(role="current_evidence", reason="a"), _Output(role="current_evidence", reason="b")]
    with patch(
        "app.infrastructure.structured_runtime.facade.run_structured",
        new=AsyncMock(side_effect=outputs),
    ):
        result = await run_structured_consensus(
            spec,
            [{"role": "user", "content": "profile"}],
            validator=lambda value: value.role == "current_evidence",
        )

    assert result.status == "completed"
    assert result.completed_pass_count == 2
    assert [item.typed_output.reason for item in result.passes] == ["a", "b"]


@pytest.mark.asyncio
async def test_consensus_separates_provider_failure_from_semantic_failure():
    spec = SimpleNamespace(contract_key="data.temporal_role", model="test-model")
    with patch(
        "app.infrastructure.structured_runtime.facade.run_structured",
        new=AsyncMock(side_effect=[asyncio.TimeoutError(), _Output(role="x", reason="bad")]),
    ):
        result = await run_structured_consensus(
            spec,
            [{"role": "user", "content": "profile"}],
            validator=lambda value: value.role == "current_evidence",
        )

    assert result.status == "provider_failed"
    assert result.provider_failure_count == 1
    assert result.semantic_failure_count == 1
    assert result.passes[1].failure_code == "SEMANTIC_VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_consensus_marks_schema_or_protocol_failure_separately():
    spec = SimpleNamespace(contract_key="data.temporal_role", model="test-model")
    with patch(
        "app.infrastructure.structured_runtime.facade.run_structured",
        new=AsyncMock(side_effect=[ValueError("malformed response"), ValueError("malformed response")]),
    ):
        result = await run_structured_consensus(
            spec,
            [{"role": "user", "content": "profile"}],
        )

    assert result.status == "protocol_failed"
    assert result.provider_failure_count == 0
    assert result.protocol_failure_count == 2
    assert all(item.status == "protocol_failed" for item in result.passes)
