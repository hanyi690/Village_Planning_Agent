"""Provider-neutral contracts for bounded structured LLM execution."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


StructuredPassStatus = Literal[
    "completed",
    "provider_failed",
    "protocol_failed",
    "semantic_failed",
]


class StructuredPassResult(BaseModel):
    """Safe result metadata for one typed provider pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pass_number: int = Field(ge=1)
    status: StructuredPassStatus
    typed_output: Any | None = None
    provider_name: str = ""
    model_id: str = ""
    contract_key: str = ""
    finish_reason: str = ""
    failure_code: str = ""
    failure_kind: str = ""
    response_shape: dict[str, Any] = Field(default_factory=dict)
    reasoning_present: bool = False
    reasoning_channel: str = ""
    reasoning_length: int = Field(default=0, ge=0)
    reasoning_digest: str = ""


class StructuredConsensusResult(BaseModel):
    """Bounded collection of typed passes with no domain adjudication."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal[
        "completed",
        "provider_failed",
        "protocol_failed",
        "semantic_failed",
    ]
    passes: tuple[StructuredPassResult, ...] = ()
    completed_pass_count: int = Field(default=0, ge=0)
    provider_failure_count: int = Field(default=0, ge=0)
    protocol_failure_count: int = Field(default=0, ge=0)
    semantic_failure_count: int = Field(default=0, ge=0)
    contract_key: str = ""


__all__ = [
    "StructuredConsensusResult",
    "StructuredPassResult",
    "StructuredPassStatus",
]
