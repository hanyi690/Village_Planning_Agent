"""EXECUTE Agent subpackage - spatial execution layer.

Peer to parse/ - consumes PARSE intent + KG context, produces spatial
layout results (allocated zones, facilities, axes, roads).

Sub-tasks (each a sub-directory under execute/):
  layout/   - zone allocation + function zone generation
  facility/ - facility point placement
  axis/     - development axis generation
  road/     - planned road network (placeholder)

Architecture:
  route_tasks -> layout -> facility -> axis -> road -> validate
  Worker-Evaluator retry loop on validation failure (max 3 rounds)

Current status (P0): skeleton compiles, nodes are pass-through placeholders.
Not yet wired into the top-level pipeline (layout_pipeline.py still runs the
production allocate_and_generate + validate nodes). See agent.py docstring
for the P0 -> P1 -> P2 migration path.
"""

from .state import ExecuteAgentState
from .agent import build_execute_agent_graph

__all__ = ["ExecuteAgentState", "build_execute_agent_graph"]
