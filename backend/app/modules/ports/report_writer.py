from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol


class ReportWriterPort(Protocol):
    """Write access for persisting layer reports.

    Declared for dependency-inversion completeness. No current ``app/modules``
    call site invokes a writer method; writing is handled by the services/agent
    layer. The signature mirrors the concrete ``ReportStore.save`` contract.
    """

    async def save(
        self,
        session_id: str,
        dim_key: str,
        version: int,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        layer: int = 1,
        knowledge_sources: Optional[List[Dict[str, Any]]] = None,
        gis_data: Optional[List[Dict[str, Any]]] = None,
    ) -> str: ...