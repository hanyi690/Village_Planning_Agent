from pathlib import Path
from types import SimpleNamespace

from app.modules.spatial_ops.selection import (
    CandidateParcel,
    _PROHIBITED_CONSTRAINTS,
    apply_hard_filters,
)

_POLY = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.0, 0.01], [0.01, 0.01], [0.01, 0.0], [0.0, 0.0]]],
}


def _parcel(bsm: str, area_ha: float) -> CandidateParcel:
    return CandidateParcel(bsm=bsm, geometry=_POLY, dlmc="空闲宅基地", area_ha=area_ha)


class _FakeConstraintIndex:
    def geometry_in_constraint(self, geometry):
        return [SimpleNamespace(constraint_type="farmland_protection")]


def test_min_area_rejects_small_parcel():
    survivors, rejected = apply_hard_filters([_parcel("A", 0.5)], min_area_ha=1.0)
    assert survivors == []
    assert len(rejected) == 1
    assert rejected[0].reason == "hard_filter"
    assert "below_min_area" in rejected[0].detail[0]


def test_min_area_zero_default_no_filter():
    survivors, rejected = apply_hard_filters([_parcel("A", 0.5)])
    assert [s.bsm for s in survivors] == ["A"]
    assert rejected == []


def test_min_area_meets_threshold():
    survivors, rejected = apply_hard_filters([_parcel("A", 2.0)], min_area_ha=1.0)
    assert [s.bsm for s in survivors] == ["A"]
    assert rejected == []


def test_min_area_combines_with_constraint():
    survivors, rejected = apply_hard_filters(
        [_parcel("A", 0.5)],
        min_area_ha=1.0,
        constraint_index=_FakeConstraintIndex(),
    )
    assert survivors == []
    assert len(rejected) == 1
    assert len(rejected[0].detail) == 2
    assert any(d.startswith("constraint:") for d in rejected[0].detail)
    assert any(d.startswith("below_min_area:") for d in rejected[0].detail)


def test_execute_agent_imports_prohibited():
    source = Path(__file__).resolve().parents[3] / "app" / "agent" / "execute" / "execute_agent.py"
    text = source.read_text(encoding="utf-8-sig")
    assert "prohibited = {" not in text
    assert "_PROHIBITED_CONSTRAINTS as prohibited" in text


def test_apply_hard_filters_import_path():
    assert _PROHIBITED_CONSTRAINTS == {
        "farmland_protection",
        "ecological_redline",
        "historical_protection",
        "cultivated_land_target",
        "hazard_control_line",
        "flood_control_line",
    }
