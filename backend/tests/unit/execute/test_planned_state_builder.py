"""PlannedState builder: deterministic ParcelChangeSet -> PlannedState (Wave I Task 2)."""

import pytest

from app.agent.execute.planned_state_builder import (
    _change_to_planned_parcel,
    changeset_to_planned_state,
)
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.modules.schema.contracts.parse_contracts import (
    AxisTarget,
    FacilityTarget,
    RoadTarget,
    SpatialPlanningIntent,
)
from app.modules.schema.contracts.provenance import Provenance

WKT = "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))"


def make_change(
    action,
    bsm,
    after_code="",
    derived=None,
    wkt=WKT,
    area=0.0,
    before_code="",
    before_wkt="",
):
    after_classification = None
    if after_code:
        after_classification = _classification(after_code)
    before_classification = None
    if before_code:
        before_classification = _classification(before_code, source="preserve")
    return ParcelChange(
        bsm=bsm,
        action=action,
        derived_from_bsms=list(derived or []),
        before_classification=before_classification,
        after_classification=after_classification,
        before_geometry_wkt=before_wkt,
        after_geometry_wkt=wkt,
        new_area_ha=area,
    )


def _classification(code, source="derived"):
    from app.modules.schema.contracts.classification_ref import ClassificationRef

    return ClassificationRef(
        system="GB/T 21010",
        code=code,
        canonical_name=f"name-{code}",
        source=source,
    )


def make_provenance():
    return Provenance(source="land_design_worker", run_id="r1", module="execute")


def test_reclassify_change_to_planned_parcel():
    change = make_change("reclassify", "P001", after_code="0701", derived=["P001"], area=1.2)
    parcel = _change_to_planned_parcel(change)
    assert parcel.operation == "reclassify"
    assert parcel.planning_land_use == "0701"
    assert parcel.zone_type == "0701"
    assert parcel.derived_from_bsms == ["P001"]
    assert parcel.geometry == WKT
    assert parcel.decided_by == "rule"
    assert parcel.area_ha == 1.2
    assert parcel.area_change_ha == 1.2


def test_area_change_ha_from_before_geometry():
    change = make_change(
        "split",
        "P001",
        after_code="0701",
        before_wkt="POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0))",
        area=0.0002,
    )
    parcel = _change_to_planned_parcel(change)
    assert parcel.area_change_ha == pytest.approx(-0.0002)


def test_split_merge_changes_operations():
    split = _change_to_planned_parcel(make_change("split", "P002", after_code="0701"))
    merge = _change_to_planned_parcel(make_change("merge", "M001", after_code="0701"))
    assert split.operation == "split"
    assert merge.operation == "merge"


def test_preserve_action():
    change = make_change("preserve", "P003", before_code="0101", derived=["P003"])
    parcel = _change_to_planned_parcel(change)
    assert parcel.operation == "preserve"
    assert parcel.planning_land_use == "0101"
    assert parcel.derived_from_bsms == ["P003"]


def test_changeset_to_planned_state_parcels():
    changes = [
        make_change("reclassify", "P001", after_code="0701", derived=["P001"]),
        make_change("reclassify", "P002", after_code="0702", derived=["P002"]),
    ]
    state = changeset_to_planned_state(
        ParcelChangeSet(changes=changes, provenance=make_provenance())
    )
    assert state.version == "v1"
    assert state.source == "parcel_change_set"
    assert len(state.parcels) == 2
    assert state.parcels[0].bsm == "P001"
    assert state.parcels[1].planning_land_use == "0702"
    assert state.provenance is not None
    assert state.provenance.source == "land_design_worker"
    assert state.zones == []
    assert state.roads == []
    assert state.axes == []
    assert state.facilities == []


def test_changeset_to_planned_state_with_intent():
    intent = SpatialPlanningIntent(
        road_targets=[RoadTarget(road_level="主干道", width_m=8.0, connects=["村北", "村南"])],
        development_axes=[
            AxisTarget(reference_feature="河流", direction="north-south", label="南北发展轴")
        ],
        facilities=[
            FacilityTarget(type="school", anchor_point=(0.01, 0.02), service_radius=500)
        ],
    )
    state = changeset_to_planned_state(
        ParcelChangeSet(changes=[make_change("create", "P009", after_code="0801")]),
        intent=intent,
    )
    assert len(state.roads) == 1
    road = state.roads[0]
    assert road.name == "主干道"
    assert road.road_level == "主干道"
    assert road.width_m == 8.0
    assert len(state.axes) == 1
    axis = state.axes[0]
    assert axis.name == "南北发展轴"
    assert axis.reference_feature == "河流"
    assert axis.direction == "north-south"
    assert len(state.facilities) == 1
    facility = state.facilities[0]
    assert facility.name == "school"
    assert facility.facility_type == "school"
    assert facility.lon == 0.01
    assert facility.lat == 0.02
    assert facility.service_radius == 500


def test_changeset_to_planned_state_no_intent():
    state = changeset_to_planned_state(ParcelChangeSet(changes=[]))
    assert state.roads == []
    assert state.axes == []
    assert state.facilities == []


def test_empty_changeset():
    state = changeset_to_planned_state(ParcelChangeSet(changes=[]))
    assert len(state.parcels) == 0
    assert state.source == "parcel_change_set"
