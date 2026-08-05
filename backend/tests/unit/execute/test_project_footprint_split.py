"""Land Design Worker: real project footprint generation (split/setback/traceability)."""

from types import SimpleNamespace

from app.agent.execute.land_design_worker import (
    design_all,
    design_facility_parcel,
    design_project_footprint,
)
from app.modules.schema.contracts.parse_contracts import (
    FacilityTarget,
    ProjectTarget,
    SpatialPlanningIntent,
    ZoneTarget,
)
from app.modules.schema.contracts.selection_contracts import (
    LandDesignBrief,
    SiteSelectionDecision,
)

_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.001, 0.0], [0.001, 0.001], [0.0, 0.001], [0.0, 0.0]]],
}

# ~10 ha under the subdivision convention (area / 10000 -> ha): 316x316 = 99856.
_BIG_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [316.0, 0.0], [316.0, 316.0], [0.0, 316.0], [0.0, 0.0]]],
}


def make_big_parcel_by_bsm():
    return {
        "P001": SimpleNamespace(
            bsm="P001", geometry=_BIG_POLYGON, dlbm="0701", area_sqm=99856.0
        ),
    }


def make_brief(**kwargs):
    base = dict(
        project_ref="p1",
        footprint_conditions=["code:0701"],
        area_tolerance_pct=5.0,
    )
    base.update(kwargs)
    return LandDesignBrief(**base)


def test_split_large_parcel_produces_footprint_and_remainder():
    project = ProjectTarget(project_id="p1", name="P1", area_ha=5.0, candidate_bsms=["P001"])
    changes = design_project_footprint(
        project, make_brief(), "P001", make_big_parcel_by_bsm()
    )
    assert len(changes) == 2
    creates = [c for c in changes if c.action == "create"]
    preserves = [c for c in changes if c.action == "preserve"]
    assert len(creates) == 1
    assert len(preserves) == 1
    fp = creates[0]
    assert fp.bsm == "p1_FP"
    assert fp.project_ref == "p1"
    assert fp.intervention_id == "p1"
    assert fp.derived_from_bsms == ["P001"]
    assert fp.after_classification is not None
    assert fp.after_geometry_wkt
    assert fp.before_geometry_wkt
    assert abs(fp.new_area_ha - 5.0) / 5.0 <= 0.05
    rem = preserves[0]
    assert rem.bsm.startswith("p1_REM")
    assert rem.derived_from_bsms == ["P001"]
    assert rem.new_area_ha > 0


def test_setback_applied():
    project = ProjectTarget(project_id="p1", name="P1", area_ha=5.0, candidate_bsms=["P001"])
    brief = make_brief(setback_requirements=["退让5米"])
    changes = design_project_footprint(project, brief, "P001", make_big_parcel_by_bsm())
    creates = [c for c in changes if c.action == "create"]
    assert len(creates) == 1
    fp = creates[0]
    raw_area_ha = 99856.0 / 10000.0
    assert fp.new_area_ha < raw_area_ha


def test_below_target_still_reclassifies():
    project = ProjectTarget(project_id="p1", name="P1", scale_text="1.5公顷", candidate_bsms=["P001"])
    parcel_by_bsm = {
        "P001": SimpleNamespace(bsm="P001", geometry=_POLYGON, dlbm="0701", area_sqm=12000.0),
    }
    changes = design_project_footprint(project, make_brief(), "P001", parcel_by_bsm)
    assert len(changes) == 1
    assert changes[0].action == "reclassify"
    assert changes[0].bsm == "P001"
    assert changes[0].project_ref == "p1"
    assert changes[0].intervention_id == "p1"


def test_facility_uses_containing_parcel():
    parcel_by_bsm = {
        "P001": SimpleNamespace(bsm="P001", geometry=_POLYGON, dlbm="0701", area_sqm=12000.0),
    }
    inside = FacilityTarget(type="school", anchor_point=(0.0005, 0.0005), source_project_id="proj-x")
    change = design_facility_parcel(inside, parcel_by_bsm, None)
    assert change is not None
    assert change.action == "reclassify"
    assert change.derived_from_bsms == ["P001"]
    assert change.project_ref == "facility:school"
    assert change.intervention_id == "proj-x"

    outside = FacilityTarget(type="school", anchor_point=(0.01, 0.01))
    change2 = design_facility_parcel(outside, parcel_by_bsm, None)
    assert change2 is not None
    assert change2.action == "create"
    assert change2.derived_from_bsms == []


def test_traceability_fields():
    intent = SpatialPlanningIntent(
        project_targets=[
            ProjectTarget(
                project_id="p1", name="P1", scale_text="1.5公顷", candidate_bsms=["P001"]
            )
        ],
        zone_targets=[ZoneTarget(land_use="生态保护区", candidate_bsms=["P001"])],
        facilities=[FacilityTarget(type="school", anchor_point=(0.01, 0.01))],
    )
    ssd = SiteSelectionDecision(selected_combination=["P001"])
    brief = LandDesignBrief(
        project_ref="p1",
        footprint_conditions=["category:project", "scale:1.5公顷"],
        area_tolerance_pct=5.0,
    )
    parcel_by_bsm = {
        "P001": SimpleNamespace(bsm="P001", geometry=_POLYGON, dlbm="0701", area_sqm=12000.0),
    }
    result = design_all(intent, ssd, [brief], parcel_by_bsm)
    project_changes = [c for c in result.changes if c.project_ref == "p1"]
    assert project_changes
    for c in project_changes:
        assert c.project_ref == "p1"
        assert c.intervention_id == "p1"
