"""Pipeline output models — Pydantic schemas for tool return values.

These models define the structured output of each pipeline stage tool.
Use llm.with_structured_output(Model) for automatic parsing and validation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


class ConflictItem(BaseModel):
    """Single conflict detected across dimensions."""

    conflict_id: str = ""
    conflict_type: Literal["metric", "constraint", "spatial"] = "metric"
    description: str = ""
    severity: Literal["low", "medium", "high"] = "medium"
    source_a: str = ""
    source_b: str = ""
    resolution_suggestion: str = ""


class ConflictReport(BaseModel):
    """Output of detect_conflicts tool."""

    conflicts: List[ConflictItem] = Field(default_factory=list)
    total_count: int = 0
    by_type: Dict[str, int] = Field(default_factory=dict)
    severity: Literal["none", "low", "medium", "high"] = "none"


class ViolationItem(BaseModel):
    """Single validation violation."""

    check_name: str = ""
    description: str = ""
    actual_value: Any = None
    expected_value: Any = None
    fix_suggestion: str = ""


class ValidationReport(BaseModel):
    """Output of validate_layout tool.

    Used by the Worker-Evaluator pattern: failed validation triggers retry
    with violations injected into the ReAct subgraph's messages.
    """

    passed: bool = False
    violations: List[ViolationItem] = Field(default_factory=list)
    checks_total: int = 8
    checks_passed: int = 0
    retry_suggestions: List[str] = Field(default_factory=list)


class AllocationResult(BaseModel):
    """Output of allocate_zones tool — MIP or greedy allocation result."""

    allocated_geojson: Dict[str, Any] = Field(default_factory=dict)
    allocation_summary: Dict[str, Any] = Field(default_factory=dict)
    mode: Literal["mip", "greedy"] = "mip"
    elapsed_s: float = 0.0
    succeeded: bool = False
    error_message: str = ""


class ExportResult(BaseModel):
    """Output of export_gdb tool — 12-layer GeoPackage + land balance."""

    layers_exported: List[str] = Field(default_factory=list)
    output_dir: str = ""
    land_balance: Dict[str, Any] = Field(default_factory=dict)
    total_layers: int = 0
    succeeded: bool = False
    warnings: List[str] = Field(default_factory=list)


__all__ = [
    "ConflictItem",
    "ConflictReport",
    "ViolationItem",
    "ValidationReport",
    "AllocationResult",
    "ExportResult",
]
