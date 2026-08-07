"""VALIDATE checks: 8 deterministic validation check functions (Wave J Task 1)."""

from types import SimpleNamespace

from app.agent.validate.checks import (
    check_accessibility,
    check_area_conservation,
    check_classification_missing,
    check_contract_completeness,
    check_continuity,
    check_hard_constraints,
    check_overlap,
    check_topology,
)
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.modules.schema.contracts.parse_contracts import ProjectTarget, SpatialPlanningIntent
from app.modules.schema.contracts.planned_state_contracts import PlannedFacility, PlannedParcel, PlannedState

WKT = "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))"

UNIT_SQUARE = [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]
UNIT_SQUARE_B = [[2.0, 2.0], [2.0, 3.0], [3.0, 3.0], [3.0, 2.0], [2.0, 2.0]]


def make_planned_state(parcels=None):
    return PlannedState(parcels=list(parcels or []))


def make_parcel(bsm, planning_land_use="", operation="preserve", geometry_wkt=WKT):
    return PlannedParcel(
        bsm=bsm,
        planning_land_use=planning_land_use,
        operation=operation,
        geometry=geometry_wkt,
    )


def make_changeset(changes=None, area_conservation_verified=False, geometry_validity_verified=True):
    return ParcelChangeSet(
        changes=list(changes or []),
        area_conservation_verified=area_conservation_verified,
        geometry_validity_verified=geometry_validity_verified,
    )


def make_change(action, bsm, before_wkt="", after_wkt="", before_area=0.0, after_area=0.0, derived=None):
    return ParcelChange(
        bsm=bsm,
        action=action,
        derived_from_bsms=list(derived or []),
        before_geometry_wkt=before_wkt,
        after_geometry_wkt=after_wkt,
        new_area_ha=after_area,
    )


def make_layout_configs(layer_type, features):
    return [
        {
            "layerType": layer_type,
            "data": {"type": "FeatureCollection", "features": list(features)},
        }
    ]


def polygon_feature(coords, name=""):
    return {
        "type": "Feature",
        "properties": {"name": name},
        "geometry": {"type": "Polygon", "coordinates": [coords]},
    }


class FakeConstraintIndex:
    def __init__(self, overlaps):
        self._overlaps = overlaps

    def geometry_in_constraint(self, geometry):
        return self._overlaps


def test_check_hard_constraints_violation():
    state = make_planned_state(parcels=[make_parcel("P001", "0701", "reclassify")])
    idx = FakeConstraintIndex([SimpleNamespace(constraint_type="farmland_protection")])
    checks = check_hard_constraints(state, idx)
    assert len(checks) == 1
    assert checks[0].passed is False
    assert checks[0].responsible_stage == "SELECT"
    assert checks[0].affected_parcels == ["P001"]


def test_check_hard_constraints_pass():
    state = make_planned_state(parcels=[make_parcel("P001", "0701", "reclassify")])
    checks = check_hard_constraints(state, FakeConstraintIndex([]))
    assert checks[0].passed is True


def test_check_area_conservation_verified():
    checks = check_area_conservation(make_changeset(area_conservation_verified=True))
    assert checks[0].passed is True


def test_check_area_conservation_mismatch():
    before = WKT
    after = "POLYGON ((0 0, 0 1, 0.5 1, 0.5 0, 0 0))"
    changeset = make_changeset(
        changes=[make_change("split", "P002", before_wkt=before, after_wkt=after, derived=["P001"])],
        area_conservation_verified=False,
    )
    checks = check_area_conservation(changeset)
    assert checks[0].passed is False
    assert checks[0].responsible_stage == "EXECUTE"


def test_check_overlap_detects():
    state = make_planned_state(
        parcels=[
            make_parcel("P001", geometry_wkt=WKT),
            make_parcel("P002", geometry_wkt=WKT),
        ]
    )
    checks = check_overlap(state)
    assert checks[0].passed is False


def test_check_overlap_pass():
    state = make_planned_state(
        parcels=[
            make_parcel("P001", geometry_wkt=WKT),
            make_parcel("P002", geometry_wkt="POLYGON ((2 2, 2 3, 3 3, 3 2, 2 2))"),
        ]
    )
    checks = check_overlap(state)
    assert checks[0].passed is True


def test_check_topology_invalid():
    bowtie = "POLYGON ((0 0, 1 1, 1 0, 0 1, 0 0))"
    state = make_planned_state(parcels=[make_parcel("P001", geometry_wkt=bowtie)])
    invalid = check_topology(state)
    validity = next(c for c in invalid if c.check_id == "topology_validity")
    assert validity.passed is False
    valid = check_topology(make_planned_state(parcels=[make_parcel("P001", geometry_wkt=WKT)]))
    valid_check = next(c for c in valid if c.check_id == "topology_validity")
    assert valid_check.passed is True


def test_check_continuity_fragmented():
    from app.modules.schema.contracts.planned_state_contracts import PlannedZone

    multipolygon_wkt = (
        "MULTIPOLYGON (((0 0, 0 1, 1 1, 1 0, 0 0)), "
        "((2 2, 2 3, 3 3, 3 2, 2 2)))"
    )
    state = make_planned_state()
    state.zones = [PlannedZone(name="Z1", geometry=multipolygon_wkt)]
    checks = check_continuity(state)
    assert checks[0].passed is False
    assert checks[0].responsible_stage == "EXECUTE"


def test_check_accessibility_valid():
    state = make_planned_state()
    state.facilities = [
        PlannedFacility(name="school", facility_type="school", lon=116.0, lat=23.0)
    ]
    checks = check_accessibility(state, None)
    assert checks[0].passed is True
    bad = make_planned_state()
    bad.facilities = [PlannedFacility(name="school", lon=0.0, lat=0.0)]
    checks_bad = check_accessibility(bad, None)
    assert checks_bad[0].passed is False
    assert checks_bad[0].responsible_stage == "SELECT"


def test_check_contract_completeness():
    intent = SpatialPlanningIntent(project_targets=[ProjectTarget(project_id="p1", name="P1")])
    empty = check_contract_completeness(make_planned_state(), make_changeset(), intent)
    assert next(c for c in empty if c.check_id == "parcels_present").passed is False
    populated = make_planned_state(parcels=[make_parcel("P001", "0701", "reclassify")])
    full = check_contract_completeness(populated, make_changeset(), intent)
    assert next(c for c in full if c.check_id == "parcels_present").passed is True
    assert next(c for c in full if c.check_id == "parcel_fields").passed is True


def test_check_classification_missing():
    state = make_planned_state(
        parcels=[
            make_parcel("P001", "", "reclassify"),
            make_parcel("P002", "", "preserve"),
            make_parcel("P003", "0701", "reclassify"),
        ]
    )
    checks = check_classification_missing(state)
    assert checks[0].passed is False
    assert checks[0].affected_parcels == ["P001"]
