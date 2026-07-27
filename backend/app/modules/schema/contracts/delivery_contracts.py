"""Delivery and balance contracts — delivery gate, target patch, land balance table.

v1.0 (2026-07-26):
- DeliveryGate: hard exit criteria — fail produces diagnostic bundle, not final output
- TargetPatch: feedback protocol for the Worker-Evaluator retry loop
- LandBalanceRow/Table: L1 vs L4 parcel-level comparison table

Design: 02_EXECUTION_PLAN.md Module F, Module G
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Target Patch (feedback protocol) ──


class TargetPatch(BaseModel):
    """Single adjustment to a zone target — from validation feedback.

    zone uses PlanningZone enum — guaranteed same vocabulary as MIP targets.
    delta_ha: positive = increase target, negative = decrease target.
    new_bound: directly set a new hard bound if delta accumulation is unstable.
    """

    zone: PlanningZone
    delta_ha: float = 0.0
    new_bound: Optional[float] = None
    reason: str = ""
    source_check: str = ""


# ── Delivery Gate ──


class DeliveryGate(BaseModel):
    """出口硬门槛 — 不满足则只出诊断包，不出成品。

    All checks must pass for delivery. Any failure produces a diagnostic
    bundle (violations + CompilationReport + trace) instead of final output.
    """

    land_balance_closed: bool = False    # 用地平衡表闭合 ±0.5%
    three_line_violations: int = 0       # 必须 == 0
    protected_intrusions: int = 0        # 必须 == 0
    changed_parcels_pct: float = 0.0     # 变更比例 ≤ 阈值（默认15%）
    changed_parcels_threshold: float = 15.0
    zones_complete: bool = False          # 必备分区齐全

    @property
    def passed(self) -> bool:
        return (
            self.land_balance_closed
            and self.three_line_violations == 0
            and self.protected_intrusions == 0
            and self.changed_parcels_pct <= self.changed_parcels_threshold
            and self.zones_complete
        )

    @property
    def failures(self) -> List[str]:
        fails = []
        if not self.land_balance_closed:
            fails.append("用地平衡表不闭合")
        if self.three_line_violations > 0:
            fails.append(f"三线冲突: {self.three_line_violations} 处")
        if self.protected_intrusions > 0:
            fails.append(f"保护侵入: {self.protected_intrusions} 处")
        if self.changed_parcels_pct > self.changed_parcels_threshold:
            fails.append(f"变更比例 {self.changed_parcels_pct:.1f}% > 阈值 {self.changed_parcels_threshold}%")
        if not self.zones_complete:
            fails.append("必备分区不齐全")
        return fails

    def summary(self) -> str:
        if self.passed:
            return "DeliveryGate: PASS (all checks passed)"
        return f"DeliveryGate: FAIL ({'; '.join(self.failures)})"


# ── Land Balance Table ──


class LandBalanceRow(BaseModel):
    """Single row in the land balance table (用地平衡表).

    对应 土地利用结构调整表（附表2）的一行。
    """

    land_use_name: str = ""          # 地类名称
    land_use_code: str = ""          # 地类编码
    planning_zone: Optional[PlanningZone] = None  # 归属规划分区
    current_area_ha: float = 0.0     # 现状面积
    current_ratio: float = 0.0       # 现状比重 (%)
    planned_area_ha: float = 0.0     # 规划面积
    planned_ratio: float = 0.0       # 规划比重 (%)
    change_ha: float = 0.0           # 规划期内增减
    change_pct: float = 0.0          # 增减百分比


class LandBalanceTable(BaseModel):
    """Complete land balance table (土地利用结构调整表).

    3 大类（农业/建设/生态）× 6 列结构。
    闭合校验：规划总面积 ±0.5% 内必须等于现状总面积。
    """

    rows: List[LandBalanceRow] = Field(default_factory=list)
    total_current_area_ha: float = 0.0
    total_planned_area_ha: float = 0.0
    closure_deviation_pct: float = 0.0

    # 大类汇总
    agriculture_current: float = 0.0
    agriculture_planned: float = 0.0
    construction_current: float = 0.0
    construction_planned: float = 0.0
    ecological_current: float = 0.0
    ecological_planned: float = 0.0

    @property
    def is_closed(self) -> bool:
        """用地平衡表闭合：规划总面积与现状总面积偏差 ≤ 0.5%"""
        if self.total_current_area_ha <= 0:
            return False
        self.closure_deviation_pct = abs(
            (self.total_planned_area_ha - self.total_current_area_ha)
            / self.total_current_area_ha
            * 100
        )
        return self.closure_deviation_pct <= 0.5

    def to_delivery_check(self) -> DeliveryGate:
        """Convert to a DeliveryGate check for the exit gate."""
        return DeliveryGate(
            land_balance_closed=self.is_closed,
        )

    def summary(self) -> str:
        return (
            f"LandBalanceTable: 现状={self.total_current_area_ha:.1f}ha, "
            f"规划={self.total_planned_area_ha:.1f}ha, "
            f"闭合偏差={self.closure_deviation_pct:.2f}%, "
            f"闭合={'✅' if self.is_closed else '❌'}"
        )


__all__ = [
    "DeliveryGate",
    "TargetPatch",
    "LandBalanceRow",
    "LandBalanceTable",
]