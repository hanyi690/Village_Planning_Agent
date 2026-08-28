"""Provider-aware adapter for the non-executable L3 claims contract.

The planning workflow owns the meaning of ``PlanningClaimSet``.  This adapter
owns how a configured provider returns that contract.  MiniMax M2.x exposes
function/tool calling through its OpenAI-compatible API; it does not expose
the JSON-schema response format used by ``method='json_schema'``.
"""

from __future__ import annotations

import logging
import json
import threading
from typing import Any, Sequence

from pydantic import ValidationError

from app.core.llm_config import get_llm_settings
from app.infrastructure.structured_runtime.facade import LLMCallSpec, run_structured
from app.infrastructure.structured_runtime.parser import (
    provider_failure_code,
    structured_failure_code,
    structured_failure_kind,
    structured_failure_observation,
)


logger = logging.getLogger(__name__)


def _claim_counts(result: Any) -> dict[str, int | None]:
    claims = getattr(result, "claims", None)
    if not isinstance(claims, list):
        return {"emitted": None, "accepted": None, "quarantined": None}
    count = len(claims)
    return {"emitted": count, "accepted": count, "quarantined": 0}


def _log_claim_observation(observation: dict[str, Any], *, level: str) -> None:
    logger_method = getattr(logger, level)
    logger_method(
        "[planning_claims] output_observation=%s",
        json.dumps(
            observation,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


class PlanningClaimGenerator:
    """Generate and validate one evidence-bearing claim set."""

    def __init__(self) -> None:
        self._llm: Any | None = None

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
    ) -> Any:
        """Run one bounded provider call for one semantic projection only."""

        stage_policy = get_llm_settings().stage_policy("l3")
        configured_max_tokens = max(256, stage_policy.max_tokens)
        incomplete_output_max_tokens = max(
            configured_max_tokens,
            stage_policy.incomplete_output_max_tokens,
        )
        retry_count = stage_policy.parse_retries
        transient_retries = stage_policy.transient_retries
        transient_retry_backoff_s = stage_policy.transient_retry_backoff_s
        last_error: Exception | None = None
        for attempt in range(retry_count + 1):
            try:
                feedback_text = ""
                if validation_feedback:
                    feedback_text = (
                        "\nCorrect only these deterministic closed-set findings; "
                        "do not add new claims or report content:\n- "
                        + "\n- ".join(
                            str(item).strip()[:300]
                            for item in validation_feedback[:8]
                            if str(item).strip()
                        )
                    )
                retry_text = ""
                if attempt > 0 and last_error is not None:
                    retry_text = (
                        "\nL3 claims repair: fix only the typed validation paths below; "
                        "return the same narrow claims contract and no report text:\n"
                        + str(last_error)[:1200]
                    )
                result = await run_structured(
                    LLMCallSpec(
                        stage="L3",
                        contract_key="l3.claims",
                        response_model=response_model,
                        call_type="semantic",
                        # The caller owns the only semantic reask.  Do not let
                        # Instructor replay the same invalid structured request
                        # before the failure reaches the quality boundary.
                        max_retries=0,
                        timeout_s=stage_policy.timeout_s,
                        max_tokens=configured_max_tokens,
                        incomplete_output_max_tokens=incomplete_output_max_tokens,
                        max_concurrent=stage_policy.max_concurrent,
                        semaphore_scope="l3",
                        transient_retries=transient_retries,
                        transient_retry_backoff_s=transient_retry_backoff_s,
                        temperature=0.1,
                        allow_content_json=True,
                        timeout_includes_queue=False,
                    ),
                    [
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": instruction + retry_text + feedback_text,
                        },
                    ],
                    llm=self._get_llm(),
                    context={"projection": "claims"},
                )
                if result is None:
                    error = ValueError(
                        "L3 structured provider returned no typed projection"
                    )
                    setattr(error, "structured_failure_code", "TOOL_CALL_MISSING")
                    raise error
                if isinstance(result, response_model):
                    return result
                return response_model.model_validate(result)
            except Exception as exc:
                failure_code = structured_failure_code(exc)
                if failure_code == "TIMEOUT":
                    raise
                if failure_code and not isinstance(exc, ValidationError):
                    error = ValueError(
                        f"L3 structured output failed: {failure_code}"
                    )
                    setattr(error, "structured_failure_code", failure_code)
                    raise error from exc
                last_error = exc
                if attempt >= retry_count:
                    raise
        assert last_error is not None
        raise last_error

    async def generate_claims(
        self,
        prompt: str,
        *,
        source_fact_ids: Sequence[str],
        spatial_source_fact_ids: Sequence[str],
        allowed_evidence_refs: Sequence[str] = (),
        validation_feedback: list[str] | None = None,
    ) -> Any:
        """Generate only typed L3 rough claims; summary is a later call."""

        # Evidence refs are closed by the L3 business boundary after the
        # provider response is parsed.  Keep the catalog in this adapter's
        # contract so the shared runtime and the L3 worker cannot drift into
        # incompatible call shapes; it is intentionally not expanded into
        # the provider JSON schema.
        del allowed_evidence_refs

        response_model = _dynamic_claim_output_model(
            source_fact_ids,
            spatial_source_fact_ids,
        )

        try:
            result = await self._generate_projection(
                response_model,
                prompt,
                instruction=(
                    "Return only the complete structured claims array. Do not return "
                    "summary_body, Markdown, explanations, coordinates, BSM IDs or geometry."
                ),
                validation_feedback=validation_feedback,
            )
            _log_claim_observation(
                {
                    "contract": "l3.claims",
                    "failure_code": None,
                    "failure_kind": None,
                    "status": "accepted",
                    "claim_counts": _claim_counts(result),
                },
                level="info",
            )
            return result
        except Exception as exc:
            failure_code = structured_failure_code(exc)
            failure_kind = structured_failure_kind(exc)
            if failure_kind == "provider_infrastructure" or provider_failure_code(exc) is not None:
                observation = structured_failure_observation(exc)
                observation.update(
                    {
                        "status": "provider_failure",
                        "claim_counts": {
                            "emitted": None,
                            "accepted": 0,
                            "quarantined": 0,
                        },
                    }
                )
                _log_claim_observation(observation, level="error")
                raise
            if failure_kind != "recoverable_schema":
                observation = structured_failure_observation(exc)
                observation["status"] = "unclassified_failure"
                _log_claim_observation(observation, level="error")
                raise
            observation = structured_failure_observation(exc)
            emitted = observation.get("claims_emitted")
            observation.update(
                {
                    "status": "quarantined",
                    "claim_counts": {
                        "emitted": emitted,
                        "accepted": 0,
                        "quarantined": emitted,
                    },
                }
            )
            _log_claim_observation(observation, level="warning")
            return response_model(
                claims=[],
                diagnostics=["provider_claims_quarantined_validation_error"],
            )

_GENERATOR: PlanningClaimGenerator | None = None
_GENERATOR_LOCK = threading.Lock()


def _dynamic_claim_output_model(
    source_fact_ids: Sequence[str],
    spatial_source_fact_ids: Sequence[str],
) -> type[Any]:
    """Return one stable provider wire schema for every invocation.

    Runtime fact IDs and relation choices are deliberately not expanded into
    the JSON schema.  They are closed locally after parsing against the
    current catalog.  Keeping one model identity also prevents provider
    schema caches from seeing a new contract name for every catalog digest.
    """

    from app.modules.l3.claim_generation import L3RoughClaimOutput

    del source_fact_ids, spatial_source_fact_ids
    return L3RoughClaimOutput

def get_planning_claim_generator() -> PlanningClaimGenerator:
    global _GENERATOR
    if _GENERATOR is None:
        with _GENERATOR_LOCK:
            if _GENERATOR is None:
                _GENERATOR = PlanningClaimGenerator()
    return _GENERATOR


__all__ = ["PlanningClaimGenerator", "get_planning_claim_generator"]
