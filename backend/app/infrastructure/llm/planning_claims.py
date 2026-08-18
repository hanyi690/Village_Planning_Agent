"""Provider-aware adapter for the non-executable L3 claims contract.

The planning workflow owns the meaning of ``PlanningClaimSet``.  This adapter
owns how a configured provider returns that contract.  MiniMax M2.x exposes
function/tool calling through its OpenAI-compatible API; it does not expose
the JSON-schema response format used by ``method='json_schema'``.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any

from pydantic import ValidationError

from app.core.settings import LLM_MAX_CONCURRENT, LLM_STREAM_TIMEOUT
from app.domain.program.claim_draft import L3DimensionOutput
from app.infrastructure.llm.structured import run_structured_output


class PlanningClaimGenerator:
    """Generate and validate one evidence-bearing claim set."""

    def __init__(self) -> None:
        self._llm: Any | None = None
        self._max_concurrent = max(
            1,
            int(os.getenv("L3_LLM_MAX_CONCURRENT", str(LLM_MAX_CONCURRENT))),
        )
        self._slots = asyncio.Semaphore(
            self._max_concurrent
        )

    def _get_llm(self) -> Any | None:
        """Return an injected adapter when tests or a controlled caller provide one."""
        return self._llm

    async def generate(
        self,
        prompt: str,
        *,
        validation_feedback: list[str] | None = None,
    ) -> L3DimensionOutput:
        """Call the provider and return the dual-response report + claims."""

        # Bound semaphore queueing as well as the provider request. LangGraph
        # dispatches dimensions concurrently; waiting behind the local slot
        # must not create an unbounded hidden retry/latency queue.
        await asyncio.wait_for(self._slots.acquire(), timeout=LLM_STREAM_TIMEOUT)
        try:
            retry_count = max(0, int(os.getenv("L3_PROVIDER_PARSE_RETRIES", "0")))
            last_error: Exception | None = None
            for attempt in range(retry_count + 1):
                try:
                    feedback_text = ""
                    if validation_feedback:
                        feedback_text = (
                            "\nThe previous structured result failed deterministic domain validation. "
                            "Repair only the listed claims and return the complete claim set again:\n- "
                            + "\n- ".join(validation_feedback[:40])
                        )
                    provider_error_feedback = ""
                    if attempt > 0 and last_error is not None:
                        provider_error_feedback = (
                            "\nThe previous function arguments violated the declared JSON schema. "
                            "Correct the exact validation errors below; do not invent enum values:\n"
                            + str(last_error)[:6000]
                        )
                    result = await run_structured_output(
                        L3DimensionOutput,
                        [
                            {"role": "system", "content": prompt},
                            {
                                "role": "user",
                                "content": (
                                    "Return the PlanningClaimSet only." + feedback_text
                                    if attempt == 0
                                    else (
                                        "Return valid function arguments only. Use strict JSON: "
                                        "double-quote every key and string, encode nested arrays as "
                                        "arrays, and omit markdown, comments, and trailing commas."
                                        + provider_error_feedback
                                        + feedback_text
                                    )
                                ),
                            },
                        ],
                        max_retries=1,
                        timeout=float(LLM_STREAM_TIMEOUT),
                        temperature=0.1,
                        llm=self._get_llm(),
                        max_concurrent=self._max_concurrent,
                        semaphore_scope="l3",
                    )
                    if result is None:
                        return L3DimensionOutput(report_body="", claims=[])
                    if isinstance(result, L3DimensionOutput):
                        return result
                    return L3DimensionOutput.model_validate(result)
                except (ValidationError, TypeError, ValueError) as exc:
                    last_error = exc
                    if attempt >= retry_count:
                        raise
            assert last_error is not None
            raise last_error
        finally:
            self._slots.release()


_GENERATOR: PlanningClaimGenerator | None = None
_GENERATOR_LOCK = threading.Lock()


def get_planning_claim_generator() -> PlanningClaimGenerator:
    global _GENERATOR
    if _GENERATOR is None:
        with _GENERATOR_LOCK:
            if _GENERATOR is None:
                _GENERATOR = PlanningClaimGenerator()
    return _GENERATOR


__all__ = ["PlanningClaimGenerator", "get_planning_claim_generator"]
