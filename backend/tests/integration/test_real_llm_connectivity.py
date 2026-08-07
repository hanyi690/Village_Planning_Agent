"""Opt-in live provider check for the configured repository LLM."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.timeout(60)
def test_configured_llm_returns_real_message():
    """Exercise the configured OpenAI-compatible provider, not a fake adapter."""
    from app.core.llm import create_llm

    llm = create_llm(temperature=0, max_tokens=64)
    response = asyncio.run(llm.ainvoke("只回复 OK"))
    content = getattr(response, "content", "") or ""
    assert content.strip(), "configured LLM returned an empty message"
    metadata = getattr(response, "response_metadata", {}) or {}
    assert metadata.get("model_name"), "real provider metadata is missing model_name"
