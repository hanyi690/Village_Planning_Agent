"""LLM provider adapters used by workflow stages."""

from .manager import (
    LLMCallRecord,
    LLMCallSpec,
    LLMContextOverflow,
    LLMManager,
    get_llm_manager,
)
from app.infrastructure.context_runtime.table_renderer import (
    render_dependency_table,
    render_table,
    table_cell,
)

__all__ = [
    "LLMCallRecord",
    "LLMCallSpec",
    "LLMContextOverflow",
    "LLMManager",
    "PlanningClaimGenerator",
    "get_llm_manager",
    "get_planning_claim_generator",
    "render_table",
    "table_cell",
    "render_dependency_table",
]


def __getattr__(name: str):
    if name in {"PlanningClaimGenerator", "get_planning_claim_generator"}:
        from .planning_claims import PlanningClaimGenerator, get_planning_claim_generator

        return {
            "PlanningClaimGenerator": PlanningClaimGenerator,
            "get_planning_claim_generator": get_planning_claim_generator,
        }[name]
    raise AttributeError(name)
