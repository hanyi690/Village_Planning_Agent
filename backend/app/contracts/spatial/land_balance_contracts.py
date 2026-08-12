"""Land balance contracts — L1 vs L4 parcel-level comparison table.

v1.0 (2026-07-26):
- LandBalanceRow/Table: L1 vs L4 parcel-level comparison table (用地平衡表)

Design: 02_EXECUTION_PLAN.md Module G
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.contracts.artifacts.delivery_manifest_contracts import DeliveryGate


class LandBalanceRow(BaseModel):
    """Single row in the land balance table (用地平衡表).

    对应 土地利用结构调整表（附表2）的一行。
    """

    land_use_name: str = ""          # 地类名称
    land_use_code: str = ""          # 地类编码
    planning_zone: Optional[str] = None  # 归属规划分区
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
    # 闭合允许偏差（%）：由校验策略注入；None 表示未设置时保守判定不闭合。
    closure_tolerance_pct: Optional[float] = None

    # 大类汇总（由计算方填充，schema 不固化汇总规则）
    agriculture_current: float = 0.0
    agriculture_planned: float = 0.0
    construction_current: float = 0.0
    construction_planned: float = 0.0
    ecological_current: float = 0.0
    ecological_planned: float = 0.0

    @property
    def is_closed(self) -> bool:
        """用地平衡表闭合：规划总面积与现状总面积偏差 ≤ 容差（未设置则不闭合）。"""
        if self.total_current_area_ha <= 0:
            return False
        if self.closure_tolerance_pct is None:
            return False
        self.closure_deviation_pct = abs(
            (self.total_planned_area_ha - self.total_current_area_ha)
            / self.total_current_area_ha
            * 100
        )
        return self.closure_deviation_pct <= self.closure_tolerance_pct

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
    "LandBalanceRow",
    "LandBalanceTable",
]
