"""PlanningContext — Runtime context for the planning graph.

Separates "runtime configuration" (settings that control graph behavior)
from "graph state" (data produced by nodes). Context is NOT affected by
Send snapshot freezing, making it safe for runtime-switchable settings
like step_mode.

Nodes access context via: runtime: Runtime[PlanningContext]
"""

from dataclasses import dataclass


@dataclass
class PlanningContext:
    step_mode: bool = False
