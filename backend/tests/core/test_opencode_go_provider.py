"""OpenCode Go provider wiring tests; no network call is made."""

from __future__ import annotations

import pytest


def test_opencode_go_provider_uses_isolated_openai_compatible_config(monkeypatch):
    from app.infrastructure.llm.factory import LLMProvider, create_llm, get_api_key, get_provider

    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-opencode-go-key")
    monkeypatch.setenv("OPENCODE_GO_API_BASE", "https://opencode.ai/zen/go/v1")

    assert get_provider("opencode-go") is LLMProvider.OPENCODE_GO
    assert get_api_key(LLMProvider.OPENCODE_GO) == "test-opencode-go-key"

    llm = create_llm(
        provider="opencode-go",
        model=None,
        temperature=0.2,
        max_tokens=128,
        streaming=False,
    )

    assert str(llm.openai_api_base).rstrip("/") == "https://opencode.ai/zen/go/v1"
    assert llm.model_name == "deepseek-v4-flash"


def test_opencode_go_accepts_fully_qualified_model_id(monkeypatch):
    from app.infrastructure.llm.factory import create_llm

    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-opencode-go-key")
    llm = create_llm(
        provider="opencode_go",
        model="opencode-go/kimi-k3",
        max_tokens=128,
    )

    assert llm.model_name == "kimi-k3"


def test_opencode_go_requires_its_own_key(monkeypatch):
    from app.infrastructure.llm.factory import create_llm

    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "an-openai-key")

    with pytest.raises(ValueError, match="OPENCODE_GO_API_KEY"):
        create_llm(provider="opencode-go", model="qwen3.7-plus", max_tokens=128)
