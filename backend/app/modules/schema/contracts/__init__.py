"""Cross-layer data contracts — PARSE, EXECUTE, LAYOUT, and spatial cognition.

This package intentionally does NOT re-export every contract. Each contract lives
in its own module (e.g. ``l1_contracts.py``, ``execution_plan_contracts.py``) and
business code must import from the specific contract file:

    from app.modules.schema.contracts.l1_contracts import L1Snapshot
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan
"""

__all__: list[str] = []
