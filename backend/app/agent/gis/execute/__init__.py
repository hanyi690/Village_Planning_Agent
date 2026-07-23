"""EXECUTE_OPS Agent subgraph — Phase 2.5 reserved.

ReAct subgraph that adaptively decides spatial operations:
  - 3-layered conflict resolution (priority → preference → spatial)
  - LLM-driven tool selection from tools/gis_execute/
  - Auto-retry with MIP optimization on allocation failure

See: docs/gis/proposals/03_TOOL_FIRST_ARCHITECTURE.md §4
"""
