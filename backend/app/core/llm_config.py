"""Single typed configuration boundary for every LLM transport.

The application has two implementation paths for model calls: the LangChain
factory and the Instructor structured client.  They must resolve the same
provider connection and protocol from the same settings object.  This module
contains only transport configuration; domain contracts and stage policies
remain in their respective modules.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(Path.cwd() / ".env", override=False)
load_dotenv(_PROJECT_ROOT / ".env", override=False)


class LLMProviderName(str, Enum):
    """Canonical provider names understood by the runtime."""

    OPENAI = "openai"
    ZHIPUAI = "zhipuai"
    MINIMAX = "minimax"
    OPENCODE_GO = "opencode-go"
    DASHSCOPE = "dashscope"


class LLMStructuredMode(str, Enum):
    """Wire protocol used for typed output calls."""

    TOOLS = "tools"
    JSON = "json"
    JSON_SCHEMA = "json_schema"
    MD_JSON = "md_json"


_PROVIDER_ALIASES = {
    "deepseek": LLMProviderName.OPENAI.value,
    "openai-compatible": LLMProviderName.OPENAI.value,
    "minimaxai": LLMProviderName.MINIMAX.value,
    "mini-max": LLMProviderName.MINIMAX.value,
    "opencode_go": LLMProviderName.OPENCODE_GO.value,
    "opencodego": LLMProviderName.OPENCODE_GO.value,
}

_STRUCTURED_MODE_ALIASES = {
    "tool": LLMStructuredMode.TOOLS.value,
    "function": LLMStructuredMode.TOOLS.value,
    "function_call": LLMStructuredMode.TOOLS.value,
    "function_calling": LLMStructuredMode.TOOLS.value,
    "json-mode": LLMStructuredMode.JSON.value,
    "json_schema_native": LLMStructuredMode.JSON_SCHEMA.value,
    "native_json_schema": LLMStructuredMode.JSON_SCHEMA.value,
    "strict_json_schema": LLMStructuredMode.JSON_SCHEMA.value,
    "json-schema": LLMStructuredMode.JSON_SCHEMA.value,
    "markdown_json": LLMStructuredMode.MD_JSON.value,
    "markdown-json": LLMStructuredMode.MD_JSON.value,
}


def normalize_provider_name(value: str | LLMProviderName | None) -> str:
    """Return one canonical provider name without touching credentials."""

    raw = str(value or "").strip().lower()
    raw = _PROVIDER_ALIASES.get(raw, raw)
    if raw in {item.value for item in LLMProviderName}:
        return raw
    # Preserve the historical factory fallback, but make it one shared rule.
    return LLMProviderName.OPENAI.value


def normalize_structured_mode(value: str | LLMStructuredMode | None) -> str:
    """Normalize user-facing protocol aliases to one wire mode."""

    raw = str(value or "").strip().lower()
    raw = _STRUCTURED_MODE_ALIASES.get(raw, raw)
    if raw in {item.value for item in LLMStructuredMode}:
        return raw
    return LLMStructuredMode.TOOLS.value


class LLMConnection(BaseModel):
    """Resolved provider connection used by both client implementations."""

    model_config = ConfigDict(extra="forbid")

    provider: LLMProviderName
    model: str = Field(min_length=1)
    api_key: str | None = None
    base_url: str | None = None

    def require_api_key(self) -> str:
        if not self.api_key:
            env_name = {
                LLMProviderName.OPENAI: "OPENAI_API_KEY",
                LLMProviderName.ZHIPUAI: "ZHIPUAI_API_KEY",
                LLMProviderName.MINIMAX: "MINIMAX_API_KEY",
                LLMProviderName.OPENCODE_GO: "OPENCODE_GO_API_KEY",
                LLMProviderName.DASHSCOPE: "DASHSCOPE_API_KEY",
            }[self.provider]
            raise ValueError(f"{env_name} not found in environment.")
        return self.api_key

    def safe_dict(self) -> dict[str, Any]:
        """Return diagnostics-safe connection metadata without the key."""

        return {
            "provider": self.provider.value,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_configured": bool(self.api_key),
        }


@dataclass(frozen=True)
class LLMStagePolicy:
    """One immutable budget snapshot for a typed workflow stage.

    A stage policy is deliberately separate from the provider connection.  A
    provider/model is shared by all stages, while output budgets and semantic
    reask budgets belong to the stage contract.  Keeping both in the same
    settings snapshot prevents one worker from silently reading a different
    environment value after the request has started.
    """

    timeout_s: float
    max_tokens: int
    observe_max_tokens: int
    report_max_tokens: int
    max_concurrent: int
    parse_retries: int
    transient_retries: int
    transient_retry_backoff_s: float
    incomplete_output_max_tokens: int


class LLMRuntimeSettings(BaseSettings):
    """Typed environment-backed configuration shared by all LLM instances."""

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    provider: str = Field(
        default=LLMProviderName.MINIMAX.value,
        validation_alias=AliasChoices("LLM_PROVIDER", "provider"),
    )
    llm_model: str = Field(
        default="MiniMax-M2.7-highspeed",
        validation_alias=AliasChoices("LLM_MODEL", "llm_model"),
    )
    max_tokens: int = Field(
        default=32768,
        validation_alias=AliasChoices("MAX_TOKENS", "max_tokens"),
    )
    structured_mode: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_STRUCTURED_MODE", "structured_mode"),
    )

    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
    )
    openai_api_base: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_BASE", "openai_api_base"),
    )
    zhipuai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ZHIPUAI_API_KEY", "zhipuai_api_key"),
    )
    zhipuai_api_base: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ZHIPUAI_API_BASE", "zhipuai_api_base"),
    )
    dashscope_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DASHSCOPE_API_KEY", "dashscope_api_key"),
    )
    dashscope_api_base: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("DASHSCOPE_API_BASE", "dashscope_api_base"),
    )
    minimax_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MINIMAX_API_KEY", "minimax_api_key"),
    )
    minimax_api_base: str = Field(
        default="https://api.minimaxi.com/v1",
        validation_alias=AliasChoices("MINIMAX_API_BASE", "minimax_api_base"),
    )
    minimax_model: str = Field(
        default="MiniMax-M2.7-highspeed",
        validation_alias=AliasChoices("MINIMAX_MODEL", "minimax_model"),
    )
    opencode_go_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENCODE_GO_API_KEY", "opencode_go_api_key"),
    )
    opencode_go_api_base: str = Field(
        default="https://opencode.ai/zen/go/v1",
        validation_alias=AliasChoices("OPENCODE_GO_API_BASE", "opencode_go_api_base"),
    )
    opencode_go_model: str = Field(
        default="deepseek-v4-flash",
        validation_alias=AliasChoices("OPENCODE_GO_MODEL", "opencode_go_model"),
    )

    stream_timeout: float = Field(
        default=600.0,
        validation_alias=AliasChoices("LLM_STREAM_TIMEOUT", "stream_timeout"),
    )
    provider_request_timeout: float | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "LLM_PROVIDER_REQUEST_TIMEOUT",
            "LLM_REQUEST_TIMEOUT",
            "provider_request_timeout",
        ),
    )
    provider_max_retries: int = Field(
        default=0,
        validation_alias=AliasChoices("LLM_PROVIDER_MAX_RETRIES", "provider_max_retries"),
    )
    max_concurrent: int | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_MAX_CONCURRENT", "max_concurrent"),
    )
    http_max_connections: int | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_HTTP_MAX_CONNECTIONS", "http_max_connections"),
    )
    reasoning_effort: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_REASONING_EFFORT", "reasoning_effort"),
    )
    incomplete_output_max_tokens: int = Field(
        default=65536,
        validation_alias=AliasChoices(
            "LLM_INCOMPLETE_OUTPUT_MAX_TOKENS", "incomplete_output_max_tokens"
        ),
    )

    # Secondary typed callers use the same provider factory, but historically
    # kept their own environment knobs.  Keep those knobs in this snapshot so
    # a worker cannot combine one provider connection with another task's
    # stale model/budget.
    flash_model_name: str = Field(
        default="MiniMax-M2.7-highspeed",
        validation_alias=AliasChoices("FLASH_MODEL_NAME", "flash_model_name"),
    )
    flash_model_max_tokens: int = Field(
        default=500,
        validation_alias=AliasChoices(
            "FLASH_MODEL_MAX_TOKENS", "flash_model_max_tokens"
        ),
    )
    flash_model_temperature: float = Field(
        default=0.3,
        validation_alias=AliasChoices(
            "FLASH_MODEL_TEMPERATURE", "flash_model_temperature"
        ),
    )
    gis_explore_llm_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "GIS_EXPLORE_LLM_ENABLED", "gis_explore_llm_enabled"
        ),
    )
    gis_explore_model: str = Field(
        default="MiniMax-M2.7-highspeed",
        validation_alias=AliasChoices("GIS_EXPLORE_MODEL", "gis_explore_model"),
    )
    gis_explore_max_tokens: int = Field(
        default=1200,
        validation_alias=AliasChoices(
            "GIS_EXPLORE_MAX_TOKENS", "gis_explore_max_tokens"
        ),
    )
    gis_explore_temperature: float = Field(
        default=0.1,
        validation_alias=AliasChoices(
            "GIS_EXPLORE_TEMPERATURE", "gis_explore_temperature"
        ),
    )
    source_semantic_llm_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "SOURCE_SEMANTIC_LLM_ENABLED", "source_semantic_llm_enabled"
        ),
    )
    ground_llm_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("GROUND_LLM_ENABLED", "ground_llm_enabled"),
    )
    disable_ground_llm: bool = Field(
        default=False,
        validation_alias=AliasChoices("DISABLE_GROUND_LLM", "disable_ground_llm"),
    )
    disable_ground_report_llm: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "DISABLE_GROUND_REPORT_LLM", "disable_ground_report_llm"
        ),
    )
    disable_llm: bool = Field(
        default=False,
        validation_alias=AliasChoices("DISABLE_LLM", "disable_llm"),
    )
    ground_call_timeout_s: float = Field(
        default=60.0,
        validation_alias=AliasChoices(
            "GROUND_LLM_CALL_TIMEOUT_S", "ground_call_timeout_s"
        ),
    )
    ground_max_calls: int = Field(
        default=16,
        validation_alias=AliasChoices("GROUND_MAX_LLM_CALLS", "ground_max_calls"),
    )
    ground_max_recovery_rounds: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "GROUND_MAX_RECOVERY_ROUNDS", "ground_max_recovery_rounds"
        ),
    )
    ground_query_spec_max_tokens: int = Field(
        default=1200,
        validation_alias=AliasChoices(
            "GROUND_QUERY_SPEC_MAX_TOKENS", "ground_query_spec_max_tokens"
        ),
    )
    ground_max_tokens: int = Field(
        default=4000,
        validation_alias=AliasChoices(
            "GROUND_LLM_MAX_TOKENS", "ground_max_tokens"
        ),
    )
    ground_parse_retries: int = Field(
        default=0,
        validation_alias=AliasChoices(
            "GROUND_LLM_PARSE_RETRIES", "ground_parse_retries"
        ),
    )
    rag_dashscope_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "RAG_DASHSCOPE_ENABLED", "rag_dashscope_enabled"
        ),
    )
    embedding_model: str = Field(
        default="text-embedding-v4",
        validation_alias=AliasChoices(
            "ALIYUN_EMBEDDING_MODEL", "embedding_model"
        ),
    )
    embedding_dimensions: int = Field(
        default=1024,
        validation_alias=AliasChoices(
            "EMBEDDING_DIMENSIONS", "embedding_dimensions"
        ),
    )
    embedding_max_concurrent: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "EMBEDDING_MAX_CONCURRENT", "embedding_max_concurrent"
        ),
    )
    embedding_rate_limit_rps: float = Field(
        default=25.0,
        validation_alias=AliasChoices(
            "EMBEDDING_RATE_LIMIT_RPS", "embedding_rate_limit_rps"
        ),
    )

    l1_max_tokens: int = Field(
        default=32768,
        validation_alias=AliasChoices("L1_MAX_TOKENS", "l1_max_tokens"),
    )
    l1_observe_max_tokens: int = Field(
        default=6144,
        validation_alias=AliasChoices(
            "L1_OBSERVE_MAX_TOKENS", "l1_observe_max_tokens"
        ),
    )
    l1_report_max_tokens: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "L1_REPORT_MAX_TOKENS", "l1_report_max_tokens"
        ),
    )
    l1_timeout_s: float = Field(
        default=480.0,
        validation_alias=AliasChoices("L1_LLM_TIMEOUT_S", "l1_timeout_s"),
    )
    l1_transient_retries: int = Field(
        default=1,
        validation_alias=AliasChoices("L1_TRANSIENT_RETRIES", "l1_transient_retries"),
    )
    l1_transient_retry_backoff_s: float | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "L1_TRANSIENT_RETRY_BACKOFF_S", "l1_transient_retry_backoff_s"
        ),
    )
    l2_max_tokens: int | None = Field(
        default=None,
        validation_alias=AliasChoices("L2_MAX_TOKENS", "l2_max_tokens"),
    )
    l2_report_max_tokens: int | None = Field(
        default=None,
        validation_alias=AliasChoices("L2_REPORT_MAX_TOKENS", "l2_report_max_tokens"),
    )
    l3_max_tokens: int | None = Field(
        default=None,
        validation_alias=AliasChoices("L3_MAX_TOKENS", "l3_max_tokens"),
    )
    l3_report_max_tokens: int | None = Field(
        default=None,
        validation_alias=AliasChoices("L3_REPORT_MAX_TOKENS", "l3_report_max_tokens"),
    )
    l3_provider_parse_retries: int = Field(
        default=0,
        validation_alias=AliasChoices(
            "L3_PROVIDER_PARSE_RETRIES", "l3_provider_parse_retries"
        ),
    )
    l3_transient_retries: int = Field(
        default=0,
        validation_alias=AliasChoices("L3_TRANSIENT_RETRIES", "l3_transient_retries"),
    )
    l3_transient_retry_backoff_s: float = Field(
        default=2.0,
        validation_alias=AliasChoices(
            "L3_TRANSIENT_RETRY_BACKOFF_S", "l3_transient_retry_backoff_s"
        ),
    )
    l3_incomplete_output_max_tokens: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "L3_INCOMPLETE_OUTPUT_MAX_TOKENS", "l3_incomplete_output_max_tokens"
        ),
    )
    node_transient_retries: int = Field(
        default=0,
        validation_alias=AliasChoices(
            "LLM_NODE_TRANSIENT_RETRIES", "node_transient_retries"
        ),
    )
    provider_circuit_failure_threshold: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "LLM_PROVIDER_CIRCUIT_FAILURE_THRESHOLD",
            "provider_circuit_failure_threshold",
        ),
    )

    l1_max_concurrent: int | None = Field(
        default=None,
        validation_alias=AliasChoices("L1_LLM_MAX_CONCURRENT", "l1_max_concurrent"),
    )
    l2_max_concurrent: int | None = Field(
        default=None,
        validation_alias=AliasChoices("L2_LLM_MAX_CONCURRENT", "l2_max_concurrent"),
    )
    l3_max_concurrent: int | None = Field(
        default=None,
        validation_alias=AliasChoices("L3_LLM_MAX_CONCURRENT", "l3_max_concurrent"),
    )
    ground_max_concurrent: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GROUND_LLM_MAX_CONCURRENT", "ground_max_concurrent"
        ),
    )

    @field_validator("provider")
    @classmethod
    def _normalize_provider(cls, value: str) -> str:
        return normalize_provider_name(value)

    @field_validator("structured_mode")
    @classmethod
    def _normalize_mode(cls, value: str) -> str:
        return normalize_structured_mode(value)

    @field_validator(
        "max_tokens",
        "provider_max_retries",
        "incomplete_output_max_tokens",
        "max_concurrent",
        "http_max_connections",
        "l1_max_concurrent",
        "l2_max_concurrent",
        "l3_max_concurrent",
        "ground_max_concurrent",
        "l1_max_tokens",
        "l1_observe_max_tokens",
        "l1_report_max_tokens",
        "l1_transient_retries",
        "l2_max_tokens",
        "l2_report_max_tokens",
        "l3_max_tokens",
        "l3_report_max_tokens",
        "l3_provider_parse_retries",
        "l3_transient_retries",
        "l3_incomplete_output_max_tokens",
        "node_transient_retries",
        "provider_circuit_failure_threshold",
        "flash_model_max_tokens",
        "gis_explore_max_tokens",
        "ground_max_calls",
        "ground_max_recovery_rounds",
        "ground_query_spec_max_tokens",
        "ground_max_tokens",
        "ground_parse_retries",
        "embedding_dimensions",
        "embedding_max_concurrent",
    )
    @classmethod
    def _validate_nonnegative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("LLM numeric settings must be non-negative")
        return value

    @field_validator(
        "stream_timeout",
        "provider_request_timeout",
        "l1_timeout_s",
        "l1_transient_retry_backoff_s",
        "l3_transient_retry_backoff_s",
        "flash_model_temperature",
        "gis_explore_temperature",
        "ground_call_timeout_s",
        "embedding_rate_limit_rps",
    )
    @classmethod
    def _validate_nonnegative_float(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("LLM duration settings must be non-negative")
        return value

    def resolved_provider(self, explicit: str | None = None) -> LLMProviderName:
        return LLMProviderName(normalize_provider_name(explicit or self.provider))

    def connection(self, provider: str | LLMProviderName | None = None) -> LLMConnection:
        selected = self.resolved_provider(
            provider.value if isinstance(provider, LLMProviderName) else provider
        )
        if selected is LLMProviderName.MINIMAX:
            return LLMConnection(
                provider=selected,
                model=self.minimax_model,
                api_key=self.minimax_api_key,
                base_url=self.minimax_api_base,
            )
        if selected is LLMProviderName.OPENCODE_GO:
            return LLMConnection(
                provider=selected,
                model=self.opencode_go_model.removeprefix("opencode-go/"),
                api_key=self.opencode_go_api_key,
                base_url=self.opencode_go_api_base,
            )
        if selected is LLMProviderName.ZHIPUAI:
            return LLMConnection(
                provider=selected,
                model=self.llm_model,
                api_key=self.zhipuai_api_key,
                base_url=self.zhipuai_api_base,
            )
        if selected is LLMProviderName.DASHSCOPE:
            return LLMConnection(
                provider=selected,
                model=self.llm_model,
                api_key=self.dashscope_api_key,
                base_url=self.dashscope_api_base,
            )
        return LLMConnection(
            provider=LLMProviderName.OPENAI,
            model=self.llm_model,
            api_key=self.openai_api_key,
            base_url=self.openai_api_base or "https://api.openai.com/v1",
        )

    def typed_mode(self, provider: str | None = None) -> LLMStructuredMode:
        configured = normalize_structured_mode(self.structured_mode)
        if not str(self.structured_mode or "").strip():
            configured = LLMStructuredMode.TOOLS.value
        selected_provider = normalize_provider_name(provider or self.provider)
        if selected_provider == LLMProviderName.OPENCODE_GO.value:
            if configured == LLMStructuredMode.JSON_SCHEMA.value:
                # The active adapter is Instructor over OpenAI Chat
                # Completions.  OpenCode Go does not publish a model-specific
                # constrained-decoding guarantee for the JSON-Schema shape;
                # its supported, portable response contract is JSON object
                # content.  Keep exact Pydantic and closed-set validation
                # local instead of treating an accepted request as proof that
                # the upstream model enforced the schema.
                return LLMStructuredMode.JSON
        return LLMStructuredMode(configured)

    def opencode_go_thinking_payload(self) -> dict[str, str]:
        """Return the thinking control supported by the configured Go model.

        OpenCode Go is an OpenAI-compatible route, not a uniform model
        capability.  DeepSeek V4 accepts disabled thinking, while GLM-5.x
        rejects it and requires thinking to be enabled.  Keeping this choice
        beside the model connection prevents every caller from inventing a
        provider-wide flag that is invalid for one of the configured models.
        """

        model = str(self.connection("opencode-go").model or "").strip().lower()
        if model.startswith("glm-5") or model.startswith("glm5"):
            return {"type": "enabled"}
        return {"type": "disabled"}

    def opencode_go_reasoning_effort(self) -> str | None:
        """Return a valid reasoning level when the configured Go model needs one."""

        model = str(self.connection("opencode-go").model or "").strip().lower()
        if model.startswith("glm-5") or model.startswith("glm5"):
            configured = str(self.reasoning_effort or "").strip().lower()
            return configured if configured in {"low", "high", "max"} else "max"
        return None

    def request_timeout_seconds(self) -> float:
        return float(
            self.provider_request_timeout
            if self.provider_request_timeout is not None
            else self.stream_timeout
        )

    def ground_llm_is_disabled(self, *, report: bool = False) -> bool:
        """Return the shared opt-in/disable decision for grounding callers."""

        if not self.ground_llm_enabled or self.disable_ground_llm or self.disable_llm:
            return True
        return bool(report and self.disable_ground_report_llm)

    def provider_concurrency(self) -> int:
        if self.max_concurrent is not None:
            return max(1, int(self.max_concurrent))
        return 12 if self.provider == LLMProviderName.OPENCODE_GO.value else 8

    def stage_concurrency(self, stage: str) -> int:
        value = getattr(self, f"{str(stage).strip().lower()}_max_concurrent", None)
        return max(1, int(value)) if value is not None else self.provider_concurrency()

    def stage_policy(self, stage: str) -> LLMStagePolicy:
        """Resolve one stage's complete typed-call budget from this snapshot."""

        normalized = str(stage or "").strip().lower()
        if normalized == "l1":
            configured_backoff = self.l1_transient_retry_backoff_s
            return LLMStagePolicy(
                timeout_s=max(0.001, float(self.l1_timeout_s)),
                max_tokens=max(1, int(self.l1_max_tokens)),
                observe_max_tokens=max(
                    1024,
                    min(int(self.l1_observe_max_tokens), int(self.l1_max_tokens)),
                ),
                report_max_tokens=max(
                    1,
                    int(self.l1_report_max_tokens)
                    if self.l1_report_max_tokens is not None
                    else min(int(self.l1_max_tokens), 4096),
                ),
                max_concurrent=self.stage_concurrency("l1"),
                parse_retries=1,
                transient_retries=max(0, int(self.l1_transient_retries)),
                transient_retry_backoff_s=max(
                    0.0,
                    float(
                        configured_backoff
                        if configured_backoff is not None
                        else (8.0 if self.provider == LLMProviderName.MINIMAX.value else 3.0)
                    ),
                ),
                incomplete_output_max_tokens=max(
                    int(self.l1_max_tokens), int(self.incomplete_output_max_tokens)
                ),
            )
        if normalized == "l2":
            max_tokens = max(
                1,
                int(self.l2_max_tokens)
                if self.l2_max_tokens is not None
                else min(int(self.max_tokens), 12288),
            )
            report_max_tokens = max(
                1,
                int(self.l2_report_max_tokens)
                if self.l2_report_max_tokens is not None
                else min(int(self.max_tokens), 4096),
            )
            return LLMStagePolicy(
                timeout_s=max(0.001, self.request_timeout_seconds()),
                max_tokens=max_tokens,
                report_max_tokens=report_max_tokens,
                max_concurrent=self.stage_concurrency("l2"),
                parse_retries=1,
                transient_retries=0,
                transient_retry_backoff_s=0.0,
                incomplete_output_max_tokens=max(
                    max_tokens, int(self.incomplete_output_max_tokens)
                ),
            )
        if normalized == "l3":
            max_tokens = max(
                1,
                int(self.l3_max_tokens)
                if self.l3_max_tokens is not None
                else min(int(self.max_tokens), 12288),
            )
            report_max_tokens = max(
                1,
                int(self.l3_report_max_tokens)
                if self.l3_report_max_tokens is not None
                else min(int(self.max_tokens), 4096),
            )
            incomplete_max_tokens = (
                int(self.l3_incomplete_output_max_tokens)
                if self.l3_incomplete_output_max_tokens is not None
                else max_tokens
            )
            return LLMStagePolicy(
                timeout_s=max(0.001, self.request_timeout_seconds()),
                max_tokens=max_tokens,
                report_max_tokens=report_max_tokens,
                max_concurrent=self.stage_concurrency("l3"),
                parse_retries=max(0, int(self.l3_provider_parse_retries)),
                transient_retries=max(0, int(self.l3_transient_retries)),
                transient_retry_backoff_s=max(
                    0.0, float(self.l3_transient_retry_backoff_s)
                ),
                incomplete_output_max_tokens=max(
                    max_tokens, incomplete_max_tokens
                ),
            )
        raise ValueError(f"unknown LLM stage: {stage!r}")


def get_llm_settings() -> LLMRuntimeSettings:
    """Load one typed settings snapshot for the current process environment."""

    return LLMRuntimeSettings()


__all__ = [
    "LLMConnection",
    "LLMStagePolicy",
    "LLMProviderName",
    "LLMRuntimeSettings",
    "LLMStructuredMode",
    "get_llm_settings",
    "normalize_provider_name",
    "normalize_structured_mode",
]
