"""Flash-LLM unit repair for L3 claim drafts.

Unknown units (hm, 待定, 处/户 used as area units) are cheap to fix - a
flash LLM maps them to the standard closed-set unit in one quick call,
avoiding a full dimension re-generation (the main model) or a program_rework
retry loop.  The flash model only decides the unit mapping; the values and
geometry stay untouched and deterministic normalization still applies.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.domain.program.unit_normalization import normalize_unit
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_MEASURE_FIELDS: dict[str, tuple[str, ...]] = {
    "road_parameters": ("length", "roadbed_width", "pavement_width"),
    "facility_parameters": ("service_radius", "capacity", "footprint_area"),
    "axis_parameters": ("corridor_width",),
    "polygon_parameters": ("area_range",),
    "project_parameters": ("capacity", "footprint_area"),
}

# Standard units the normalizer can actually consume (post-alias).
_KNOWN_STANDARD_UNITS = {
    "m", "km", "cm", "mm",
    "ha", "mu", "m2", "km2",
    "m3", "l", "t",
    "个", "处", "座", "条", "棵", "株", "人", "户", "间", "栋",
    "kw", "kwh",
}


def _measures_of(claim: Any):
    for attr, fields in _MEASURE_FIELDS.items():
        params = getattr(claim, attr, None)
        if params is None:
            continue
        for field in fields:
            measure = getattr(params, field, None)
            if measure is not None:
                yield measure


def _still_unknown(unit: str) -> bool:
    text = (unit or "").strip()
    if not text:
        return False
    normalized = normalize_unit(text)
    if normalized in _KNOWN_STANDARD_UNITS:
        return False
    # normalize_unit returns the raw text when nothing matched
    return normalized.lower().replace(" ", "") == text.lower().replace(" ", "")


def collect_unknown_units(draft_set: Any) -> dict[str, list[str]]:
    """Return {raw_unit: [claim_id, ...]} for units the normalizer cannot map."""
    unknown: dict[str, list[str]] = {}
    for claim in draft_set.claims or []:
        for measure in _measures_of(claim):
            unit = (getattr(measure, "unit", None) or "").strip()
            if _still_unknown(unit):
                unknown.setdefault(unit, []).append(str(claim.claim_id or ""))
        top_unit = (getattr(claim, "quantity_unit", None) or "").strip()
        if top_unit and _still_unknown(top_unit):
            unknown.setdefault(top_unit, []).append(str(claim.claim_id or ""))
    return unknown


def _apply_mapping(draft_set: Any, mapping: dict[str, str]) -> int:
    applied = 0
    for claim in draft_set.claims or []:
        for measure in _measures_of(claim):
            unit = (getattr(measure, "unit", None) or "").strip()
            replacement = mapping.get(unit) or mapping.get(unit.lower())
            if replacement and replacement != unit and not _still_unknown(replacement):
                try:
                    measure.unit = replacement
                    applied += 1
                except Exception:  # noqa: BLE001 - pydantic frozen safety
                    pass
        top_unit = (getattr(claim, "quantity_unit", None) or "").strip()
        replacement = mapping.get(top_unit) or mapping.get(top_unit.lower())
        if replacement and replacement != top_unit and not _still_unknown(replacement):
            try:
                claim.quantity_unit = replacement
                applied += 1
            except Exception:  # noqa: BLE001
                pass
    return applied


def _parse_mapping(content: Any) -> dict[str, str]:
    text = str(content or "")
    if isinstance(content, list):
        text = "".join(str(part) for part in content)
    match = re.search(r"\{[^{}]*\}", text, re.S)
    if match:
        try:
            payload = json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            payload = None
        if isinstance(payload, dict):
            return {str(k).strip().lower(): str(v).strip() for k, v in payload.items() if str(v).strip()}
    # fallback: "原单位 -> 标准单位" lines
    mapping: dict[str, str] = {}
    for line in text.splitlines():
        parts = re.split(r"[\->：:=]", line)
        if len(parts) >= 2:
            mapping[parts[0].strip().lower()] = parts[1].strip()
    return mapping


async def flash_repair_units(draft_set: Any, session_id: str) -> Any:
    """Map unknown units to the standard closed set with a flash LLM call.

    Returns the (possibly modified) draft_set.  No-op when every unit is
    already known.  The flash model never invents values or geometry.
    """
    unknown = collect_unknown_units(draft_set)
    if not unknown:
        return draft_set
    from app.infrastructure.llm.factory import create_flash_llm

    llm = create_flash_llm(max_tokens=300, temperature=0.0)
    units = sorted(unknown.keys())
    prompt = (
        "以下是从村庄规划干预 claim 中提取的单位（可能是面积/长度/数量/容量单位，"
        "也可能写错或为占位词）。请把每个映射到标准单位闭集："
        "面积：ha/m2/亩；长度：m/km；数量：个/处/座/条/人/户；容量：m3/l/t；功率：kw/kwh。"
        "只输出 JSON 对象 “原单位”→“标准单位”；无法判断的保持原值。\n"
        f"单位列表：{units}"
    )
    try:
        import asyncio

        response = await llm.ainvoke(prompt) if asyncio.iscoroutinefunction(getattr(llm, "ainvoke", None)) else llm.invoke(prompt)
    except Exception as exc:  # noqa: BLE001 - flash failure keeps the draft unchanged
        logger.warning("[flash_unit_repair] llm call failed for %s: %s", session_id, exc)
        return draft_set
    mapping = _parse_mapping(getattr(response, "content", ""))
    if not mapping:
        return draft_set
    applied = _apply_mapping(draft_set, mapping)
    if applied:
        logger.info(
            "[flash_unit_repair] session=%s mapped %d unknown units: %s",
            session_id, applied, {k: mapping[k] for k in list(mapping)[:10]},
        )
    return draft_set


__all__ = ["collect_unknown_units", "flash_repair_units"]
