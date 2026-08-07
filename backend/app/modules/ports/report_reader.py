from __future__ import annotations

from typing import Any, Dict, Protocol


class ReportReaderPort(Protocol):
    """Read access to persisted layer reports.

    Derived from the exact reader methods exercised by ``app/modules`` call
    sites (see ``docs/audit/port-call-sites.md``). No writer methods are
    included here; writing is confined to the services/agent layer.
    """

    async def get_layer_reports(
        self, session_id: str, layer: int
    ) -> Dict[str, str]: ...

    async def get_layer_reports_with_sources(
        self, session_id: str, layer: int
    ) -> Dict[str, Dict[str, Any]]: ...

    async def get_layer_summaries(
        self, session_id: str, layer: int
    ) -> Dict[str, Dict[str, Any]]: ...