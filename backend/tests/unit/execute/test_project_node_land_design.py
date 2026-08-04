"""EXECUTE _execute_project_node: Land Design Worker polygon footprint + ParcelChange accumulation."""

import asyncio
from pathlib import Path

from app.agent.execute.execute_agent import _execute_project_node
from app.agent.execute.execute_state import ExecuteAgentState
from app.modules.schema.contracts.parse_contracts import ProjectTarget, SpatialPlanningIntent
from app.modules.schema.contracts.selection_contracts import LandDesignBrief, SiteSelectionDecision

_EXECUTE_AGENT_PATH = (
    Path(__file__).resolve().parents[3] / "app" / "agent" / "execute" / "execute_agent.py"
)


def _landuse(bsm="P001"):
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"BSM": bsm, "DLBM": "0101", "area_sqm": 10000},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[116.0, 24.8], [116.1, 24.8], [116.1, 24.9], [116.0, 24.9], [116.0, 24.8]]],
            },
        }],
    }


def _state(selected=None, brief=None):
    return ExecuteAgentState(
        session_id="s1",
        tasks_to_run=["project"],
        gis_data={"landuse_current_geojson": _landuse()},
        intent=SpatialPlanningIntent(
            project_targets=[
                ProjectTarget(
                    project_id="p1",
                    name="P1",
                    scale_text="1.5公顷",
                    candidate_bsms=["P001"],
                )
            ]
        ),
        site_selection=SiteSelectionDecision(selected_combination=selected or ["P001"]),
        land_design_briefs=brief or [LandDesignBrief(project_ref="p1", footprint_conditions=["category:project"])],
    )


def _project_layer(result):
    return next(c for c in result["layout_configs"] if c["layerType"] == "planned_project")


def test_project_node_polygon_footprint():
    state = _state()

    result = asyncio.run(_execute_project_node(state))

    layer = _project_layer(result)
    features = layer["data"]["features"]
    assert len(features) == 1
    assert features[0]["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    props = features[0]["properties"]
    assert props["source_bsm"] == "P001"
    assert props["change_action"] == "reclassify"


def test_project_node_accumulates_parcel_changes():
    state = _state()

    asyncio.run(_execute_project_node(state))

    assert len(state.parcel_changes) == 1
    change = state.parcel_changes[0]
    assert change.action in {"reclassify", "merge"}
    assert change.bsm == "P001"
    assert change.derived_from_bsms == ["P001"]


def test_project_node_builds_changeset():
    state = _state()

    asyncio.run(_execute_project_node(state))

    assert state.parcel_changeset is not None
    assert len(state.parcel_changeset.changes) == 1


def test_legacy_loop_deleted():
    source = _EXECUTE_AGENT_PATH.read_text(encoding="utf-8")

    assert "_project_legacy_output" not in source
    assert "for bsm in project.candidate_bsms" not in source
