from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

_DEG2_HA = 110.9 * 101.0 * 100.0
_SCALE_HA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(公顷|万平方米|亩|㎡|平方米)")
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def compute_area_ha(geometry: Dict[str, Any]) -> float:
    if not geometry:
        return 0.0
    from shapely.geometry import shape

    try:
        geom = shape(geometry)
    except Exception:
        return 0.0
    if geom.is_empty:
        return 0.0
    return geom.area * _DEG2_HA


def parse_scale_ha(scale_text: str) -> Optional[float]:
    text = (scale_text or "").strip()
    if not text:
        return None
    m = _SCALE_HA_RE.search(text)
    if not m:
        cn = re.search(r"占地\s*([一二三四五六七八九十]+)\s*亩", text)
        if not cn:
            return None
        num = _CN_NUM.get(cn.group(1))
        return num / 15.0 if num is not None else None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "公顷":
        return value
    if unit == "万平方米":
        return value
    if unit == "亩":
        return value / 15.0
    return value / 10000.0
