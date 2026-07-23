"""EXECUTE_OPS Agent tools — Phase 2.5 reserved.

Tools for the EXECUTE_OPERATIONS ReAct subgraph:
  - resolve_place_name: 地名解析 → 候选图斑
  - check_compliance: 合规预检 (reuses _conflict.py ConflictDetector)
  - edit_parcel: create/split/merge/modify/reclassify
  - lookup_land_use_code: 用途查表 (reuses lookup.py)
  - optimize_allocation: MIP 辅助 (reuses _generation.optimizer)

See: docs/gis/proposals/03_TOOL_FIRST_ARCHITECTURE.md §4
"""
