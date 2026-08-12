"""Table schema inference — match parsed Markdown tables to known planning schemas.

Infers the table type from header keywords and maps rows to typed Pydantic models:
  - 附表1 (indicator table) → PlanningIndicatorTable
  - 附表2 (land-use structure) → List[ZoneTarget]
  - 设施表 → List[FacilityTarget]

Tables that don't match any known schema are left as raw dicts.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)


class TableSchemaType(Enum):
    """Known planning table types."""

    INDICATOR_TABLE = "indicator_table"       # 附表1: 7 indicators
    LAND_USE_TABLE = "land_use_table"         # 附表2: 19 land-use categories
    FACILITY_TABLE = "facility_table"         # 设施配置表
    UNKNOWN = "unknown"


# ── Header keyword sets for schema inference ──────────────────────────

_INDICATOR_KEYWORDS = {
    "指标", "编码", "单位", "属性", "约束性", "预期性",
    "耕地保有量", "基本农田", "建设用地规模", "户均宅基地",
    "base", "target", "现状", "规划",
}

_LAND_USE_KEYWORDS = {
    "用地名称", "地类名称", "用地面积", "用地编码", "比例", "占比",
    "耕地", "园地", "林地", "宅基地", "建设用地", "生态",
    "GHYTBM", "DLBM", "现状面积", "规划面积",
}

_FACILITY_KEYWORDS = {
    "设施", "设施类型", "设施名称", "位置", "服务半径",
    "现状", "规划", "保留", "新建", "扩建",
}


def infer_table_schema(headers: List[str]) -> TableSchemaType:
    """Infer table schema type from header keywords.

    Args:
        headers: List of table header strings.

    Returns:
        Best-matching TableSchemaType.
    """
    if not headers:
        return TableSchemaType.UNKNOWN

    header_text = " ".join(headers)

    ind_score = sum(1 for kw in _INDICATOR_KEYWORDS if kw in header_text)
    lu_score = sum(1 for kw in _LAND_USE_KEYWORDS if kw in header_text)
    fac_score = sum(1 for kw in _FACILITY_KEYWORDS if kw in header_text)

    if ind_score >= 3 and ind_score >= lu_score:
        return TableSchemaType.INDICATOR_TABLE
    if lu_score >= 3 and lu_score > ind_score:
        return TableSchemaType.LAND_USE_TABLE
    if fac_score >= 2:
        return TableSchemaType.FACILITY_TABLE

    return TableSchemaType.UNKNOWN


# ── Number parsing helper ─────────────────────────────────────────────


def _parse_number(s: str) -> Optional[float]:
    """Parse a Chinese-formatted number string to float.

    Handles: "120.5", "120.5公顷", "3.2万㎡", "15亩"
    """
    if not s:
        return None
    s = s.strip()
    # Remove common units
    s = re.sub(r"(公顷|ha|亩|万㎡|m²|平方米|人|%|户)", "", s)
    s = s.replace(",", "").replace("，", "")
    # Handle 万 multiplier
    match = re.match(r"([\d.]+)\s*万", s)
    if match:
        try:
            return float(match.group(1)) * 10000
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


# ── Row mappers ───────────────────────────────────────────────────────


def _find_header(headers: List[str], *candidates: str) -> Optional[int]:
    """Find the first header matching any candidate keyword."""
    for i, h in enumerate(headers):
        for kw in candidates:
            if kw in h:
                return i
    return None


def map_table_to_indicators(
    rows: List[List[str]],
    headers: List[str],
) -> Optional[Any]:
    """Map table rows to PlanningIndicatorTable (附表1).

    Returns PlanningIndicatorTable if at least 1 indicator is extracted,
    None otherwise.
    """
    from app.contracts.workflow.parse_contracts import PlanningIndicatorItem, PlanningIndicatorTable

    # Find column indices
    code_idx = _find_header(headers, "编码", "代码", "指标编码")
    name_idx = _find_header(headers, "指标名称", "名称", "指标")
    unit_idx = _find_header(headers, "单位")
    attr_idx = _find_header(headers, "属性", "性质")
    base_idx = _find_header(headers, "现状", "基期", "基年")
    target_idx = _find_header(headers, "规划", "目标", "期末")

    if name_idx is None and code_idx is None:
        return None

    indicators = []
    for row in rows:
        if not row or all(c.strip() == "" for c in row):
            continue

        def _get(idx: Optional[int]) -> str:
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        code = _get(code_idx)
        name = _get(name_idx)
        unit = _get(unit_idx)
        attr_str = _get(attr_idx)

        # Determine attribute
        attribute = "mandatory" if "约束" in attr_str else "expected"

        # Parse numeric values
        base_val = _parse_number(_get(base_idx))
        target_val = _parse_number(_get(target_idx))
        change = None
        if base_val is not None and target_val is not None:
            change = round(target_val - base_val, 4)

        # Map to known field names from YAML
        field = _indicator_name_to_field(name)

        indicators.append(PlanningIndicatorItem(
            code=code,
            name=name,
            unit=unit,
            attribute=attribute,
            field=field,
            base_year_value=base_val,
            target_year_value=target_val,
            change=change,
        ))

    if not indicators:
        return None

    logger.info("[table_schema] Mapped %d rows to PlanningIndicatorTable", len(indicators))
    return PlanningIndicatorTable(indicators=indicators)


def _indicator_name_to_field(name: str) -> str:
    """Map indicator Chinese name to YAML field name."""
    name_to_field = {
        "耕地保有量": "farmland_area_ha",
        "基本农田保护面积": "basic_farmland_area_ha",
        "村庄建设用地规模": "construction_area_ha",
        "公共服务设施用地规模": "public_service_area_ha",
        "基础设施用地规模": "infrastructure_area_ha",
        "户均宅基地": "homestead_per_household_sqm",
        "人均村庄建设用地": "construction_per_capita_sqm",
    }
    for key, field in name_to_field.items():
        if key in name:
            return field
    return ""


def map_table_to_zone_targets(
    rows: List[List[str]],
    headers: List[str],
) -> Optional[Any]:
    """Map table rows to List[ZoneTarget] (附表2).

    Returns list of ZoneTarget if at least 1 is extracted, None otherwise.
    """
    from app.contracts.workflow.parse_contracts import ZoneTarget

    # Find column indices
    name_idx = _find_header(headers, "用地名称", "地类名称", "名称", "用地")
    code_idx = _find_header(headers, "编码", "GHYTBM", "DLBM", "用地编码")
    area_idx = _find_header(headers, "面积", "用地面积", "规划面积", "现状面积")
    ratio_idx = _find_header(headers, "比例", "占比", "面积占比", "比例(%)")

    if name_idx is None and code_idx is None:
        return None

    targets = []
    classification_system = _classification_system_from_headers(headers)
    for row in rows:
        if not row or all(c.strip() == "" for c in row):
            continue

        def _get(idx: Optional[int]) -> str:
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        land_use = _get(name_idx)
        dlbm = _get(code_idx)
        area_str = _get(area_idx)
        ratio_str = _get(ratio_idx)

        area_val = _parse_number(area_str)
        ratio_val = _parse_number(ratio_str)

        # If ratio is percentage (e.g. "45.2%"), convert to 0-1 range
        if ratio_val is not None and ratio_val > 1.0 and "%" in (ratio_str or ""):
            ratio_val = ratio_val / 100.0

        classification_decision = _classification_decision(
            classification_system,
            dlbm,
            evidence_ref="parse:land_use_table",
        )

        targets.append(ZoneTarget(
            land_use=land_use,
            area_ratio=ratio_val or 0.0,
            dlbm=dlbm if dlbm else None,
            vne_code=dlbm if classification_system == "vne" and dlbm else None,
            classification_decision=classification_decision,
        ))

    if not targets:
        return None

    logger.info("[table_schema] Mapped %d rows to ZoneTarget list", len(targets))
    return targets


def _classification_system_from_headers(headers: List[str]) -> Optional[str]:
    """Identify an explicitly declared code system from table headers.

    A bare ``DLBM`` header is intentionally ambiguous.  Guessing whether it
    means GB/T 21010, 土规, or a planning layer would reintroduce the exact
    cross-system inference this parser is required to avoid.
    """
    text = " ".join(headers).upper()
    explicit = (
        ("GHYTBM", "ghytbm"),
        ("VNE", "vne"),
        ("GHFLBM", "ghflbm"),
        ("YDYHFLDM", "ydyhfldm"),
        ("QMDLBM", "tugui"),
        ("GB/T 21010", "gbt21010"),
        ("GB/T21010", "gbt21010"),
    )
    matches = [system for marker, system in explicit if marker in text]
    return matches[0] if len(set(matches)) == 1 else None


def _classification_decision(
    system: Optional[str],
    code: str,
    *,
    evidence_ref: str,
):
    """Build a resolved decision only for an explicit, valid closed-set code."""
    if not system or not code:
        return None
    from app.contracts.artifacts.classification_ref import (
        ClassificationDecision,
        ClassificationSystem,
        classification_code_names,
    )

    try:
        code_names = classification_code_names(system)
        if not code_names or code.strip() not in code_names:
            return None
        return ClassificationDecision(
            target_id="table-row",
            code_system=ClassificationSystem(system),
            candidate_codes=[code.strip()],
            selected_code=code.strip(),
            decision_mode="parse_explicit",
            evidence_refs=[evidence_ref],
            status="resolved",
        )
    except (KeyError, TypeError, ValueError):
        return None


def map_table_to_facility_targets(
    rows: List[List[str]],
    headers: List[str],
) -> Optional[Any]:
    """Map table rows to List[FacilityTarget].

    Returns list of FacilityTarget if at least 1 is extracted, None otherwise.
    """
    from app.contracts.workflow.parse_contracts import FacilityTarget

    type_idx = _find_header(headers, "设施类型", "类型", "名称", "设施")
    status_idx = _find_header(headers, "状态", "建设状态", "情况")
    location_idx = _find_header(headers, "位置", "地点", "所在")
    radius_idx = _find_header(headers, "服务半径", "半径")

    if type_idx is None:
        return None

    facilities = []
    for row in rows:
        if not row or all(c.strip() == "" for c in row):
            continue

        def _get(idx: Optional[int]) -> str:
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        ftype = _get(type_idx)
        status_str = _get(status_idx)
        location = _get(location_idx)
        radius_str = _get(radius_idx)

        # Map status string to enum
        status = "existing_preserve"
        if any(kw in status_str for kw in ("新建", "规划新", "新建")):
            status = "planned_new"
        elif any(kw in status_str for kw in ("扩建", "扩大")):
            status = "planned_expand"
        elif any(kw in status_str for kw in ("迁建", "搬迁", "异地")):
            status = "planned_relocate"

        radius = _parse_number(radius_str)
        radius_int = int(radius) if radius is not None else None

        facilities.append(FacilityTarget(
            type=ftype,
            status=status,
            location_hint=location,
            service_radius=radius_int,
        ))

    if not facilities:
        return None

    logger.info("[table_schema] Mapped %d rows to FacilityTarget list", len(facilities))
    return facilities


# ── Main entry point ──────────────────────────────────────────────────


def infer_and_map_table(
    headers: List[str],
    rows: List[List[str]],
) -> Tuple[TableSchemaType, Any]:
    """Infer table schema and map rows to typed models.

    Returns:
        (schema_type, typed_result) where typed_result is:
          - PlanningIndicatorTable for INDICATOR_TABLE
          - List[ZoneTarget] for LAND_USE_TABLE
          - List[FacilityTarget] for FACILITY_TABLE
          - None for UNKNOWN (caller should use raw dict)
    """
    schema_type = infer_table_schema(headers)

    if schema_type == TableSchemaType.INDICATOR_TABLE:
        result = map_table_to_indicators(rows, headers)
        return (schema_type, result)

    if schema_type == TableSchemaType.LAND_USE_TABLE:
        result = map_table_to_zone_targets(rows, headers)
        return (schema_type, result)

    if schema_type == TableSchemaType.FACILITY_TABLE:
        result = map_table_to_facility_targets(rows, headers)
        return (schema_type, result)

    return (TableSchemaType.UNKNOWN, None)


__all__ = [
    "TableSchemaType",
    "infer_table_schema",
    "infer_and_map_table",
    "map_table_to_indicators",
    "map_table_to_zone_targets",
    "map_table_to_facility_targets",
]
