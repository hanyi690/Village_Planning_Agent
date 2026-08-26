"""Field-scoped flash unit repair for provider draft claims.

Deterministic aliases run first and only unresolved fields are sent to the
flash model. Rewrites are always scoped to one ``claim_id`` + ``field_path``
pair so the same raw unit can resolve differently across quantity kinds.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

QuantityKind = Literal[
    "area",
    "length",
    "count",
    "capacity",
    "population",
    "ratio",
    "time",
]
ResolutionStatus = Literal["resolved", "abstain"]


class UnitResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    field_path: str
    raw_unit: str
    quantity_kind: QuantityKind
    normalized_unit: str
    status: ResolutionStatus


class UnitResolutionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolutions: list[UnitResolution] = Field(default_factory=list)


@dataclass(frozen=True)
class _FieldSpec:
    field_path: str
    allowed_kinds: tuple[QuantityKind, ...]


@dataclass(frozen=True)
class _UnitCandidate:
    claim_id: str
    field_path: str
    raw_unit: str
    allowed_kinds: tuple[QuantityKind, ...]


@dataclass(frozen=True)
class _AliasMatch:
    quantity_kind: QuantityKind
    normalized_unit: str


_FIELD_SPECS: tuple[_FieldSpec, ...] = (
    _FieldSpec("quantity_unit", ("area", "length", "count", "capacity", "population", "ratio", "time")),
    _FieldSpec("road_parameters.length.unit", ("length",)),
    _FieldSpec("road_parameters.roadbed_width.unit", ("length",)),
    _FieldSpec("road_parameters.pavement_width.unit", ("length",)),
    _FieldSpec("linear_parameters.length.unit", ("length",)),
    _FieldSpec("linear_parameters.diameter.unit", ("length",)),
    _FieldSpec("facility_parameters.service_radius.unit", ("length",)),
    _FieldSpec("facility_parameters.capacity.unit", ("capacity", "count", "population")),
    _FieldSpec("facility_parameters.footprint_area.unit", ("area",)),
    _FieldSpec("axis_parameters.corridor_width.unit", ("length",)),
    _FieldSpec("polygon_parameters.area_range.unit", ("area",)),
    _FieldSpec("site_area_parameters.capacity.unit", ("capacity", "count", "population")),
    _FieldSpec("site_area_parameters.footprint_area.unit", ("area",)),
)

_UNIT_ALIASES: dict[QuantityKind, dict[str, str]] = {
    "area": {
        "ha": "ha",
        "hectare": "ha",
        "hectares": "ha",
        "公顷": "ha",
        "hm2": "ha",
        "hm²": "ha",
        "hm": "ha",
        "hectometer": "ha",
        "hectometre": "ha",
        "squarehectometer": "ha",
        "平方百米": "ha",
        "mu": "mu",
        "亩": "mu",
        "mou": "mu",
        "m2": "m2",
        "㎡": "m2",
        "sqm": "m2",
        "sq.m": "m2",
        "squaremeter": "m2",
        "squaremeters": "m2",
        "squaremetre": "m2",
        "平方米": "m2",
        "平米": "m2",
        "km2": "km2",
        "平方公里": "km2",
        "平方千米": "km2",
    },
    "length": {
        "m": "m",
        "meter": "m",
        "metre": "m",
        "meters": "m",
        "metres": "m",
        "米": "m",
        "公尺": "m",
        "km": "km",
        "kilometer": "km",
        "kilometre": "km",
        "kilometers": "km",
        "公里": "km",
        "千米": "km",
        "cm": "cm",
        "centimeter": "cm",
        "厘米": "cm",
        "mm": "mm",
        "millimeter": "mm",
        "毫米": "mm",
    },
    "count": {
        "个": "个",
        "处": "处",
        "座": "座",
        "条": "条",
        "棵": "棵",
        "株": "株",
        "户": "户",
        "家": "户",
        "间": "间",
        "栋": "栋",
    },
    "capacity": {
        "m3": "m3",
        "m³": "m3",
        "cubicmeter": "m3",
        "立方米": "m3",
        "l": "l",
        "liter": "l",
        "litre": "l",
        "升": "l",
        "t": "t",
        "ton": "t",
        "tonne": "t",
        "吨": "t",
    },
    "population": {
        "人": "人",
        "person": "人",
        "persons": "人",
        "people": "人",
        "population": "人",
    },
    "ratio": {
        "%": "%",
        "％": "%",
        "percent": "%",
        "percentage": "%",
    },
    "time": {
        "年": "year",
        "year": "year",
        "years": "year",
        "yr": "year",
        "月": "month",
        "month": "month",
        "months": "month",
        "天": "day",
        "日": "day",
        "day": "day",
        "days": "day",
    },
}


def _normalize_token(text: Any) -> str:
    value = str(text or "")
    try:
        value = unicodedata.normalize("NFKC", value)
    except Exception:  # noqa: BLE001
        pass
    value = "".join(ch for ch in value if unicodedata.category(ch)[0] != "C")
    return value.strip().lower().replace(" ", "").strip(".,;:，；。:")


def _iter_unit_candidates(draft_set: Any) -> list[_UnitCandidate]:
    candidates: list[_UnitCandidate] = []
    for claim in getattr(draft_set, "claims", []) or []:
        claim_id = str(getattr(claim, "claim_id", "") or "")
        for spec in _FIELD_SPECS:
            unit = _get_value_by_path(claim, spec.field_path)
            if unit is None:
                continue
            raw_unit = str(unit or "").strip()
            if not raw_unit:
                continue
            candidates.append(
                _UnitCandidate(
                    claim_id=claim_id,
                    field_path=spec.field_path,
                    raw_unit=raw_unit,
                    allowed_kinds=spec.allowed_kinds,
                )
            )
    return candidates


def _get_value_by_path(root: Any, field_path: str) -> Any:
    current = root
    for part in field_path.split("."):
        if current is None or not hasattr(current, part):
            return None
        current = getattr(current, part)
    return current


def _find_alias_matches(raw_unit: str) -> list[_AliasMatch]:
    token = _normalize_token(raw_unit)
    if not token:
        return []
    matches: list[_AliasMatch] = []
    seen: set[tuple[QuantityKind, str]] = set()
    for quantity_kind, aliases in _UNIT_ALIASES.items():
        normalized_unit = aliases.get(token)
        if normalized_unit is None:
            continue
        key = (quantity_kind, normalized_unit)
        if key in seen:
            continue
        matches.append(_AliasMatch(quantity_kind=quantity_kind, normalized_unit=normalized_unit))
        seen.add(key)
    return matches


def _deterministic_resolution_for(
    candidate: _UnitCandidate,
) -> tuple[UnitResolution | None, bool]:
    matches = _find_alias_matches(candidate.raw_unit)
    if not matches:
        return None, True
    allowed = [match for match in matches if match.quantity_kind in candidate.allowed_kinds]
    allowed_keys = {(match.quantity_kind, match.normalized_unit) for match in allowed}
    if len(allowed_keys) == 1:
        match = allowed[0]
        return (
            UnitResolution(
                claim_id=candidate.claim_id,
                field_path=candidate.field_path,
                raw_unit=candidate.raw_unit,
                quantity_kind=match.quantity_kind,
                normalized_unit=match.normalized_unit,
                status="resolved",
            ),
            False,
        )
    if not allowed:
        return (
            UnitResolution(
                claim_id=candidate.claim_id,
                field_path=candidate.field_path,
                raw_unit=candidate.raw_unit,
                quantity_kind=candidate.allowed_kinds[0],
                normalized_unit="",
                status="abstain",
            ),
            False,
        )
    return (
        UnitResolution(
            claim_id=candidate.claim_id,
            field_path=candidate.field_path,
            raw_unit=candidate.raw_unit,
            quantity_kind=allowed[0].quantity_kind,
            normalized_unit="",
            status="abstain",
        ),
        False,
    )


def resolve_units_deterministically(
    draft_set: Any,
) -> tuple[UnitResolutionBatch, list[_UnitCandidate]]:
    resolutions: list[UnitResolution] = []
    unresolved: list[_UnitCandidate] = []
    for candidate in _iter_unit_candidates(draft_set):
        resolution, should_send_to_llm = _deterministic_resolution_for(candidate)
        if resolution is not None:
            resolutions.append(resolution)
        if should_send_to_llm:
            unresolved.append(candidate)
    return UnitResolutionBatch(resolutions=resolutions), unresolved


def collect_unknown_units(draft_set: Any) -> dict[str, list[str]]:
    _, unresolved = resolve_units_deterministically(draft_set)
    unknown: dict[str, list[str]] = {}
    for candidate in unresolved:
        unknown.setdefault(candidate.raw_unit, []).append(candidate.claim_id)
    return unknown


def _claim_index(draft_set: Any) -> dict[str, Any]:
    return {
        str(getattr(claim, "claim_id", "") or ""): claim
        for claim in getattr(draft_set, "claims", []) or []
    }


def apply_unit_resolution_batch(draft_set: Any, batch: UnitResolutionBatch) -> int:
    applied = 0
    claims_by_id = _claim_index(draft_set)
    for resolution in batch.resolutions:
        if resolution.status != "resolved":
            continue
        claim = claims_by_id.get(resolution.claim_id)
        if claim is None:
            continue
        current = _get_value_by_path(claim, resolution.field_path)
        if current is None:
            continue
        previous = str(current or "")
        if previous.strip() != resolution.raw_unit.strip():
            continue
        if resolution.quantity_kind not in _allowed_kinds_for_path(resolution.field_path):
            continue
        if _normalize_token(resolution.normalized_unit) not in _UNIT_ALIASES[resolution.quantity_kind]:
            continue
        if not _set_value_by_path(claim, resolution.field_path, resolution.normalized_unit):
            continue
        if not _field_matches_resolution(claim, resolution):
            _set_value_by_path(claim, resolution.field_path, previous)
            continue
        applied += 1
    return applied


def _allowed_kinds_for_path(field_path: str) -> tuple[QuantityKind, ...]:
    for spec in _FIELD_SPECS:
        if spec.field_path == field_path:
            return spec.allowed_kinds
    return ()


def _set_value_by_path(root: Any, field_path: str, value: str) -> bool:
    parts = field_path.split(".")
    current = root
    for part in parts[:-1]:
        if current is None or not hasattr(current, part):
            return False
        current = getattr(current, part)
    final = parts[-1]
    if current is None or not hasattr(current, final):
        return False
    try:
        setattr(current, final, value)
    except Exception:  # noqa: BLE001
        return False
    return True


def _field_matches_resolution(claim: Any, resolution: UnitResolution) -> bool:
    raw_unit = _get_value_by_path(claim, resolution.field_path)
    if raw_unit is None:
        return False
    verified = _UnitCandidate(
        claim_id=resolution.claim_id,
        field_path=resolution.field_path,
        raw_unit=str(raw_unit),
        allowed_kinds=_allowed_kinds_for_path(resolution.field_path),
    )
    deterministic, should_send_to_llm = _deterministic_resolution_for(verified)
    if should_send_to_llm or deterministic is None:
        return False
    return (
        deterministic.status == "resolved"
        and deterministic.quantity_kind == resolution.quantity_kind
        and deterministic.normalized_unit == resolution.normalized_unit
    )


def _build_llm_prompt(candidates: list[_UnitCandidate]) -> str:
    payload = [
        {
            "claim_id": candidate.claim_id,
            "field_path": candidate.field_path,
            "raw_unit": candidate.raw_unit,
            "allowed_quantity_kinds": list(candidate.allowed_kinds),
        }
        for candidate in candidates
    ]
    return (
        "请修复村庄规划 claim 中尚未识别的单位字段。"
        "你只能处理下列字段，且每条 resolution 必须严格对应同一个 claim_id 和 field_path。"
        "如果单位含义不明确、与字段 quantity kind 不匹配、或无法确定，请输出 status='abstain'，不要猜。"
        "只输出一个 JSON 对象，格式为 "
        '{"resolutions":[{"claim_id":"","field_path":"","raw_unit":"","quantity_kind":"area","normalized_unit":"","status":"resolved"}]}。'
        "quantity_kind 只能是 area/length/count/capacity/population/ratio/time，"
        "status 只能是 resolved 或 abstain。"
        f"\n字段列表: {json.dumps(payload, ensure_ascii=False)}"
    )


def _parse_resolution_batch_response(content: Any) -> UnitResolutionBatch:
    text = str(content or "")
    if isinstance(content, list):
        text = "".join(str(part) for part in content)
    try:
        from app.infrastructure.llm.dimension_runtime import strip_model_reasoning

        text = strip_model_reasoning(text)
    except Exception:  # noqa: BLE001
        pass
    payload = _extract_json_payload(text)
    if isinstance(payload, list):
        payload = {"resolutions": payload}
    if not isinstance(payload, dict):
        return UnitResolutionBatch()
    try:
        return UnitResolutionBatch.model_validate(payload)
    except ValidationError:
        return UnitResolutionBatch()


def _extract_json_payload(text: str) -> Any:
    stripped = text.strip()
    for candidate in (stripped,):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        match = re.search(pattern, stripped)
        if match is None:
            continue
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
    return None


async def flash_repair_units(draft_set: Any, session_id: str) -> Any:
    deterministic_batch, unresolved = resolve_units_deterministically(draft_set)
    if not deterministic_batch.resolutions and not unresolved:
        return draft_set
    repaired = draft_set.model_copy(deep=True) if hasattr(draft_set, "model_copy") else draft_set
    deterministic_applied = apply_unit_resolution_batch(repaired, deterministic_batch)
    if not unresolved:
        return repaired
    from app.infrastructure.llm.factory import create_flash_llm

    llm = create_flash_llm(max_tokens=600, temperature=0.0)
    prompt = _build_llm_prompt(unresolved)
    try:
        import asyncio

        response = (
            await llm.ainvoke(prompt)
            if asyncio.iscoroutinefunction(getattr(llm, "ainvoke", None))
            else llm.invoke(prompt)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[flash_unit_repair] llm call failed for %s: %s", session_id, exc)
        return repaired
    llm_batch = _parse_resolution_batch_response(getattr(response, "content", ""))
    unresolved_keys = {(item.claim_id, item.field_path, item.raw_unit) for item in unresolved}
    filtered = UnitResolutionBatch(
        resolutions=[
            item
            for item in llm_batch.resolutions
            if (item.claim_id, item.field_path, item.raw_unit) in unresolved_keys
        ]
    )
    llm_applied = apply_unit_resolution_batch(repaired, filtered)
    if deterministic_applied or llm_applied:
        logger.info(
            "[flash_unit_repair] session=%s applied=%d unresolved=%d",
            session_id,
            deterministic_applied + llm_applied,
            len(unresolved),
        )
    return repaired


__all__ = [
    "UnitResolution",
    "UnitResolutionBatch",
    "apply_unit_resolution_batch",
    "collect_unknown_units",
    "flash_repair_units",
    "resolve_units_deterministically",
]
