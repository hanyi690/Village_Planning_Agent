"""Land Design Worker: deterministic parcel change production (Wave I Task 1)."""

from types import SimpleNamespace

from app.agent.execute.land_design_worker import (
    build_parcel_change_set,
    design_all,
    design_facility_parcel,
    design_project_parcel,
    design_zone_parcel,
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


def make_parcel_by_bsm():
    return {
        "P001": SimpleNamespace(
            bsm="P001", geometry=_POLYGON, dlbm="0701", area_sqm=12000.0
        ),
        "P002": SimpleNamespace(
            bsm="P002", geometry=_POLYGON, dlbm="0701", area_sqm=12000.0
        ),
    }


def make_intent():
    return SpatialPlanningIntent(
        project_targets=[
            ProjectTarget(
                project_id="p1",
                name="P1",
                scale_text="1.5公顷",
                candidate_bsms=["P001"],
            )
        ],
        zone_targets=[ZoneTarget(land_use="生态保护区", candidate_bsms=["P001"])],
        facilities=[FacilityTarget(type="school", anchor_point=(0.01, 0.01))],
    )


def make_brief():
    return LandDesignBrief(
        project_ref="p1",
        footprint_conditions=["category:project", "scale:1.5公顷"],
        area_tolerance_pct=5.0,
    )


def make_ssd():
    return SiteSelectionDecision(selected_combination=["P001"])


def test_design_project_parcel_reclassify():
    change = design_project_parcel(
        make_intent().project_targets[0], make_brief(), "P001", make_parcel_by_bsm()
    )
    assert change is not None
    assert change.action == "reclassify"
    assert change.bsm == "P001"
    assert change.derived_from_bsms == ["P001"]
    assert change.after_geometry_wkt
    assert change.after_geometry_wkt.startswith("POLYGON")
    assert change.after_classification is not None
    assert change.after_classification.code == "0701"


def test_design_project_parcel_merge():
    project = ProjectTarget(
        project_id="p2", name="P2", candidate_bsms=["P001", "P002"]
    )
    change = design_project_parcel(project, make_brief(), "P001", make_parcel_by_bsm())
    assert change is not None
    assert change.action == "merge"
    assert set(change.derived_from_bsms) == {"P001", "P002"}
    assert change.bsm.startswith("MERGED")
    assert change.after_classification is not None


def test_design_project_parcel_missing_parcel_returns_none():
    change = design_project_parcel(
        make_intent().project_targets[0], make_brief(), "UNKNOWN", make_parcel_by_bsm()
    )
    assert change is None


def test_design_zone_parcel_reclassify():
    zone_target = make_intent().zone_targets[0]
    changes = design_zone_parcel(zone_target, make_parcel_by_bsm())
    assert len(changes) == 1
    change = changes[0]
    assert change.action == "reclassify"
    assert change.bsm == "P001"
    assert change.after_classification is not None
    assert change.after_classification.code == "生态保护区"


def test_design_facility_parcel_create():
    facility = make_intent().facilities[0]
    change = design_facility_parcel(facility, make_parcel_by_bsm(), None)
    assert change is not None
    assert change.action == "create"
    assert change.after_geometry_wkt
    assert change.new_area_ha > 0
    assert change.derived_from_bsms == []


def test_design_facility_parcel_no_anchor_none():
    facility = FacilityTarget(type="school", location_hint="")
    change = design_facility_parcel(facility, make_parcel_by_bsm(), None)
    assert change is None


def test_build_parcel_change_set():
    changes = [
        design_project_parcel(
            make_intent().project_targets[0], make_brief(), "P001", make_parcel_by_bsm()
        ),
        design_facility_parcel(make_intent().facilities[0], make_parcel_by_bsm(), None),
    ]
    result = build_parcel_change_set(
        changes, area_conservation_verified=True, geometry_validity_verified=False
    )
    assert len(result.changes) == 2
    assert result.area_conservation_verified is True
    assert result.geometry_validity_verified is False


def test_design_all_orchestrator():
    result = design_all(
        make_intent(), make_ssd(), [make_brief()], make_parcel_by_bsm()
    )
    assert len(result.changes) >= 3
    assert result.area_conservation_verified is False
    assert result.geometry_validity_verified is False


def test_design_all_no_selection():
    result = design_all(
        make_intent(),
        SiteSelectionDecision(selected_combination=[]),
        [make_brief()],
        make_parcel_by_bsm(),
    )
    assert len(result.changes) == 2
    assert sum(1 for c in result.changes if c.action == "create") == 1
    assert sum(1 for c in result.changes if c.action == "reclassify") == 1
