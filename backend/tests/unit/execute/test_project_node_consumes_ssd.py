"""EXECUTE _execute_project_node: consume SiteSelectionDecision from SELECT.

Covers the SSD primary path, the legacy first-available-candidate fallback,
and the new ExecuteAgentState fields defaulting.
"""

import asyncio

from app.agent.execute.execute_agent import _execute_project_node
from app.agent.execute.execute_state import ExecuteAgentState
from app.modules.schema.contracts.parse_contracts import ProjectTarget, SpatialPlanningIntent
from app.modules.schema.contracts.selection_contracts import LandDesignBrief, SiteSelectionDecision


def _landuse(*bsms):
    features = []
    for bsm in bsms:
        features.append({
            "type": "Feature",
            "properties": {"BSM": bsm},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[116.0, 24.8], [116.1, 24.8], [116.1, 24.9], [116.0, 24.9], [116.0, 24.8]]],
            },
        })
    return {"type": "FeatureCollection", "features": features}


def _project(project_id="p1", candidate_bsms=None):
    return ProjectTarget(
        project_id=project_id,
        name="sample project",
        category="public",
        action="new",
        scale_text="1000 sqm",
        candidate_bsms=list(candidate_bsms or []),
        source_instruction_id="inst-1",
        source_report_key="report-1",
    )


def _project_layer(result):
    return next(c for c in result["layout_configs"] if c["layerType"] == "planned_project")


def test_ssd_path_builds_layer():
    state = ExecuteAgentState(
        gis_data={"landuse_current_geojson": _landuse("P001")},
        intent=SpatialPlanningIntent(project_targets=[_project(candidate_bsms=["UNKNOWN"])]),
        site_selection=SiteSelectionDecision(selected_combination=["P001"]),
        land_design_briefs=[LandDesignBrief(project_ref="p1")],
        tasks_to_run=["project"],
    )

    result = asyncio.run(_execute_project_node(state))

    layer = _project_layer(result)
    features = layer["data"]["features"]
    assert len(features) == 1
    props = features[0]["properties"]
    assert props["source_bsm"] == "P001"
    assert props["project_ref"] == "p1"
    assert props["project_id"] == "p1"
    assert features[0]["geometry"]["type"] == "Point"


def test_legacy_fallback_when_no_ssd():
    state = ExecuteAgentState(
        gis_data={"landuse_current_geojson": _landuse("P001")},
        intent=SpatialPlanningIntent(project_targets=[_project(candidate_bsms=["P001"])]),
        tasks_to_run=["project"],
    )

    result = asyncio.run(_execute_project_node(state))

    layer = _project_layer(result)
    features = layer["data"]["features"]
    assert len(features) == 1
    assert features[0]["properties"]["source_bsm"] == "P001"


def test_ssd_empty_selection_falls_back():
    state = ExecuteAgentState(
        gis_data={"landuse_current_geojson": _landuse("P001")},
        intent=SpatialPlanningIntent(project_targets=[_project(candidate_bsms=["P001"])]),
        site_selection=SiteSelectionDecision(selected_combination=[]),
        tasks_to_run=["project"],
    )

    result = asyncio.run(_execute_project_node(state))

    layer = _project_layer(result)
    features = layer["data"]["features"]
    assert len(features) == 1
    assert features[0]["properties"]["source_bsm"] == "P001"


def test_ssd_unknown_bsm_skipped():
    state = ExecuteAgentState(
        gis_data={"landuse_current_geojson": _landuse("P001")},
        intent=SpatialPlanningIntent(project_targets=[_project(candidate_bsms=["P001"])]),
        site_selection=SiteSelectionDecision(selected_combination=["UNKNOWN"]),
        tasks_to_run=["project"],
    )

    result = asyncio.run(_execute_project_node(state))

    layer = _project_layer(result)
    features = layer["data"]["features"]
    assert len(features) == 1
    assert features[0]["properties"]["source_bsm"] == "P001"


def test_state_fields_default():
    state = ExecuteAgentState()

    assert state.site_selection is None
    assert state.land_design_briefs == []
