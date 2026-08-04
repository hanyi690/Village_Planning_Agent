"""EXECUTE _execute_facility_node: decision-driven facility footprint (Wave I Task 5).

The facility node must build Polygon footprints from FacilityTarget anchors via
the Land Design Worker (no FacilityPlacer, no KG POI lookup) and accumulate
ParcelChange entries onto state.
"""

import asyncio
from pathlib import Path

from app.agent.execute.execute_agent import _execute_facility_node
from app.agent.execute.execute_state import ExecuteAgentState
from app.modules.schema.contracts.parse_contracts import FacilityTarget, SpatialPlanningIntent


def _facility_layer(result):
    return next(c for c in result["layout_configs"] if c["layerType"] == "facility_point")


def _state(*facilities, tasks=("facility",)):
    return ExecuteAgentState(
        intent=SpatialPlanningIntent(facilities=list(facilities)),
        tasks_to_run=list(tasks),
    )


def test_facility_node_creates_polygon():
    state = _state(FacilityTarget(type="school", anchor_point=(0.01, 0.01)))

    result = asyncio.run(_execute_facility_node(state))

    layer = _facility_layer(result)
    features = layer["data"]["features"]
    assert len(features) == 1
    props = features[0]["properties"]
    assert props["facility_type"] == "school"
    assert props["change_action"] == "create"
    assert props["status"] == "planned_new"
    assert features[0]["geometry"]["type"] == "Polygon"


def test_facility_node_accumulates_parcel_changes():
    state = _state(FacilityTarget(type="school", anchor_point=(0.01, 0.01)))

    asyncio.run(_execute_facility_node(state))

    assert len(state.parcel_changes) == 1
    change = state.parcel_changes[0]
    assert change.action == "create"
    assert change.bsm == "school_0"
    assert change.derived_from_bsms == []


def test_facility_node_builds_changeset():
    state = _state(FacilityTarget(type="school", anchor_point=(0.01, 0.01)))

    asyncio.run(_execute_facility_node(state))

    assert state.parcel_changeset is not None
    assert len(state.parcel_changeset.changes) == 1


def test_facility_node_empty_output():
    state = _state()

    result = asyncio.run(_execute_facility_node(state))

    codes = [issue["code"] for issue in result.get("execution_errors", [])]
    assert "facility_output_empty" in codes


def test_facility_node_no_anchor_skipped():
    state = _state(
        FacilityTarget(type="school", anchor_point=(0.01, 0.01)),
        FacilityTarget(type="clinic"),
    )

    result = asyncio.run(_execute_facility_node(state))

    layer = _facility_layer(result)
    features = layer["data"]["features"]
    assert len(features) == 1
    assert features[0]["properties"]["facility_type"] == "school"
    assert len(state.parcel_changes) == 1


def test_facility_node_all_skipped_empty():
    state = _state(FacilityTarget(type="clinic"))

    result = asyncio.run(_execute_facility_node(state))

    codes = [issue["code"] for issue in result.get("execution_errors", [])]
    assert "facility_output_empty" in codes
    assert state.parcel_changes == []


def test_facility_node_no_generate_facilities_import():
    source_path = Path(__file__).resolve().parents[3] / "app" / "agent" / "execute" / "execute_agent.py"
    source = source_path.read_text(encoding="utf-8")
    assert "from app.tools.gis.generate import _generate_facilities" not in source
    assert "_generate_facilities(" not in source
