"""Coordinate identity — 同一坐标就是同一实体（ER 原则）。

纯空间工具，几何数学只允许出现在 ``app.spatial``。domain/ground 编排器通过这里
做实体按坐标合并/去重；坐标永远来自 bundle/KG，LLM 不参与。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional, Tuple

_POINT_RE = re.compile(r"POINT\(\s*([-\d.eE]+)\s+([-\d.eE]+)\s*\)")


def point_xy(geometry_ref: Optional[str]) -> Optional[Tuple[float, float]]:
    """Extract (lon, lat) from a POINT(...) geometry ref.

    Handles both bare ``POINT(x y)`` and prefixed ``kg_wkt:POINT(x y)`` /
    ``bundled:...`` forms so co-location comparison is format-independent.
    """
    if not geometry_ref:
        return None
    m = _POINT_RE.search(geometry_ref)
    if not m:
        return None
    try:
        return (float(m.group(1)), float(m.group(2)))
    except (TypeError, ValueError):
        return None


def same_coordinate(
    a: Optional[str],
    b: Optional[str],
    tol: float = 1e-5,
) -> bool:
    """Two geometry refs are the same real-world point within ``tol`` degrees."""
    xy_a = point_xy(a)
    xy_b = point_xy(b)
    if xy_a is None or xy_b is None:
        return False
    return (
        abs(xy_a[0] - xy_b[0]) < tol
        and abs(xy_a[1] - xy_b[1]) < tol
    )


def coordinate_key(
    geometry_ref: Optional[str],
    decimals: int = 6,
) -> str:
    """Stable identity key for an entity's location ("" when no geometry).

    Rounded to ``decimals`` so near-identical coordinates collapse to one key
    (the "same coordinates = same entity" invariant).
    """
    xy = point_xy(geometry_ref)
    if xy is None:
        return ""
    return f"{round(xy[0], decimals)},{round(xy[1], decimals)}"


def bsm_key(bsms: Iterable[str]) -> str:
    """A stable key from the source BSM set (empty when none)."""
    ordered = sorted(str(b) for b in bsms if b)
    return "|".join(ordered)


def merge_by_coordinate(
    items: Iterable[Any],
    *,
    geometry_ref_getter,
    key_getter=None,
    tol: float = 1e-5,
) -> list[Any]:
    """Merge items whose geometries are co-located into one representative.

    ``geometry_ref_getter(item)`` returns the geometry ref; ``key_getter(item)``
    is an optional secondary discriminator (e.g. role). Items without geometry
    are kept as-is (they cannot be merged by coordinate).
    """
    kept: list[Any] = []
    for item in items:
        ref = geometry_ref_getter(item)
        if ref is None:
            kept.append(item)
            continue
        target = None
        for existing in kept:
            existing_ref = geometry_ref_getter(existing)
            if existing_ref is None:
                continue
            if key_getter is not None and key_getter(existing) != key_getter(item):
                continue
            if same_coordinate(existing_ref, ref, tol=tol):
                target = existing
                break
        if target is None:
            kept.append(item)
        else:
            yield_merge(target, item)
    return kept


def yield_merge(target: Any, item: Any) -> None:
    """Best-effort merge of ``item`` into ``target`` when both are Pydantic."""
    try:
        for field in ("aliases", "source_bsms", "entity_refs", "relation_refs", "evidence_refs", "topology_evidence"):
            if hasattr(target, field) and hasattr(item, field):
                values = list(getattr(target, field) or [])
                for v in list(getattr(item, field) or []):
                    if v not in values:
                        values.append(v)
                setattr(target, field, values)
        if hasattr(target, "confidence") and hasattr(item, "confidence"):
            try:
                target.confidence = max(float(target.confidence or 0.0), float(item.confidence or 0.0))
            except (TypeError, ValueError):
                pass
        if hasattr(target, "query_trace") and hasattr(item, "query_trace"):
            trace = list(getattr(target, "query_trace") or [])
            trace.append({"step": "coordinate_merge", "merged": getattr(item, "mention", "") or getattr(item, "canonical_name", "")})
            setattr(target, "query_trace", trace)
    except Exception:
        pass


__all__ = [
    "point_xy",
    "same_coordinate",
    "coordinate_key",
    "bsm_key",
    "merge_by_coordinate",
    "yield_merge",
]