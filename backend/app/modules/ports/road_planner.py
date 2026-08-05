"""Road planner port - deterministic road-planning boundary.

Implemented by adapters that wrap the Stage 1-4 road planning services and
consumed by the EXECUTE road-construction worker.  ``plan`` returns a
``RoadPlanResult``; ``is_available`` reports whether routing inputs are present.
"""
from __future__ import annotations

from typing import Any, Protocol


class RoadPlannerPort(Protocol):
    def plan(self, state: Any) -> Any:
        """Execute road planning from agent state and return a RoadPlanResult."""
        ...

    def is_available(self) -> bool:
        """Return True when road inputs are present enough for planning."""
        ...


__all__ = ["RoadPlannerPort"]
