"""UnresolvedTarget - structured record of a spatial target that could not be placed.

EXPLORE / PARSE / GROUND / SELECT may fail to ground or place a spatial
target for many reasons (gazetteer miss, no constraint-safe parcel, no
candidate, …). Instead of silently dropping it, stages record an
``UnresolvedTarget`` so the failure is auditable and reported back to the
conversation / step report. This is the Phase-1 P0 fix for "禁止静默丢弃".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class UnresolvedTarget(BaseModel):
    """A target that failed grounding/placement, with reason + provenance."""

    target_id: str = ""
    kind: str = ""  # "project" | "zone" | "facility" | "axis" | "road" | "explore"
    name: str = ""
    reason: str = ""  # machine-readable, e.g. "no_candidate" | "all_prohibited"
    detail: str = ""  # human-readable explanation
    attempted_bsms: List[str] = Field(default_factory=list)
    rejected_bsms: List[Dict[str, Any]] = Field(default_factory=list)
    stage: str = ""  # "explore" | "parse" | "ground" | "select" | "execute"
    source_text: str = ""
    provenance: Dict[str, Any] = Field(default_factory=dict)

    def to_trace(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


def collect_unresolved(payload: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    """Read the accumulated ``UnresolvedTarget`` list from a state payload."""
    return list(payload.get(key) or [])


__all__ = ["UnresolvedTarget", "collect_unresolved"]