"""The LLM transport and stage budgets have one typed configuration boundary."""

import pytest

from app.core.llm_config import (
    LLMProviderName,
    LLMRuntimeSettings,
    LLMStructuredMode,
    get_llm_settings,
)


def test_provider_connection_and_protocol_are_resolved_from_one_snapshot(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "opencode_go")
    monkeypatch.setenv("LLM_STRUCTURED_MODE", "native_json_schema")
    monkeypatch.setenv("OPENCODE_GO_MODEL", "opencode-go/deepseek-v4-flash")
    monkeypatch.setenv("OPENCODE_GO_API_BASE", "https://example.test/v1")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")

    settings = get_llm_settings()
    connection = settings.connection()

    assert settings.provider == LLMProviderName.OPENCODE_GO.value
    assert settings.typed_mode() is LLMStructuredMode.JSON
    assert connection.provider is LLMProviderName.OPENCODE_GO
    assert connection.model == "deepseek-v4-flash"
    assert connection.base_url == "https://example.test/v1"
    assert connection.require_api_key() == "test-key"


def test_opencode_go_thinking_is_model_capability_aware():
    glm = LLMRuntimeSettings(
        provider="opencode-go",
        opencode_go_model="glm-5.3-flash",
        opencode_go_api_key="test-key",
        reasoning_effort="",
    )
    deepseek = LLMRuntimeSettings(
        provider="opencode-go",
        opencode_go_model="deepseek-v4-flash",
        opencode_go_api_key="test-key",
        reasoning_effort="",
    )

    assert glm.opencode_go_thinking_payload() == {"type": "enabled"}
    assert glm.opencode_go_reasoning_effort() == "max"
    assert deepseek.opencode_go_thinking_payload() == {"type": "disabled"}
    assert deepseek.opencode_go_reasoning_effort() is None


def test_opencode_go_typed_calls_use_documented_json_object_mode():
    glm = LLMRuntimeSettings(
        provider="opencode-go",
        opencode_go_model="glm-5.3-flash",
        opencode_go_api_key="test-key",
        structured_mode="json_schema",
        reasoning_effort="max",
    )
    deepseek = LLMRuntimeSettings(
        provider="opencode-go",
        opencode_go_model="deepseek-v4-flash",
        opencode_go_api_key="test-key",
        structured_mode="json_schema",
        reasoning_effort="",
    )

    assert glm.typed_mode() is LLMStructuredMode.JSON
    assert deepseek.typed_mode() is LLMStructuredMode.JSON


def test_connection_safe_metadata_never_contains_api_key():
    settings = LLMRuntimeSettings(
        provider="minimax",
        minimax_api_key="secret-value",
        minimax_model="MiniMax-test",
    )

    safe = settings.connection().safe_dict()

    assert safe["provider"] == "minimax"
    assert safe["model"] == "MiniMax-test"
    assert safe["api_key_configured"] is True
    assert "api_key" not in safe
    assert "secret-value" not in str(safe)


def test_stage_policy_keeps_explicit_budgets_and_separates_report_budget(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "opencode-go")
    monkeypatch.setenv("MAX_TOKENS", "65536")
    monkeypatch.setenv("L1_MAX_TOKENS", "32768")
    monkeypatch.setenv("L1_LLM_TIMEOUT_S", "480")
    monkeypatch.setenv("L1_REPORT_MAX_TOKENS", "4096")
    monkeypatch.setenv("L1_LLM_MAX_CONCURRENT", "12")
    monkeypatch.setenv("L2_MAX_TOKENS", "20000")
    monkeypatch.setenv("L2_REPORT_MAX_TOKENS", "6000")
    monkeypatch.setenv("L2_LLM_MAX_CONCURRENT", "12")
    monkeypatch.setenv("L3_MAX_TOKENS", "24000")
    monkeypatch.setenv("L3_REPORT_MAX_TOKENS", "7000")
    monkeypatch.setenv("L3_LLM_MAX_CONCURRENT", "12")
    monkeypatch.setenv("L3_PROVIDER_PARSE_RETRIES", "0")
    monkeypatch.setenv("L3_TRANSIENT_RETRIES", "0")

    settings = get_llm_settings()
    l1 = settings.stage_policy("l1")
    l2 = settings.stage_policy("l2")
    l3 = settings.stage_policy("l3")

    assert (l1.max_tokens, l1.report_max_tokens, l1.max_concurrent, l1.timeout_s) == (32768, 4096, 12, 480.0)
    assert (l2.max_tokens, l2.report_max_tokens, l2.max_concurrent) == (20000, 6000, 12)
    assert (l3.max_tokens, l3.report_max_tokens, l3.max_concurrent) == (24000, 7000, 12)
    assert l3.parse_retries == 0
    assert l3.transient_retries == 0


def test_unknown_stage_fails_closed():
    with pytest.raises(ValueError, match="unknown LLM stage"):
        LLMRuntimeSettings().stage_policy("render")


def test_negative_stage_budget_is_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        LLMRuntimeSettings(l3_max_tokens=-1)


def test_secondary_llm_callers_share_the_same_typed_snapshot(monkeypatch):
    monkeypatch.setenv("GROUND_LLM_ENABLED", "true")
    monkeypatch.setenv("GROUND_LLM_CALL_TIMEOUT_S", "75")
    monkeypatch.setenv("GROUND_MAX_LLM_CALLS", "20")
    monkeypatch.setenv("GROUND_MAX_RECOVERY_ROUNDS", "2")
    monkeypatch.setenv("GROUND_QUERY_SPEC_MAX_TOKENS", "1400")
    monkeypatch.setenv("RAG_DASHSCOPE_ENABLED", "true")
    monkeypatch.setenv("ALIYUN_EMBEDDING_MODEL", "embedding-test")

    settings = get_llm_settings()

    assert settings.ground_llm_is_disabled() is False
    assert settings.ground_call_timeout_s == 75.0
    assert settings.ground_max_calls == 20
    assert settings.ground_max_recovery_rounds == 2
    assert settings.ground_query_spec_max_tokens == 1400
    assert settings.rag_dashscope_enabled is True
    assert settings.embedding_model == "embedding-test"

    monkeypatch.setenv("DISABLE_GROUND_REPORT_LLM", "true")
    assert get_llm_settings().ground_llm_is_disabled(report=True) is True
