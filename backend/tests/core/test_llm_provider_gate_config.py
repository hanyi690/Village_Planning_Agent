from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_provider_gate_reads_typed_settings_at_creation_time(monkeypatch):
    from app.infrastructure.llm import factory

    factory._llm_semaphore = None
    factory._llm_semaphore_loop = None
    factory._llm_semaphore_budget = None
    monkeypatch.setattr(
        "app.core.llm_config.get_llm_settings",
        lambda: SimpleNamespace(provider_concurrency=lambda: 12),
    )

    gate = await factory.get_llm_semaphore()

    assert gate._value == 12
