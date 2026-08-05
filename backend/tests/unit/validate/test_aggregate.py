"""VALIDATE aggregate: deterministic orchestration of the 8 checks (Wave J Task 2)."""

from types import SimpleNamespace

from app.agent.validate.aggregate import validate_aggregate
from app.modules.schema.contracts.parcel_change_contracts import ParcelChangeSet
from app.modules.schema.contracts.parse_contracts import ProjectTarget, SpatialPlanningIntent
from app.modules.schema.contracts.planned_state_contracts import PlannedParcel, PlannedState
from app.modules.schema.contracts.validation_report_contracts import ValidationReport

WKT = "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))"
LAYOUT_A = [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]
LAYOUT_B = [[1.0, 0.0], [1.0, 1.0], [2.0, 1.0], [2.0, 0.0], [1.0, 0.0]]


def make_planned_state(parcels=None):
    return PlannedState(parcels=list(parcels or []))


def make_parcel(bsm, planning_land_use="", operation="preserve", geometry_wkt=WKT):
    return PlannedParcel(
        bsm=bsm,
        planning_land_use=planning_land_use,
        operation=operation,
        geometry=geometry_wkt,
    )


def make_changeset(changes=None, area_conservation_verified=True, geometry_validity_verified=True):
    return ParcelChangeSet(
        changes=list(changes or []),
        area_conservation_verified=area_conservation_verified,
        geometry_validity_verified=geometry_validity_verified,
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


def make_intent():
    return SpatialPlanningIntent(
        project_targets=[ProjectTarget(project_id="p1", name="P1")],
        zone_targets=[],
    )


class FakeConstraintIndex:
    def __init__(self, overlaps):
        self._overlaps = overlaps

    def geometry_in_constraint(self, geometry):
        return self._overlaps


def _clean_inputs():
    state = make_planned_state(parcels=[make_parcel("P001", "0701", "reclassify")])
    changeset = make_changeset()
    layouts = make_layout_configs(
        "parcel",
        [polygon_feature(LAYOUT_A, "Z1"), polygon_feature(LAYOUT_B, "Z2")],
    )
    return state, changeset, layouts, make_intent()


def test_aggregate_all_pass():
    state, changeset, layouts, intent = _clean_inputs()
    result = validate_aggregate(state, changeset, layouts, intent, FakeConstraintIndex([]))
    assert isinstance(result, ValidationReport)
    assert result.overall_passed is True
    assert len(result.checks) >= 8
    assert result.issues_by_stage == {}


def test_aggregate_classification_failure():
    state = make_planned_state(parcels=[make_parcel("P001", "", "reclassify")])
    result = validate_aggregate(state, make_changeset(), [], make_intent(), None)
    assert result.overall_passed is False
    assert "EXECUTE" in result.issues_by_stage
    assert len(result.issues_by_stage["EXECUTE"]) == 1
    assert result.issues_by_stage["EXECUTE"][0].code == "classification_missing"


def test_aggregate_hard_constraint_failure():
    state = make_planned_state(parcels=[make_parcel("P001", "0701", "reclassify")])
    idx = FakeConstraintIndex([SimpleNamespace(constraint_type="farmland_protection")])
    result = validate_aggregate(state, make_changeset(), [], make_intent(), idx)
    assert result.overall_passed is False
    assert "SELECT" in result.issues_by_stage
    assert any(i.code == "hard_constraints" for i in result.issues_by_stage["SELECT"])


def test_aggregate_issues_by_stage_grouping():
    state = make_planned_state(
        parcels=[
            make_parcel("P001", "", "reclassify"),
            make_parcel("P002", "0701", "reclassify"),
        ]
    )
    idx = FakeConstraintIndex([SimpleNamespace(constraint_type="ecological_redline")])
    result = validate_aggregate(state, make_changeset(), [], make_intent(), idx)
    assert "SELECT" in result.issues_by_stage
    assert "EXECUTE" in result.issues_by_stage
    assert any(i.code == "hard_constraints" for i in result.issues_by_stage["SELECT"])
    assert any(i.code == "classification_missing" for i in result.issues_by_stage["EXECUTE"])


def test_aggregate_provenance():
    state, changeset, layouts, intent = _clean_inputs()
    result = validate_aggregate(state, changeset, layouts, intent, None, run_id="run-abc")
    assert result.provenance is not None
    assert result.provenance.source == "validate_aggregate"
    assert result.provenance.run_id == "run-abc"


def test_aggregate_none_inputs():
    result = validate_aggregate(None, None, None, None, None)
    assert isinstance(result, ValidationReport)
    assert isinstance(result.overall_passed, bool)
    assert result.checks


def test_aggregate_deterministic():
    state, changeset, layouts, intent = _clean_inputs()
    idx = FakeConstraintIndex([SimpleNamespace(constraint_type="hazard_control_line")])
    a = validate_aggregate(state, changeset, layouts, intent, idx)
    b = validate_aggregate(state, changeset, layouts, intent, idx)
    assert a.overall_passed == b.overall_passed
    assert a.issues_by_stage == b.issues_by_stage


def test_aggregate_generates_adjustments_for_failures():
    state = make_planned_state(parcels=[make_parcel("P001", "", "reclassify")])
    result = validate_aggregate(state, make_changeset(), [], make_intent(), None)
    assert result.adjustments
    for adj in result.adjustments:
        assert adj.constraint_id
        assert adj.adjustment_type == "relax"
        assert adj.source_check == adj.constraint_id
        assert adj.reason
    assert {a.constraint_id for a in result.adjustments} == {"classification_missing"}


def test_aggregate_all_pass_no_adjustments():
    state, changeset, layouts, intent = _clean_inputs()
    result = validate_aggregate(state, changeset, layouts, intent, FakeConstraintIndex([]))
    assert result.overall_passed is True
    assert result.adjustments == []
