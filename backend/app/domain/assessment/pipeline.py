"""Unified data pipeline: structured_summary -> ToolRegistry -> professional_data.

The single entry point for all tool execution. Replaces the old dual-path
(_run_gis + get_specialized_data) with one coherent pipeline.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


class DataPipeline:
    """Unified tool execution pipeline.

    Flow:
    1. Read tool config for the dimension (from phases.yaml)
    2. Filter to IMPLEMENTED tools only (STUB tools are skipped)
    3. Build context (inject structured_summary + state data)
    4. Execute each tool via TOOL_REGISTRY (from infrastructure/llm/tools/tools.py)
    5. Aggregate results as professional_data
    6. Single tool failure is isolated (does not affect others)
    """

    def __init__(self) -> None:
        from app.infrastructure.llm.tools.tools import TOOL_REGISTRY
        self._registry = TOOL_REGISTRY

    async def get_professional_data(
        self,
        dimension_key: str,
        summary: Any,
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute tools for a dimension and return aggregated results.

        Args:
            dimension_key: Dimension identifier (e.g. "socio_economic").
            summary: Structured summary object (BaseDimensionSummary subclass).
            state: Current planning state dict for additional context.

        Returns:
            Dict mapping tool_name -> result (typically a formatted string).
        """
        tool_names = self._get_tools_for_dimension(dimension_key)
        if not tool_names:
            return {}

        implemented_tools = self._filter_implemented(tool_names)
        if not implemented_tools:
            return {}

        context = self._build_context(dimension_key, summary, state)
        professional_data: Dict[str, Any] = {}

        for tool_name in implemented_tools:
            try:
                tool_fn = self._registry[tool_name]
                result = await asyncio.to_thread(tool_fn.invoke, context)
                professional_data[tool_name] = result
                logger.info(
                    f"[DataPipeline] {dimension_key}/{tool_name}: success"
                )
            except Exception as e:
                logger.warning(
                    f"[DataPipeline] {dimension_key}/{tool_name}: failed - {e}"
                )

        return professional_data

    def _get_tools_for_dimension(self, dimension_key: str) -> List[str]:
        """Read tool names from dimension config (phases.yaml)."""
        try:
            from app.config import get_dimension_config
            cfg = get_dimension_config(dimension_key)
            return getattr(cfg, "tools", []) or []
        except Exception:
            return []

    def _filter_implemented(self, tool_names: List[str]) -> List[str]:
        """Keep only tools that exist in the TOOL_REGISTRY."""
        implemented = []
        for name in tool_names:
            if name in self._registry:
                implemented.append(name)
            else:
                logger.debug(f"[DataPipeline] Skipping unregistered tool: {name}")
        return implemented

    def _build_context(
        self,
        dimension_key: str,
        summary: Any,
        state: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build tool execution context from summary and state."""
        context: Dict[str, Any] = {
            "structured_summary": summary,
            "dimension_key": dimension_key,
        }
        if state:
            config = state.get("config", {})
            context["project_name"] = state.get("project_name", "")
            try:
                from app.infrastructure.context.planning_context_factory import get_cached_context

                planning_context = get_cached_context(str(state.get("session_id", "")))
                if planning_context is not None:
                    context.update(planning_context.input_texts())
            except Exception:
                pass
            # Pass merged dependency metrics for tool parameter resolution
            dep_metrics = state.get("_dep_metrics")
            if dep_metrics:
                context["_dep_metrics"] = dep_metrics
                context["dep_metrics"] = dep_metrics  # Alias for convenience
        return context
