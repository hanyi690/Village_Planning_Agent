"""Land balance calculator — L1 vs L4 parcel-level comparison.

Produces LandBalanceTable for the 土地利用结构调整表 (附表2).

Design: 02_EXECUTION_PLAN.md Module G
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from app.modules.schema.contracts.land_balance_contracts import (
    LandBalanceRow,
    LandBalanceTable,
)
from app.modules.schema.contracts.delivery_manifest_contracts import DeliveryGate

logger = logging.getLogger(__name__)


def compute_land_balance(
    current_parcels: List[Any],
    planned_parcels: List[Any],
    total_area_ha: float = 0.0,
) -> LandBalanceTable:
    """Compute land balance table from L1 current and L4 planned parcels.

    Args:
        current_parcels: List of CurrentLandUseParcel or dict-like objects
        planned_parcels: List of planned parcel dicts (from parcel_ops or KG L4)
        total_area_ha: Total area override (computed from parcels if 0)

    Returns:
        LandBalanceTable with full 3×6 structure
    """
    # Aggregate L1 (current) areas by land use code
    current_by_code: Dict[str, float] = defaultdict(float)
    current_total = 0.0
    for p in current_parcels:
        code = _get_attr(p, "dlbm", "") or _get_attr(p, "ghytbm", "0000")
        area_sqm = float(_get_attr(p, "area_sqm", 0) or 0)
        area_ha = float(_get_attr(p, "area_ha", 0) or _get_attr(p, "area", 0) or 0)
        if area_sqm > 0:
            area = area_sqm / 10000.0
        else:
            area = area_ha
        current_by_code[code] += area
        current_total += area

    # Aggregate L4 (planned) areas
    planned_by_code: Dict[str, float] = defaultdict(float)
    planned_by_zone: Dict[str, float] = defaultdict(float)
    planned_zone_by_code: Dict[str, str] = {}
    planned_total = 0.0
    for p in planned_parcels:
        code = _get_attr(p, "planning_land_use", "") or _get_attr(p, "dlbm", "0000")
        area = float(_get_attr(p, "area_ha", 0) or 0)
        zone = _get_attr(p, "zone_type", "") or _get_attr(p, "planning_zone", "")

        planned_by_code[code] += area
        if zone:
            planned_by_zone[zone] += area
            planned_zone_by_code.setdefault(code, zone)
        planned_total += area

    if total_area_ha <= 0:
        total_area_ha = max(current_total, planned_total)

    # Build rows from merged code sets
    all_codes = set(current_by_code.keys()) | set(planned_by_code.keys())
    rows = []

    # Map known codes to planning zones
    for code in sorted(all_codes):
        cur_area = current_by_code.get(code, 0.0)
        pla_area = planned_by_code.get(code, 0.0)
        change = pla_area - cur_area

        lu_name = _code_to_name(code)

        pz = planned_zone_by_code.get(code, "")

        if cur_area > 0 or pla_area > 0:
            rows.append(LandBalanceRow(
                land_use_name=lu_name,
                land_use_code=code,
                planning_zone=pz,
                current_area_ha=round(cur_area, 4),
                current_ratio=round(cur_area / total_area_ha * 100, 2) if total_area_ha > 0 else 0,
                planned_area_ha=round(pla_area, 4),
                planned_ratio=round(pla_area / total_area_ha * 100, 2) if total_area_ha > 0 else 0,
                change_ha=round(change, 4),
                change_pct=round(change / cur_area * 100, 2) if cur_area > 0 else 0,
            ))

    # Compute category summaries
    agri_current = sum(r.current_area_ha for r in rows if r.planning_zone in (
        "农田保护区", "一般农业区",
        "林业发展区",
    ))
    agri_planned = sum(r.planned_area_ha for r in rows if r.planning_zone in (
        "农田保护区", "一般农业区",
        "林业发展区",
    ))
    construct_current = sum(r.current_area_ha for r in rows if r.planning_zone == "村庄建设区")
    construct_planned = sum(r.planned_area_ha for r in rows if r.planning_zone == "村庄建设区")
    eco_current = sum(r.current_area_ha for r in rows if r.planning_zone in (
        "生态保护区", "生态控制区",
    ))
    eco_planned = sum(r.planned_area_ha for r in rows if r.planning_zone in (
        "生态保护区", "生态控制区",
    ))

    table = LandBalanceTable(
        rows=rows,
        total_current_area_ha=round(current_total, 4),
        total_planned_area_ha=round(planned_total, 4),
        agriculture_current=round(agri_current, 4),
        agriculture_planned=round(agri_planned, 4),
        construction_current=round(construct_current, 4),
        construction_planned=round(construct_planned, 4),
        ecological_current=round(eco_current, 4),
        ecological_planned=round(eco_planned, 4),
        closure_tolerance_pct=0.5,
    )

    # Trigger closure check
    _ = table.is_closed

    logger.info(
        "compute_land_balance: %d codes, closure_deviation=%.2f%%",
        len(rows), table.closure_deviation_pct,
    )
    return table


def check_delivery_gate(
    current_parcels: List[Any],
    planned_parcels: List[Any],
    three_line_violations: int = 0,
    protected_intrusions: int = 0,
    changed_parcels_pct: float = 0.0,
    zones_complete: bool = True,
) -> DeliveryGate:
    """Check all delivery gate criteria.

    Args:
        current_parcels: L1 current parcels
        planned_parcels: L4 planned parcels
        three_line_violations: Count of three-line violations
        protected_intrusions: Count of protected area intrusions
        changed_parcels_pct: Percentage of parcels changed
        zones_complete: Whether all required zones are present

    Returns:
        DeliveryGate with all checks evaluated
    """
    balance = compute_land_balance(current_parcels, planned_parcels)

    gate = DeliveryGate(
        land_balance_closed=balance.is_closed,
        three_line_violations=three_line_violations,
        protected_intrusions=protected_intrusions,
        changed_parcels_pct=changed_parcels_pct,
        zones_complete=zones_complete,
    )

    logger.info("check_delivery_gate: %s", gate.summary())
    return gate


def _get_attr(obj: Any, key: str, default: Any = "") -> Any:
    if hasattr(obj, key):
        return getattr(obj, key, default)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


_KNOWN_NAMES: Dict[str, str] = {}


def _code_to_name(code: str) -> str:
    """Look up land use name from code using code_sets."""
    if code in _KNOWN_NAMES:
        return _KNOWN_NAMES[code]
    try:
        from app.modules.schema.encodings.code_sets import DLBM_TO_DLMC, GHYTBM_TO_GHYTMC

        for mapping in [GHYTBM_TO_GHYTMC, DLBM_TO_DLMC]:
            if code in mapping:
                _KNOWN_NAMES[code] = mapping[code]
                return mapping[code]
    except Exception:
        pass
    _KNOWN_NAMES[code] = code
    return code


__all__ = ["compute_land_balance", "check_delivery_gate"]