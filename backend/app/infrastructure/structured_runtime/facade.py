"""Single structured-output capability boundary for business stages.

Business modules define the response model and semantic validation.  This
facade owns the call into the shared LLM policy manager and keeps provider
construction out of those modules.
"""

from __future__ import annotations

from typing import Any

from app.infrastructure.llm.manager import LLMCallSpec
from app.infrastructure.structured_runtime.parser import (
    structured_failure_code,
    structured_failure_summary,
)


async def run_structured(
    spec: LLMCallSpec,
    messages: list[dict[str, Any]],
    *,
    context: dict[str, Any] | None = None,
    llm: Any | None = None,
) -> Any:
    """Execute one bounded structured call through the shared policy manager."""

    from app.infrastructure.llm.manager import get_llm_manager

    return await get_llm_manager().run_structured(
        spec,
        messages,
        context=context,
        llm=llm,
    )


def create_flash_model(*args: Any, **kwargs: Any) -> Any:
    """Construct the configured lightweight provider adapter."""

    from app.infrastructure.llm.factory import create_flash_llm

    return create_flash_llm(*args, **kwargs)


def create_model(*args: Any, **kwargs: Any) -> Any:
    """Construct the configured provider adapter for structured work."""

    from app.infrastructure.llm.factory import create_llm

    return create_llm(*args, **kwargs)


async def run_verified_decision(*args: Any, **kwargs: Any) -> Any:
    """Run a semantically verified proposal through the shared runtime."""

    from app.infrastructure.llm.verified_structured import (
        run_verified_structured_decision,
    )

    return await run_verified_structured_decision(*args, **kwargs)


def get_planning_claim_generator() -> Any:
    """Return the bounded rough-claim provider adapter."""

    from app.infrastructure.llm.planning_claims import (
        get_planning_claim_generator as get_generator,
    )

    return get_generator()


def claim_response_model(
    source_fact_ids: Any,
    spatial_source_fact_ids: Any,
) -> Any:
    """Return the provider wire model for the bounded rough-claim contract."""

    from app.infrastructure.llm.planning_claims import _dynamic_claim_output_model

    return _dynamic_claim_output_model(source_fact_ids, spatial_source_fact_ids)


__all__ = [
    "LLMCallSpec",
    "create_flash_model",
    "create_model",
    "claim_response_model",
    "get_planning_claim_generator",
    "run_structured",
    "run_verified_decision",
    "structured_failure_code",
    "structured_failure_summary",
]
