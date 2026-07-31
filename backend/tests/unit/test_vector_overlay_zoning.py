from shapely.geometry import Polygon

from app.modules.kg.ontology import ThreeLineSubtypes
from app.tools.gis._generation.vector_overlay_zoning import (
    compute_control_codes,
    compute_planning_zones,
)


def test_parcel_inside_ecological_redline_gets_04():
    boundary = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    eco = Polygon([(6, 6), (8, 6), (8, 8), (6, 8)])
    parcel = {
        "bsm": "P1",
        "dlbm": "0301",
        "geometry": Polygon([(6.5, 6.5), (7.5, 6.5), (7.5, 7.5), (6.5, 7.5)]),
    }
    three_lines = {
        ThreeLineSubtypes.ECOLOGICAL_REDLINE: [{"bsm": "EL1", "geometry": eco}],
    }
    codes, audit = compute_control_codes([parcel], three_lines, boundary)
    assert codes["P1"] == "04"
    missing = audit.missing_layers()
    sources = {e.source for e in missing}
    assert "missing:gd_urban_dev_boundary" in sources


def test_parcel_inside_farmland_redline_classified_by_dlbm():
    boundary = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    farm = Polygon([(2, 2), (5, 2), (5, 5), (2, 5)])
    constructed = {
        "bsm": "P1",
        "dlbm": "0702",  # 农村宅基地 (construction)
        "geometry": Polygon([(2.5, 2.5), (3.5, 2.5), (3.5, 3.5), (2.5, 3.5)]),
    }
    agricultural = {
        "bsm": "P2",
        "dlbm": "0101",  # 水田 (non-construction)
        "geometry": Polygon([(3.6, 2.5), (4.4, 2.5), (4.4, 3.5), (3.6, 3.5)]),
    }
    three_lines = {
        ThreeLineSubtypes.FARMLAND_REDLINE: [{"bsm": "FL1", "geometry": farm}],
    }
    codes, audit = compute_control_codes([constructed, agricultural], three_lines, boundary)
    assert codes["P1"] == "05"
    assert codes["P2"] == "06"


def test_parcel_only_in_boundary_gets_02():
    boundary = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    parcel = {
        "bsm": "P1",
        "dlbm": "0301",
        "geometry": Polygon([(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]),
    }
    codes, _ = compute_control_codes([parcel], {}, boundary)
    assert codes["P1"] == "02"


def test_parcel_in_urban_dev_boundary_gets_03():
    boundary = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    udb = Polygon([(1, 1), (4, 1), (4, 4), (1, 4)])
    parcel = {
        "bsm": "P1",
        "dlbm": "0301",
        "geometry": Polygon([(1.5, 1.5), (2.5, 1.5), (2.5, 2.5), (1.5, 2.5)]),
    }
    three_lines = {ThreeLineSubtypes.URBAN_DEV_BOUNDARY: [{"bsm": "U1", "geometry": udb}]}
    codes, _ = compute_control_codes([parcel], three_lines, boundary)
    assert codes["P1"] == "03"


def test_parcel_outside_boundary_excluded():
    boundary = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
    far_parcel = {
        "bsm": "P1",
        "dlbm": "0301",
        "geometry": Polygon([(20, 20), (21, 20), (21, 21), (20, 21)]),
    }
    codes, _ = compute_control_codes([far_parcel], {}, boundary)
    assert "P1" not in codes


def test_planning_zones_assigns_by_spatial_containment():
    parcels = [
        {"bsm": "P1", "geometry": Polygon([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)])},
        {"bsm": "P2", "geometry": Polygon([(4.5, 4.5), (5.5, 4.5), (5.5, 5.5), (4.5, 5.5)])},
    ]
    upper_plan = {
        "生态保护区": [{"bsm": "UP1", "geometry": Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])}],
        "村庄建设区": [{"bsm": "UP2", "geometry": Polygon([(4, 4), (6, 4), (6, 6), (4, 6)])}],
    }
    zones, audit = compute_planning_zones(parcels, upper_plan)
    assert zones["P1"] == "生态保护区"
    assert zones["P2"] == "村庄建设区"
    sources = {e.source for e in audit.report()}
    assert "derived:upper_plan_overlay" in sources


def test_planning_zones_missing_upper_plan_audits_and_returns_empty():
    parcels = [{"bsm": "P1", "geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])}]
    zones, audit = compute_planning_zones(parcels, {})
    assert zones == {}
    missing = audit.missing_layers()
    assert any(e.layer == "planning_zone" and "upper_plan" in e.source for e in missing)