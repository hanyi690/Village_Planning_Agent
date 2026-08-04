from __future__ import annotations

from typing import Any, Protocol


class GazetteerPort(Protocol):
    def resolve_place_name(self, run_id: str, name: str) -> dict[str, Any] | None: ...
    def get_cluster_by_name(self, run_id: str, cluster_name: str) -> dict[str, Any] | None: ...
