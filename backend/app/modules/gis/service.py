"""
GIS Service - Unified GIS data fetching with fallback

Design:
- Wraps ToolRegistry with standardized ToolResult
- Automatic fallback handling
- Parallel execution support
- No exceptions thrown, always returns ToolResult
"""

import asyncio
from typing import Any, Dict, List, Optional

from ..tools.protocol import ToolResult  # Unified ToolResult
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# GisService Class
# ==========================================

class GisService:
    """
    GIS Data Fetching Service

    Unified interface for all GIS tools:
    - Standardized ToolResult output
    - Automatic fallback handling
    - Parallel execution
    - Error isolation (never crashes the caller)
    """

    @staticmethod
    async def run(tool_name: str, context: Dict[str, Any]) -> ToolResult:
        """
        Execute a GIS tool with standardized result

        Args:
            tool_name: Tool identifier (e.g., "gis_coverage_calculator")
            context: Execution context with village data, config, etc.

        Returns:
            ToolResult with status, data, error, metadata
        """
        try:
            from ..tools.registry import ToolRegistry

            logger.info(f"[GisService] Executing tool: {tool_name}")

            # Execute tool
            result = ToolRegistry.execute_tool(tool_name, context)

            # Convert to standardized format
            if isinstance(result, dict):
                # Check for error indicators
                if "error" in result or result.get("status") == "error":
                    return ToolResult(
                        status="error",
                        data=None,
                        error=result.get("error", "Unknown error"),
                        metadata=result.get("metadata", {}),
                    )
                return ToolResult(
                    status="success",
                    data=result,
                    error=None,
                    metadata=result.get("metadata", {}),
                )

            # String result (legacy tools)
            if isinstance(result, str):
                if result.startswith("Error") or result.startswith("[执行失败]"):
                    return ToolResult(
                        status="error",
                        data=None,
                        error=result,
                        metadata={},
                    )
                return ToolResult(
                    status="success",
                    data=result,
                    error=None,
                    metadata={},
                )

            # Unknown format
            logger.warning(f"[GisService] Unknown result type: {type(result)}")
            return ToolResult(
                status="partial",
                data=result,
                error=None,
                metadata={"warning": "Non-standard result format"},
            )

        except ImportError as e:
            logger.error(f"[GisService] ToolRegistry unavailable: {e}")
            return ToolResult(
                status="error",
                data=None,
                error=f"ToolRegistry unavailable: {str(e)}",
                metadata={},
            )

        except Exception as e:
            logger.error(f"[GisService] Tool execution failed: {e}")
            return ToolResult(
                status="error",
                data=None,
                error=str(e),
                metadata={"exception_type": type(e).__name__},
            )

    @staticmethod
    async def run_parallel(
        tool_names: List[str],
        context: Dict[str, Any]
    ) -> List[ToolResult]:
        """
        Execute multiple GIS tools in parallel

        Args:
            tool_names: List of tool identifiers
            context: Shared execution context

        Returns:
            List of ToolResult (same order as tool_names)
        """
        tasks = [GisService.run(name, context) for name in tool_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to ToolResult
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(ToolResult(
                    status="error",
                    data=None,
                    error=str(result),
                    metadata={"tool": tool_names[i]},
                ))
            else:
                final_results.append(result)

        return final_results

    @staticmethod
    async def get_boundary(village_name: str) -> Optional[Dict[str, Any]]:
        """
        Get village boundary with fallback

        Args:
            village_name: Village name for boundary lookup

        Returns:
            Boundary GeoJSON or None (never raises exception)
        """
        try:
            from ..tools.geocoding import TiandituProvider

            provider = TiandituProvider()
            result = provider.get_boundary(village_name)

            if result.success:
                return result.data
            logger.warning(f"[GisService] Boundary fallback for: {village_name}")
            return None

        except Exception as e:
            logger.error(f"[GisService] Boundary fetch failed: {e}")
            return None

    @staticmethod
    async def get_village_center(
        village_name: str,
        buffer_km: float = 5.0
    ) -> Optional[tuple]:
        """
        Get village center coordinates with buffer bbox

        Args:
            village_name: Village name
            buffer_km: Buffer distance in kilometers

        Returns:
            (center_lon, center_lat) or None
        """
        try:
            from ..tools.core.gis_data_fetcher import GISDataFetcher

            fetcher = GISDataFetcher()
            center, _ = fetcher.get_village_center(village_name, buffer_km)

            if center:
                return center
            return None

        except Exception as e:
            logger.error(f"[GisService] Center fetch failed: {e}")
            return None


__all__ = ["GisService", "ToolResult"]