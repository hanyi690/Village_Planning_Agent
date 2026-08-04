import pytest

from app.modules.spatial_ops.selection import compute_area_ha, parse_scale_ha


def test_compute_area_ha_square():
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    ha = compute_area_ha(geometry)
    assert 1_000_000 < ha < 1_300_000


def test_compute_area_ha_invalid():
    assert compute_area_ha(None) == 0.0
    assert compute_area_ha({"type": "Polygon", "coordinates": []}) == 0.0


def test_parse_scale_ha():
    assert parse_scale_ha("0.15公顷") == 0.15
    assert parse_scale_ha("占地3亩") == 0.2
    assert parse_scale_ha("1500㎡") == 0.15
    assert parse_scale_ha("约2万平方米") == 2.0
    assert parse_scale_ha("占地十亩") == pytest.approx(10 / 15.0)
    assert parse_scale_ha("") is None
    assert parse_scale_ha("无规模信息") is None


from app.modules.spatial_ops.selection import SelectionTarget, is_large_block_target


def test_is_large_block_target():
    assert is_large_block_target(SelectionTarget(target_id="z1", category="zone")) is True
    assert is_large_block_target(SelectionTarget(target_id="p1", name="南药种植基地")) is True
    assert is_large_block_target(SelectionTarget(target_id="p2", scale_text="占地3亩")) is False
    assert is_large_block_target(SelectionTarget(target_id="p3", scale_text="0.15公顷")) is False
