"""Validation contract schemas — data models for the validation loop.

Defines the 8 validation checks (design doc §5.6) and their structured
output. These are consumed by the Worker-Evaluator retry loop.

Also defines ClauseReference for clause-level traceability (design
principle #7: every parcel change traceable to source text).
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .execution_contracts import ConstraintAdjustment


# ── Clause-level traceability ───────────────────────────────────────


class ClauseReference(BaseModel):
    """Structured reference to a source document clause.

    Replaces the flat article_ref: str field with a structured model
    that supports clause-level traceability (Phase 5).
    """

    document: str = ""          # e.g. "金田村规划文本"
    article_number: str = ""    # e.g. "第15条"
    clause: str = ""            # e.g. "第二款"
    section: str = ""           # e.g. "用地布局"
    raw_text: str = ""          # original text excerpt (≤200 chars)


# ── Validation check items ──────────────────────────────────────────


class ValidationCheckItem(BaseModel):
    """Single validation check result — one of the 8 checks from design doc §5.6.

    | # | Check                    | Constraint Source |
    |---|--------------------------|-------------------|
    | 1 | 建设用地不超上限        | kg_constraint     |
    | 2 | 耕地下限                | kg_constraint     |
    | 3 | 不占永久基本农田        | kg_spatial        |
    | 4 | 不占生态红线            | kg_spatial        |
    | 5 | 建设边界内              | kg_spatial        |
    | 6 | 面积偏差 ≤ 5%           | intent            |
    | 7 | 邻接规则合规            | intent            |
    | 8 | 三线合规                | kg_spatial        |
    """

    check_id: str = ""          # "construction_cap" / "farmland_floor" / ...
    check_name: str = ""        # e.g. "建设用地不超上限"
    passed: bool = True
    actual_value: Optional[float] = None
    expected_value: Optional[float] = None
    deviation_pct: Optional[float] = None
    constraint_source: Literal["kg_constraint", "kg_spatial", "intent"] = "kg_constraint"
    affected_parcels: List[str] = Field(default_factory=list)
    fix_suggestion: str = ""


class ValidationCheckResult(BaseModel):
    """Complete validation result — 8 checks + overall pass/fail.

    Produced by the Evaluator, consumed by the Worker-Evaluator loop gate.
    Design doc §5.6: PASS -> END, FAIL -> generate adjustments -> re-EXECUTE.
    """

    checks: List[ValidationCheckItem] = Field(default_factory=list)
    overall_passed: bool = False
    total_checks: int = 8
    passed_count: int = 0
    adjustments: List[ConstraintAdjustment] = Field(default_factory=list)
    round_number: int = 0


__all__ = [
    "ClauseReference",
    "ValidationCheckItem",
    "ValidationCheckResult",
]
