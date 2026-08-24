"""Parcel footprint generation via OBB (Oriented Bounding Box) recursive split.

Pure geometry module (shapely only, plus ``math`` / ``typing``).  Implements the
Vanegas et al. (Eurographics 2012) parcel-subdivision idea: carve a parcel along
its minimum-rotated-rectangle axes so that the first fragment matches a target
footprint area as closely as possible.

Method
------
1. ``polygon.minimum_rotated_rectangle`` gives the OBB of the parcel.
2. The two OBB edge directions define the axes; the long axis is the "split
   direction" and the short axis is the frontage.
3. The target fragment area (m^2) is ``target_area_ha * 10000``.
4. A split line perpendicular to the long axis is placed at distance
   ``target_area / frontage_length`` from the front edge; ``shapely.ops.split``
   cuts off the target-area strip from the front of the parcel.
5. The remainder is subdivided recursively; each recursion carves another
   target-sized fragment from its own front edge.
6. Fragments smaller than ``min_area_ha`` (default 0.1% of the target area) are
   merged into the adjacent fragment with the longest shared boundary.
7. The first returned fragment is the project footprint; the rest are
   remainders.

Units: polygon coordinates are assumed to be metres; areas in m^2 are converted
to hectares by dividing by 10 000.

Functions
---------
apply_setback
    Shrink a polygon inward by ``setback_m`` via ``buffer(-setback_m)``.
obb_subdivide
    Recursively split a parcel into fragments as close as possible to
    ``target_area_ha``; the first fragment is the project footprint.
split_for_footprint
    Convenience wrapper returning ``(project_footprint, remainders)``.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from shapely.geometry import LineString, Polygon
from shapely.ops import split, unary_union

_HA = 10000.0
_MAX_RECURSION_DEPTH = 64


def apply_setback(polygon: Polygon, setback_m: float) -> Polygon:
    """Shrink ``polygon`` inward by ``setback_m`` metres.

    Returns the original polygon unchanged when ``setback_m`` is not positive
    or when the inward buffer is empty or invalid.
    """
    if setback_m is None or setback_m <= 0:
        return polygon
    buf = polygon.buffer(-float(setback_m))
    if buf.is_empty or not buf.is_valid:
        return polygon
    if buf.geom_type == "Polygon":
        return buf
    if buf.geom_type == "MultiPolygon" and not buf.is_empty:
        parts = sorted(buf.geoms, key=lambda g: g.area, reverse=True)
        return parts[0]
    return polygon


def _edge_length(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _unit(vx: float, vy: float) -> Tuple[float, float]:
    length = math.hypot(vx, vy)
    if length <= 0.0:
        return (0.0, 0.0)
    return (vx / length, vy / length)


def _as_polygon(geom) -> Optional[Polygon]:
    """Return a valid Polygon (largest part of a MultiPolygon), else None."""
    if geom is None:
        return None
    if geom.geom_type == "Polygon" and geom.is_valid:
        return geom
    if geom.geom_type == "MultiPolygon" and not geom.is_empty:
        parts = sorted(geom.geoms, key=lambda g: g.area, reverse=True)
        best = parts[0]
        return best if best.is_valid else best.buffer(0)
    if geom.is_empty:
        return None
    cleaned = geom.buffer(0)
    if cleaned.geom_type == "Polygon" and cleaned.is_valid:
        return cleaned
    if cleaned.geom_type == "MultiPolygon" and not cleaned.is_empty:
        parts = sorted(cleaned.geoms, key=lambda g: g.area, reverse=True)
        return parts[0]
    return None


def _obb_params(polygon: Polygon):
    """OBB geometry of ``polygon`` as a dict, or None for degenerate input."""
    obb = polygon.minimum_rotated_rectangle
    if obb.geom_type != "Polygon":
        return None
    coords = list(obb.exterior.coords)[:-1]
    if len(coords) != 4:
        return None
    lengths = [_edge_length(coords[i], coords[(i + 1) % 4]) for i in range(4)]
    if min(lengths) <= 0.0:
        return None
    short_idx = min(range(4), key=lambda i: lengths[i])
    return {
        "coords": coords,
        "lengths": lengths,
        "short_idx": short_idx,
    }


def _split_strip(
    polygon: Polygon,
    a: Tuple[float, float],
    b: Tuple[float, float],
    interior_dir: Tuple[float, float],
    depth: float,
) -> Tuple[Optional[Polygon], Optional[Polygon]]:
    """Cut ``polygon`` with a line parallel to the front edge ``(a, b)``.

    The line sits ``depth`` metres inward along ``interior_dir`` and is extended
    far beyond the polygon so that ``shapely.ops.split`` yields clean pieces.
    Returns ``(front, rest)``; ``(None, None)`` on failure.
    """
    pa = (a[0] + interior_dir[0] * depth, a[1] + interior_dir[1] * depth)
    pb = (b[0] + interior_dir[0] * depth, b[1] + interior_dir[1] * depth)
    u = _unit(b[0] - a[0], b[1] - a[1])
    x0, y0, x1, y1 = polygon.bounds
    extend = math.hypot(x1 - x0, y1 - y0) + 1.0
    q1 = (pa[0] - u[0] * extend, pa[1] - u[1] * extend)
    q2 = (pb[0] + u[0] * extend, pb[1] + u[1] * extend)
    result = split(polygon, LineString([q1, q2]))
    pieces = [g for g in result.geoms if g.geom_type == "Polygon" and g.area > 1e-9]
    if len(pieces) < 2:
        return None, None

    def _proj(g: Polygon) -> float:
        p = g.representative_point()
        return p.x * interior_dir[0] + p.y * interior_dir[1]

    split_pos = pa[0] * interior_dir[0] + pa[1] * interior_dir[1]
    front_pieces = [g for g in pieces if _proj(g) <= split_pos + 1e-9]
    rest_pieces = [g for g in pieces if _proj(g) > split_pos + 1e-9]
    if not front_pieces or not rest_pieces:
        return None, None
    front = _as_polygon(front_pieces[0] if len(front_pieces) == 1 else unary_union(front_pieces))
    rest = _as_polygon(rest_pieces[0] if len(rest_pieces) == 1 else unary_union(rest_pieces))
    if front is None or rest is None or front.area <= 0.0 or rest.area <= 0.0:
        return None, None
    return front, rest


def _cut_strip_from_edge(
    polygon: Polygon,
    a: Tuple[float, float],
    b: Tuple[float, float],
    interior_dir: Tuple[float, float],
    target_m2: float,
    exact_search: bool = True,
) -> Tuple[Optional[Polygon], Optional[Polygon]]:
    frontage = _edge_length(a, b)
    if frontage <= 0.0:
        return None, None
    direct = _split_strip(polygon, a, b, interior_dir, target_m2 / frontage)
    if not exact_search:
        return direct
    if direct[0] is not None and direct[1] is not None:
        direct_error = abs(direct[0].area - target_m2)
        if direct_error <= max(target_m2 * 0.005, 1e-6):
            return direct

    # The OBB frontage is only an estimate for concave/irregular parcels.  A
    # fixed depth can therefore produce a materially undersized first piece.
    # Search the cut depth against the actual polygon area so the selected
    # footprint is bounded by the requested tolerance rather than by the
    # rectangle approximation.
    coords = list(polygon.exterior.coords)
    projections = [point[0] * interior_dir[0] + point[1] * interior_dir[1] for point in coords]
    if not projections:
        return direct
    low = 0.0
    high = max(projections) - min(projections)
    best: Tuple[Optional[Polygon], Optional[Polygon]] = (None, None)
    best_error = float("inf")
    for _ in range(40):
        depth = (low + high) / 2.0
        candidate = _split_strip(polygon, a, b, interior_dir, depth)
        front, rest = candidate
        if front is None or rest is None:
            high = depth
            continue
        error = abs(front.area - target_m2)
        if error < best_error:
            best = candidate
            best_error = error
        if front.area < target_m2:
            low = depth
        else:
            high = depth
    return best if best[0] is not None and best[1] is not None else direct


def _cut_front(
    polygon: Polygon,
    target_m2: float,
    params,
    mode: str,
    exact_search: bool = True,
):
    """Cut a ``target_m2`` strip from the front of ``polygon``.

    ``mode == "long"`` cuts along the OBB long axis (frontage = short edge);
    ``mode == "width"`` cuts along the short axis (frontage = long edge), used
    as a fallback for non-convex parcels.
    """
    coords = params["coords"]
    short_idx = params["short_idx"]
    if mode == "width":
        a = coords[(short_idx + 1) % 4]
        b = coords[(short_idx + 2) % 4]
        interior_dir = _unit(coords[short_idx][0] - a[0], coords[short_idx][1] - a[1])
        return _cut_strip_from_edge(
            polygon, a, b, interior_dir, target_m2, exact_search=exact_search
        )
    a = coords[short_idx]
    b = coords[(short_idx + 1) % 4]
    nxt = coords[(short_idx + 2) % 4]
    interior_dir = _unit(nxt[0] - b[0], nxt[1] - b[1])
    return _cut_strip_from_edge(
        polygon, a, b, interior_dir, target_m2, exact_search=exact_search
    )


def _merge_slivers(fragments: List[Polygon], min_ha: Optional[float], target_m2: float) -> List[Polygon]:
    """Merge fragments below the sliver threshold into an adjacent fragment."""
    if min_ha is None:
        min_ha = 0.001 * (target_m2 / _HA)
    threshold = min_ha * _HA
    result: List[Polygon] = []
    for frag in fragments:
        if frag.area >= threshold:
            result.append(frag)
            continue
        best_idx = None
        best_len = -1.0
        for i, other in enumerate(result):
            shared = frag.intersection(other)
            if shared.is_empty:
                continue
            if shared.geom_type in ("LineString", "MultiLineString"):
                shared_len = shared.length
            else:
                shared_len = 0.0
            if shared_len > best_len:
                best_len = shared_len
                best_idx = i
        if best_idx is None:
            if result:
                merged = _as_polygon(result[-1].union(frag))
                if merged is not None:
                    result[-1] = merged
                    continue
            result.append(frag)
        else:
            merged = _as_polygon(result[best_idx].union(frag))
            if merged is not None:
                result[best_idx] = merged
            else:
                result.append(frag)
    return result


def _subdivide(
    polygon: Polygon,
    target_m2: float,
    tolerance_pct: float,
    min_ha: Optional[float],
    depth: int,
    exact_search: bool,
) -> List[Polygon]:
    area = polygon.area
    if area <= 0.0 or not polygon.is_valid:
        return [polygon] if area > 0.0 else []
    if abs(area - target_m2) / max(area, target_m2) * 100.0 <= tolerance_pct:
        return [polygon]
    if area <= target_m2 * (1.0 + tolerance_pct / 100.0):
        return [polygon]
    if depth <= 0:
        return [polygon]
    params = _obb_params(polygon)
    if params is None:
        return [polygon]
    front, rest = _cut_front(
        polygon, target_m2, params, "long", exact_search=exact_search
    )
    if front is None or rest is None:
        front, rest = _cut_front(
            polygon, target_m2, params, "width", exact_search=exact_search
        )
    if front is None or rest is None:
        return [polygon]
    fragments = [front] + _subdivide(
        rest, target_m2, tolerance_pct, min_ha, depth - 1, exact_search
    )
    return _merge_slivers(fragments, min_ha, target_m2)


def obb_subdivide(
    polygon: Polygon,
    target_area_ha: float,
    tolerance_pct: float = 5.0,
    min_area_ha: Optional[float] = None,
    exact_search: bool = True,
) -> List[Polygon]:
    """Recursively split ``polygon`` into fragments near ``target_area_ha``.

    The first returned fragment is the project footprint (closest to the target
    area); the remaining fragments are the remainders.  When the parcel is
    already within ``tolerance_pct`` of the target, ``[polygon]`` is returned.
    """
    if polygon is None or polygon.is_empty:
        return []
    poly = _as_polygon(polygon)
    if poly is None:
        return []
    target_m2 = target_area_ha * _HA
    if target_m2 <= 0.0:
        return [poly]
    return _subdivide(
        poly,
        target_m2,
        tolerance_pct,
        min_area_ha,
        _MAX_RECURSION_DEPTH,
        exact_search,
    )


def split_for_footprint(
    polygon: Polygon,
    target_area_ha: float,
    tolerance_pct: float = 5.0,
    exact_search: bool = True,
) -> Tuple[Polygon, List[Polygon]]:
    """Split ``polygon`` into ``(project_footprint, remainders)``.

    ``remainders`` is empty when no split was needed.  Raises ``ValueError`` if
    the parcel area (ha) is smaller than ``target_area_ha``.
    """
    area_ha = polygon.area / _HA
    if area_ha < target_area_ha:
        raise ValueError(
            f"parcel area {area_ha:.4f} ha is smaller than target footprint "
            f"{target_area_ha} ha"
        )
    fragments = obb_subdivide(
        polygon,
        target_area_ha,
        tolerance_pct=tolerance_pct,
        exact_search=exact_search,
    )
    if not fragments:
        return polygon, []
    # Recursive OBB splitting can encounter an irregular front edge where the
    # first strip is a very small sliver even though a later fragment is much
    # closer to the requested footprint.  The caller treats the first item as
    # the executable footprint, so choosing by area is part of the contract;
    # relying on traversal order would materialize an arbitrary sliver.
    target_m2 = float(target_area_ha) * _HA
    footprint_index = min(
        range(len(fragments)),
        key=lambda index: (
            abs(float(fragments[index].area) - target_m2),
            -float(fragments[index].area),
            index,
        ),
    )
    footprint = fragments[footprint_index]
    remainders = [
        fragment for index, fragment in enumerate(fragments)
        if index != footprint_index
    ]
    return footprint, remainders
