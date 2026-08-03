"""EXECUTE Agent subpackage - spatial execution layer.

Peer to parse/ - consumes PARSE intent + KG context, produces spatial
layout results (allocated zones, facilities, axes, roads).

Sub-tasks (each a sub-directory under execute/):
  layout/   - zone allocation + function zone generation
  facility/ - facility point placement
  axis/     - development axis generation
  road/     - staged road planning with deterministic fallback

Architecture:
  route_tasks -> layout -> facility -> axis -> road -> validate
  Worker-Evaluator retry loop on validation failure (max 3 rounds)

Current status: all seven nodes are wired into the top-level GIS pipeline.
Declared sub-task failures are collected in execution_errors and the
validation gate blocks export and L4 writes.
"""

from .state import ExecuteAgentState
from .agent import build_execute_agent_graph

__all__ = ["ExecuteAgentState", "build_execute_agent_graph"]
