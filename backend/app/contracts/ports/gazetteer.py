"""Gazetteer port - village-name to spatial entity resolution boundary.

Implemented by kg-side adapters (KG gazetteer) and consumed by agent layers.
"""
from __future__ import annotations

from typing import Any, Protocol

from app.modules.schema.contracts.gazetteer_contracts import GazetteerEntryLike


class GazetteerPort(Protocol):
    def resolve_place_name(self, run_id: str, name: str) -> dict[str, Any] | None: ...
    def get_cluster_by_name(self, run_id: str, cluster_name: str) -> dict[str, Any] | None: ...
    def resolve(self, run_id: str, name: str, fuzzy: bool = False) -> GazetteerEntryLike | None: ...


__all__ = ["GazetteerPort"]
