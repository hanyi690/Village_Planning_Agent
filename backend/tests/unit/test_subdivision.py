"""Unit tests for subdivision.py (OBB parcel footprint generation)."""

from __future__ import annotations

import math

import pytest
from shapely.geometry import Polygon, box

from app.modules.spatial_ops.geometry.subdivision import (
    apply_setback,
    obb_subdivide,
    split_for_footprint,
)


def _area_ha(polygon: Polygon) -> float:
    return polygon.area / 10000.0


def test_split_for_footprint_rectangular_parcel():
    parcel = box(0, 0, 316, 316)
    footprint, remainders = split_for_footprint(parcel, 5.0)
    assert 5.0 * 0.95 <= _area_ha(footprint) <= 5.0 * 1.05
    total = footprint.area + sum(r.area for r in remainders)
    assert math.isclose(total, parcel.area, rel_tol=0.01, abs_tol=1.0)


def test_apply_setback_reduces_area():
    parcel = box(0, 0, 316, 316)
    setback = apply_setback(parcel, 10)
    assert setback.is_valid
    assert setback.geom_type == "Polygon"
    expected = (316.0 - 2 * 10.0) ** 2
    assert math.isclose(setback.area, expected, rel_tol=1e-6)
    expected_decrease = 4.0 * 10.0 * 316.0 - 4.0 * 100.0
    assert math.isclose(parcel.area - setback.area, expected_decrease, rel_tol=1e-6)


def test_apply_setback_erases_polygon_returns_original():
    parcel = box(0, 0, 10, 10)
    assert apply_setback(parcel, 20) == parcel


def test_obb_subdivide_parcel_already_target_returns_single():
    parcel = box(0, 0, 250, 200)
    fragments = obb_subdivide(parcel, 5.0)
    assert len(fragments) == 1
    assert fragments[0] == parcel


def test_split_for_footprint_no_split_remainder_empty():
    parcel = box(0, 0, 250, 200)
    footprint, remainders = split_for_footprint(parcel, 5.0)
    assert remainders == []
    assert _area_ha(footprint) == pytest.approx(5.0, rel=1e-6)


def test_split_for_footprint_parcel_smaller_than_target_raises():
    parcel = box(0, 0, 100, 100)
    with pytest.raises(ValueError):
        split_for_footprint(parcel, 5.0)


def test_obb_subdivide_l_shape_non_convex():
    l_shape = Polygon(
        [(0, 0), (300, 0), (300, 100), (100, 100), (100, 300), (0, 300)]
    )
    fragments = obb_subdivide(l_shape, 2.0)
    assert len(fragments) >= 1
    total = sum(f.area for f in fragments)
    assert math.isclose(total, l_shape.area, rel_tol=0.05, abs_tol=1.0)
