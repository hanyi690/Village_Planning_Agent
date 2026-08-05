"""EXECUTE facility worker: decision-driven facility footprint (Wave I Task 5, Wave O worker).

The facility worker must build Polygon footprints from FacilityTarget anchors via
the Land Design Worker (no FacilityPlacer, no KG POI lookup), pass the real
parcel_by_bsm (containing-parcel branch), and return a WorkerResult.
"""

import asyncio
from pathlib import Path

from app.agent.execute.execute_agent import _facility_worker_node
from app.agent.execute.execute_state import ExecuteAgentState
from app.modules.schema.contracts.parse_contracts import FacilityTarget, SpatialPlanningIntent


def _facility_layer(result):
    worker = result["worker_results"][0]
    return next(c for c in worker.layers if c["layerType"] == "facility_point")


def _state(*facilities, tasks=("facility",)):
    return ExecuteAgentState(
        intent=SpatialPlanningIntent(facilities=list(facilities)),
        tasks_to_run=list(tasks),
    )


def test_facility_worker_creates_polygon():
    state = _state(FacilityTarget(type="school", anchor_point=(0.01, 0.01)))

    result = asyncio.run(_facility_worker_node(state))

    layer = _facility_layer(result)
    features = layer["data"]["features"]
    assert len(features) == 1
    props = features[0]["properties"]
    assert props["facility_type"] == "school"
    assert props["change_action"] == "create"
    assert props["status"] == "planned_new"
    assert features[0]["geometry"]["type"] == "Polygon"


def test_facility_worker_accumulates_parcel_changes():
    state = _state(FacilityTarget(type="school", anchor_point=(0.01, 0.01)))

    result = asyncio.run(_facility_worker_node(state))

    changes = result["worker_results"][0].parcel_changes
    assert len(changes) == 1
    change = changes[0]
    assert change.action == "create"
    assert change.bsm == "school_0"
    assert change.derived_from_bsms == []


def test_facility_worker_builds_changeset_via_merge():
    from app.agent.execute.merge import merge_worker_results

    state = _state(FacilityTarget(type="school", anchor_point=(0.01, 0.01)))

    result = asyncio.run(_facility_worker_node(state))

    changeset, layouts, diagnostics = merge_worker_results(
        [result["worker_results"][0]]
    )
    assert changeset is not None
    assert len(changeset.changes) == 1


def test_facility_worker_empty_output():
    state = _state()

    result = asyncio.run(_facility_worker_node(state))

    codes = [item["code"] for item in result["worker_results"][0].unresolved_items]
    assert "facility_output_empty" in codes


def test_facility_worker_no_anchor_skipped():
    state = _state(
        FacilityTarget(type="school", anchor_point=(0.01, 0.01)),
        FacilityTarget(type="clinic"),
    )

    result = asyncio.run(_facility_worker_node(state))

    layer = _facility_layer(result)
    features = layer["data"]["features"]
    assert len(features) == 1
    assert features[0]["properties"]["facility_type"] == "school"
    assert len(result["worker_results"][0].parcel_changes) == 1


def test_facility_worker_all_skipped_empty():
    state = _state(FacilityTarget(type="clinic"))

    result = asyncio.run(_facility_worker_node(state))

    codes = [item["code"] for item in result["worker_results"][0].unresolved_items]
    assert "facility_output_empty" in codes
    assert result["worker_results"][0].parcel_changes == []


def test_facility_worker_uses_containing_parcel():
    from app.modules.schema.contracts.parse_contracts import FacilityTarget

    state = ExecuteAgentState(
        gis_data={
            "landuse_current_geojson": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {"BSM": "P001", "DLBM": "0701", "area_sqm": 12000},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0.0, 0.0], [0.001, 0.0], [0.001, 0.001], [0.0, 0.001], [0.0, 0.0]]],
                    },
                }],
            }
        },
        intent=SpatialPlanningIntent(
            facilities=[FacilityTarget(type="school", anchor_point=(0.0005, 0.0005))]
        ),
        tasks_to_run=["facility"],
    )

    result = asyncio.run(_facility_worker_node(state))

    changes = result["worker_results"][0].parcel_changes
    assert len(changes) == 1
    assert changes[0].action == "reclassify"
    assert changes[0].derived_from_bsms == ["P001"]


def test_facility_worker_no_generate_facilities_import():
    source_path = Path(__file__).resolve().parents[3] / "app" / "agent" / "execute" / "execute_agent.py"
    source = source_path.read_text(encoding="utf-8")
    assert "from app.tools.gis.generate import _generate_facilities" not in source
    assert "_generate_facilities(" not in source
