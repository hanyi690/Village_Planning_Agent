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

    async def _generate_projection(
        self,
        response_model: Any,
        prompt: str,
        *,
        instruction: str,
        validation_feedback: list[str] | None = None,
        content_fallback_mode: str = "strict",
    ) -> Any:
        """Run one bounded provider call for one semantic projection only."""

        await asyncio.wait_for(self._slots.acquire(), timeout=LLM_STREAM_TIMEOUT)
        try:
            retry_count = max(0, int(os.getenv("L3_PROVIDER_PARSE_RETRIES", "0")))
            last_error: Exception | None = None
            for attempt in range(retry_count + 1):
                try:
                    feedback_text = ""
                    if validation_feedback:
                        feedback_text = (
                            "\nRepair only these deterministic validation findings; "
                            "do not add new claims or report content:\n- "
                            + "\n- ".join(validation_feedback[:40])
                        )
                    retry_text = ""
                    if attempt > 0 and last_error is not None:
                        retry_text = (
                            "\nThe previous structured arguments were invalid. Return only "
                            "valid arguments for the declared response model:\n"
                            + str(last_error)[:6000]
                        )
                    result = await run_structured_output(
                        response_model,
                        [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": instruction + retry_text + feedback_text},
                        ],
                        max_retries=1,
                        timeout=float(LLM_STREAM_TIMEOUT),
                        temperature=0.1,
                        llm=self._get_llm(),
                        content_fallback_mode=content_fallback_mode,
                        max_concurrent=self._max_concurrent,
                        semaphore_scope="l3",
                    )
                    if result is None:
                        return response_model()
                    if isinstance(result, response_model):
                        return result
                    return response_model.model_validate(result)
                except (ValidationError, TypeError, ValueError) as exc:
                    last_error = exc
                    if attempt >= retry_count:
                        raise
            assert last_error is not None
            raise last_error
        finally:
            self._slots.release()

    async def generate_claims(
        self,
        prompt: str,
        *,
        validation_feedback: list[str] | None = None,
    ) -> Any:
        """Generate only typed L3 claims; report synthesis is a later call."""

        from app.domain.program.claim_draft import L3ClaimOutput

        return await self._generate_projection(
            L3ClaimOutput,
            prompt,
            instruction=(
                "Return only the complete structured claims array. Do not return "
                "report_body, Markdown, explanations, coordinates, BSM IDs or geometry."
            ),
            validation_feedback=validation_feedback,
        )

    async def generate_report(
        self,
        prompt: str,
        *,
        validation_feedback: list[str] | None = None,
    ) -> Any:
        """Synthesize only the human L3 report from already validated claims."""

        from app.domain.program.claim_draft import L3ReportOutput

        return await self._generate_projection(
            L3ReportOutput,
            prompt,
            instruction=(
                "Return only report_body as a human-readable planning report. "
                "Do not create or change claims, targets, locations, geometry, quantities "
                "or source facts; do not return a claims array."
            ),
            validation_feedback=validation_feedback,
            content_fallback_mode="report_text",
        )


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
