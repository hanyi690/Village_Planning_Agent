"""GIS Service — boundary and center lookups.

Tool execution (run / run_parallel) has been removed — GIS tools are
now executed by the GIS Agent ReAct subgraph (app/agent/gis/).
"""

from typing import Any, Dict, Optional

from app.tools.protocol import ToolResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GisService:

    @staticmethod
    async def get_boundary(village_name: str) -> Optional[Dict[str, Any]]:
        """Get village boundary with fallback (never raises)."""
        try:
            from .providers.tianditu.provider import TiandituProvider

            provider = TiandituProvider()
            result = provider.get_boundary(village_name)

            if result.success:
                return result.data
            logger.warning("[GisService] Boundary fallback for: %s", village_name)
            return None

        except Exception as e:
            logger.error("[GisService] Boundary fetch failed: %s", e)
            return None

    @staticmethod
    async def get_village_center(
        village_name: str,
        buffer_km: float = 5.0,
    ) -> Optional[tuple]:
        """Get village center coordinates with buffer bbox (never raises)."""
        try:
            from .fetcher import GISDataFetcher

            fetcher = GISDataFetcher()
            center, _ = fetcher.get_village_center(village_name, buffer_km)
            return center

        except Exception as e:
            logger.error("[GisService] Center fetch failed: %s", e)
            return None


__all__ = ["GisService", "ToolResult"]
