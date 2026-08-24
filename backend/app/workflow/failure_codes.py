"""Shared workflow failure classifications.

These codes describe bounded, recoverable provider/dimension failures.  Keep
the definition independent from graph modules so routing and HITL preparation
cannot drift or create an import cycle.
"""

from __future__ import annotations


TRANSIENT_LLM_FAILURE_CODES = frozenset(
    {
        "llm_stream_timeout",
        "llm_timeout",
        "llm_provider_error",
        "llm_provider_circuit_open",
        "llm_typed_output_error",
        "dimension_quality_failed",
        # Typed provider contracts expose these bounded classifications so
        # retry/HITL routing does not collapse truncation and tool omissions
        # into a generic output error.
        "CONTEXT_OVERFLOW",
        "OUTPUT_TRUNCATED",
        "TOOL_CALL_MISSING",
        "SCHEMA_INVALID",
        "TIMEOUT",
    }
)


__all__ = ["TRANSIENT_LLM_FAILURE_CODES"]
