"""Delivery manifest contracts — exit gate + final delivery bundle manifest.

v1.0 (2026-07-26):
- DeliveryGate: hard exit criteria — fail produces diagnostic bundle, not final output
- Deliverable/TraceabilityEntry/HumanItem: final delivery manifest structure

Design: 02_EXECUTION_PLAN.md Module F, Module G
"""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field

from .contract_meta import ContractMeta
from .deferral_contracts import DeferralLedger
from .execution_plan_contracts import TypedActionResult
from .provenance import Provenance


class DeliveryGate(BaseModel):
    """出口硬门槛 — 不满足则只出诊断包，不出成品。

    All checks must pass for delivery. Any failure produces a diagnostic
    bundle (violations + CompilationReport + trace) instead of final output.
    """

    land_balance_closed: bool = False    # 用地平衡表闭合 ±0.5%
    three_line_violations: int = 0       # 必须 == 0
    protected_intrusions: int = 0        # 必须 == 0
    changed_parcels_pct: float = 0.0     # 变更比例
    # 变更比例阈值：由交付策略注入，schema 不固化为默认规则（未确认的规划策略）。
    changed_parcels_threshold: float | None = None
    zones_complete: bool = False          # 必备分区齐全

    @property
    def passed(self) -> bool:
        threshold_ok = (
            self.changed_parcels_threshold is None
            or self.changed_parcels_pct <= self.changed_parcels_threshold
        )
        return (
            self.land_balance_closed
            and self.three_line_violations == 0
            and self.protected_intrusions == 0
            and threshold_ok
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
        if (
            self.changed_parcels_threshold is not None
            and self.changed_parcels_pct > self.changed_parcels_threshold
        ):
            fails.append(
                f"变更比例 {self.changed_parcels_pct:.1f}% > 阈值 {self.changed_parcels_threshold}%"
            )
        if not self.zones_complete:
            fails.append("必备分区不齐全")
        return fails

    def summary(self) -> str:
        if self.passed:
            return "DeliveryGate: PASS (all checks passed)"
        return f"DeliveryGate: FAIL ({'; '.join(self.failures)})"


class Deliverable(BaseModel):
    deliverable_id: str
    type: str = ""
    path: str = ""
    format: str = ""
    description: str = ""


class TraceabilityEntry(BaseModel):
    target_id: str = ""
    target_type: str = ""
    expected_output_kind: Literal["parcel", "polygon", "point", "line", "action"] = "parcel"
    execution_task_id: str = ""
    output_artifacts: list[str] = Field(default_factory=list)
    status: Literal["covered", "partial", "missing", "deferred", "failed"] = "missing"
    intervention_id: str = ""
    requirement_id: str = ""
    candidate_id: str = ""
    selection_id: str = ""
    change_id: str = ""
    planned_ref: str = ""
    deliverable_id: str = ""


class HumanItem(BaseModel):
    item_id: str
    description: str = ""
    reason: str = ""
    blocking: bool = False


class DeliveryManifest(ContractMeta):
    schema_version: Literal["2.0"] = "2.0"
    delivery_status: Literal["complete", "partial", "diagnostic_only"] = "diagnostic_only"
    deliverables: list[Deliverable] = Field(default_factory=list)
    traceability: list[TraceabilityEntry] = Field(default_factory=list)
    action_results: list[TypedActionResult] = Field(default_factory=list)
    deferral_ledger: DeferralLedger | None = None
    deferral_summary: dict = Field(default_factory=dict)
    diagnostic_summary: dict = Field(default_factory=dict)
    expected_spatial_output_count: int = 0
    render_layer_count: int = 0
    pending_human_items: list[HumanItem] = Field(default_factory=list)
    delivery_gate: DeliveryGate | None = None
    provenance: "Provenance | None" = None
    # 法定成果完整性：缺规划分类等 blocking 问题时不输出"完整法定成果"（08_DELIVERABLES_COMPLIANCE.md §3）
    statutory_complete: bool = False
    statutory_complete_breakdown: dict[str, bool] = Field(default_factory=dict)

__all__ = [
    "DeliveryGate",
    "Deliverable",
    "TraceabilityEntry",
    "HumanItem",
    "DeliveryManifest",
]
