"""Unit and enum normalization for L3 structured claim output.

Real runs showed LLM outputs repeatedly failing schema compile with
``unsupported_measure_unit`` (e.g. a mojibake ``Ķ`` unit) and
``invalid_intervention_action`` (e.g. ``upgrade`` for a project).  Root cause
is structural: the provider-facing drafts use free strings with no encoding
repair, no alias table and no fuzzy tolerance (exa: repair encoding first,
normalize compatibility chars, fuzzy-match enum fields).

This module is the deterministic post-hoc normalization layer:
1. encoding/typography repair (NFKC + control-char strip + mojibake repair)
2. alias table (common Chinese/English/abbrev unit spellings)
3. difflib nearest-match for unknown units/actions
"""
from __future__ import annotations

import unicodedata
from difflib import get_close_matches

_UNIT_ALIASES: dict[str, str] = {
    # length
    "m": "m", "meter": "m", "metre": "m", "meters": "m", "metres": "m",
    "米": "m", "公尺": "m",
    "km": "km", "kilometer": "km", "kilometre": "km", "kilometers": "km",
    "公里": "km", "千米": "km",
    "cm": "cm", "centimeter": "cm", "厘米": "cm",
    "mm": "mm", "millimeter": "mm", "毫米": "mm",
    # area
    "ha": "ha", "hectare": "ha", "hectares": "ha", "公顷": "ha",
    "hm2": "ha", "hm²": "ha", "square hectometer": "ha", "平方百米": "ha",
    "亩": "mu", "mou": "mu",
    "m2": "m2", "m2": "m2", "sqm": "m2", "sq m": "m2", "square meter": "m2",
    "square meters": "m2", "square metre": "m2", "平方米": "m2", "平米": "m2",
    "km2": "km2", "km2": "km2", "平方公里": "km2", "平方千米": "km2",
    # volume / capacity
    "m3": "m3", "m3": "m3", "cubic meter": "m3", "立方米": "m3",
    "l": "l", "liter": "l", "litre": "l", "升": "l",
    "t": "t", "ton": "t", "tonne": "t", "吨": "t",
    # count
    "个": "个", "处": "处", "座": "座", "条": "条", "棵": "棵", "株": "株",
    "人": "人", "户": "户", "家": "家", "间": "间", "栋": "栋",
    "kw": "kw", "千瓦": "kw", "kwh": "kwh", "千瓦时": "kwh",
}

_ACTION_ALIASES: dict[str, str] = {
    "新建": "new", "新": "new", "建设": "new", "新增": "new",
    "保留": "preserve", "保护": "preserve", "现状": "preserve",
    "扩建": "expand", "改扩建": "expand", "扩容": "expand",
    "搬迁": "relocate", "迁建": "relocate", "异地重建": "relocate",
    "提升": "upgrade", "升级": "upgrade", "提质": "upgrade", "改造": "upgrade",
    "加宽": "widen", "拓宽": "widen", "扩宽": "widen",
    "加固": "harden", "硬化": "harden", "防护": "harden",
    "修复": "repair", "修缮": "repair", "整治": "repair", "维修": "repair",
    "拆除": "demolish", "拆": "demolish",
}


def _strip_control(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")


def _repair_mojibake(text: str) -> str:
    """Repair common mojibake patterns from GBK/UTF-8 / latin-1 mixups."""
    if not text:
        return text
    fixed = text
    for broken, good in (
        ("\ufffd", ""),
    ):
        fixed = fixed.replace(broken, good)
    try:
        fixed = unicodedata.normalize("NFKC", fixed)
    except Exception:  # noqa: BLE001
        pass
    return _strip_control(fixed)


def normalize_unit(raw: str) -> str:
    """Canonicalize a raw unit string (repair + alias + fuzzy fallback)."""
    text = _repair_mojibake(str(raw or "")).strip().lower().replace(" ", "")
    if not text:
        return ""
    if text in _UNIT_ALIASES:
        return _UNIT_ALIASES[text]
    stripped = text.strip(".,;:，；。:")
    if stripped and stripped in _UNIT_ALIASES:
        return _UNIT_ALIASES[stripped]
    close = get_close_matches(text, list(_UNIT_ALIASES.keys()), n=1, cutoff=0.82)
    if close:
        return _UNIT_ALIASES[close[0]]
    return text


def normalize_action(raw: str, allowed: set[str] | None = None) -> str:
    """Canonicalize an action string; fall back to fuzzy nearest or '' if none."""
    text = _repair_mojibake(str(raw or "")).strip().lower()
    if not text:
        return ""
    valid = allowed or {"preserve", "new", "expand", "relocate", "upgrade",
                        "widen", "harden", "repair", "demolish"}
    if text in valid:
        return text
    if text in _ACTION_ALIASES:
        return _ACTION_ALIASES[text]
    close = get_close_matches(text, sorted(valid), n=1, cutoff=0.75)
    if close:
        return close[0]
    return text


__all__ = ["normalize_unit", "normalize_action"]
