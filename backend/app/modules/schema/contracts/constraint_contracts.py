"""Constraint compilation contracts — data models for the ConstraintCompiler.

Replaces the silent drop pipeline (PARSE→MIP散转换 + KG→state拍平) with
a single compilation entry point that records every dropped and conflicted item.

v1.0 (2026-07-26):
- CompiledConstraint: single compiled constraint with provenance
- CompilationReport: full audit trail (compiled/dropped/conflicts)
- ConstraintCompiler: compile() entry point

Design: 02_EXECUTION_PLAN.md Module B
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class CompiledConstraint(BaseModel):
    """Single compiled constraint — ready for MIP consumption.

    Every constraint has a provenance chain that traces back to its source,
    enabling full auditability.
    """

    id: str = ""
    scope: Literal["global", "zone", "parcel_set"] = "global"
    zone: Optional[str] = None
    parcel_bsms: Optional[List[str]] = None
    field: str = "area_ha"                             # e.g. "area_ha", "count"
    operator: Literal["<=", ">=", "=="] = "<="
    value: float = 0.0
    hardness: Literal["hard", "soft"] = "hard"
    weight: Optional[float] = None                     # soft 时必填
    source: Literal[
        "parse", "three_line", "vne", "protected",
        "rule_yaml", "feedback",
    ] = "parse"
    provenance: str = ""                                # 原文/规则条目/查询名，可追溯


class DroppedItem(BaseModel):
    """Record of a dropped constraint with reason.

    Drops with reason="unknown" are bugs — every drop must be explained.
    """

    source_item: str = ""
    reason: str = ""
    source: str = ""


class ConflictRecord(BaseModel):
    """Record of a constraint conflict and its resolution.

    When two constraints target the same scope+field, the stricter one wins.
    """

    scope: str = ""
    field: str = ""
    competing_values: List[float] = Field(default_factory=list)
    competing_sources: List[str] = Field(default_factory=list)
    resolved_value: float = 0.0
    resolved_operator: str = "<="
    overridden_items: List[str] = Field(default_factory=list)


class CompilationReport(BaseModel):
    """Full audit report for one compilation run.

    compiled: 成功编译的约束列表（直接进入 MIP）
    dropped:  被丢弃的约束列表（必须填写原因）
    conflicts: 冲突仲裁记录（同 scope+field 保留最严格一条）
    """

    compiled: List[CompiledConstraint] = Field(default_factory=list)
    dropped: List[DroppedItem] = Field(default_factory=list)
    conflicts: List[ConflictRecord] = Field(default_factory=list)

    @property
    def total_input(self) -> int:
        return len(self.compiled) + len(self.dropped)

    @property
    def has_drops(self) -> bool:
        return len(self.dropped) > 0

    @property
    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0

    def summary(self) -> str:
        parts = [
            f"compiled={len(self.compiled)}",
        ]
        if self.dropped:
            parts.append(f"dropped={len(self.dropped)}")
        if self.conflicts:
            parts.append(f"conflicts={len(self.conflicts)}")
        return f"CompilationReport({', '.join(parts)})"


__all__ = [
    "CompiledConstraint",
    "CompilationReport",
    "ConflictRecord",
    "DroppedItem",
]