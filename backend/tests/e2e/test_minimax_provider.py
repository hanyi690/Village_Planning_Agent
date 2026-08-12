"""MiniMax provider wiring tests; no network call is made."""

from __future__ import annotations

import asyncio

import pytest


pytestmark = pytest.mark.e2e


def test_minimax_provider_uses_official_openai_endpoint(monkeypatch):
    from app.infrastructure.llm.factory import LLMProvider, create_llm, get_provider

    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    assert get_provider("minimax") is LLMProvider.MINIMAX
    llm = create_llm(
        provider="minimax",
        model="MiniMax-M2.7",
        temperature=0,
        max_tokens=8,
        streaming=False,
    )
    assert str(llm.openai_api_base).rstrip("/") == "https://api.minimaxi.com/v1"
    assert llm.temperature == 0.01


def test_minimax_default_uses_highspeed_model(monkeypatch):
    from app.infrastructure.llm.factory import create_llm

    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    llm = create_llm(provider="minimax", model=None, max_tokens=8)

    assert llm.model_name == "MiniMax-M2.7-highspeed"


def test_minimax_streaming_preflight():
    from app.infrastructure.llm.factory import create_llm

    from app.core.settings import MINIMAX_API_KEY

    if not MINIMAX_API_KEY:
        pytest.skip("MINIMAX_API_KEY is not configured")
    llm = create_llm(
        provider="minimax",
        model="MiniMax-M2.7",
        temperature=0,
        max_tokens=16,
        streaming=True,
    )

    async def collect():
        chunks = []
        async for chunk in llm.astream("只回复 OK"):
            if getattr(chunk, "content", None):
                chunks.append(chunk.content)
        return chunks

    chunks = asyncio.run(collect())
    assert chunks
    assert "OK" in "".join(chunks)
