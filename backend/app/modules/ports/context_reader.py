from __future__ import annotations

from typing import Any, Optional, Protocol


class ContextReaderPort(Protocol):
    """Read access to the frozen in-process planning context.

    The KG enrichment module only needs to retrieve the cached context object
    (it never builds one). ``get_cached_context`` returns the authoritative
    ``PlanningContext`` for a session or ``None`` when not yet built.
    """

    def get_cached_context(self, session_id: str) -> Optional[Any]: ...