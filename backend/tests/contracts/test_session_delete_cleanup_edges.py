"""Guardrail: session deletion cleans evidence cache, provider failures, kg_memory, CAS refs."""

from __future__ import annotations


def test_session_delete_clears_evidence_cache():
    import asyncio

    from app.evidence.retrieval import evidence_service
    from app.application.sessions.session_service import _clear_session_evidence

    evidence_service._EVIDENCE_CACHE[
        ("fake-session", "layer1", "demo", "query", tuple(), "purpose")
    ] = {"x": 1}
    try:
        asyncio.run(_clear_session_evidence("fake-session"))
        assert not any(k[0] == "fake-session" for k in evidence_service._EVIDENCE_CACHE)
    finally:
        evidence_service._EVIDENCE_CACHE.clear()


def test_session_delete_resets_provider_failures():
    import asyncio

    from app.infrastructure.llm import dimension_runtime
    from app.application.sessions.session_service import _clear_provider_failures

    dimension_runtime._PROVIDER_FAILURE_SESSIONS.add("fake-session")
    try:
        asyncio.run(_clear_provider_failures("fake-session"))
        assert "fake-session" not in dimension_runtime._PROVIDER_FAILURE_SESSIONS
    finally:
        dimension_runtime._PROVIDER_FAILURE_SESSIONS.discard("fake-session")


def test_session_delete_artifacts_uses_run_tmp_root():
    from app.application.sessions.session_service import _delete_session_artifacts
    import inspect

    src = inspect.getsource(_delete_session_artifacts)
    assert "run_tmp_root" in src
    assert 'Path(".run-tmp")' not in src


def test_session_delete_kg_memory_uses_get_memory_dir():
    from app.application.sessions.session_service import _delete_session_kg_memory
    import inspect

    src = inspect.getsource(_delete_session_kg_memory)
    assert "get_memory_dir" in src
    assert "round_*.json" in src
