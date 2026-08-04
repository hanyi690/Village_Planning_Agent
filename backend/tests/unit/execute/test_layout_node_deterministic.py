"""EXECUTE _execute_layout_node: deterministic zone reclassification (no MIP).

Covers the deterministic reclassify path (function_zone layer + ParcelChange
accumulation), the "deterministic" summary mode, the absence of any MIP
import/solve in the layout node, the missing-zone-targets error path, and the
custom planning-zone path via CustomZoningGenerator (vocabulary-driven, no MIP).
"""

import asyncio
from pathlib import Path

from app.agent.execute.execute_agent import _execute_layout_node
from app.agent.execute.execute_state import ExecuteAgentState
from app.modules.schema.contracts.custom_zone_contracts import (
    CustomZoneTarget,
    Vocabulary,
    VocabularyCategory,
)
from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent, ZoneTarget
from app.modules.schema.encodings.dicts.vocabularies.loader import register_vocabulary

_EXECUTE_AGENT_PATH = (
    Path(__file__).resolve().parents[3] / "app" / "agent" / "execute" / "execute_agent.py"
)


def _landuse(*bsms):
    features = []
    for bsm in bsms:
        features.append({
            "type": "Feature",
            "properties": {"BSM": bsm, "DLBM": "0101", "area_sqm": 10000},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[116.0, 24.8], [116.1, 24.8], [116.1, 24.9], [116.0, 24.9], [116.0, 24.8]]
                ],
            },
        })
    return {"type": "FeatureCollection", "features": features}


def _zone(bsms=None, **kw):
    defaults = {
        "land_use": "生态保护区",
        "planning_zone": "生态保护区",
        "candidate_bsms": list(bsms or []),
    }
    defaults.update(kw)
    return ZoneTarget(**defaults)


def _state(intent=None, landuse=None):
    return ExecuteAgentState(
        session_id="s1",
        tasks_to_run=["layout"],
        gis_data={"landuse_current_geojson": landuse or _landuse("P001")},
        intent=intent or SpatialPlanningIntent(),
    )


def test_layout_node_reclassifies_zone_targets():
    state = _state(
        intent=SpatialPlanningIntent(zone_targets=[_zone(bsms=["P001"])])
    )

    result = asyncio.run(_execute_layout_node(state))

    func = next(c for c in result["layout_configs"] if c["layerType"] == "function_zone")
    features = func["data"]["features"]
    assert len(features) == 1
    assert features[0]["geometry"]["type"] == "Polygon"
    props = features[0]["properties"]
    assert props["bsm"] == "P001"
    assert props["planning_land_use"] == "生态保护区"
    assert props["zone_type"] == "生态保护区"
    assert props["action"] == "reclassify"
    assert len(state.parcel_changes) == 1
    assert state.parcel_changes[0].action == "reclassify"
    assert state.parcel_changes[0].bsm == "P001"
    assert state.parcel_changeset is not None
    assert len(state.parcel_changeset.changes) == 1


def test_layout_node_mode_deterministic():
    state = _state(
        intent=SpatialPlanningIntent(zone_targets=[_zone(bsms=["P001"])])
    )

    result = asyncio.run(_execute_layout_node(state))

    summary = result["allocation_summary"]
    assert summary["mode"] == "deterministic"
    assert summary["zone_target_count"] == 1
    assert summary["allocated_count"] == 1


def test_layout_node_no_mip_import():
    source = _EXECUTE_AGENT_PATH.read_text(encoding="utf-8")

    assert "MIPZoneAllocator" not in source
    assert "allocator.solve" not in source
    assert "_spatial_constraint_to_mip" not in source
    assert "_generate_function_zones" not in source


def test_layout_node_missing_zone_targets():
    state = _state(intent=SpatialPlanningIntent())

    result = asyncio.run(_execute_layout_node(state))

    errors = result.get("execution_errors", [])
    assert any(e.get("code") == "missing_zone_targets" for e in errors)


def test_layout_node_custom_zone_targets():
    register_vocabulary(
        "sess_layout_vocab",
        Vocabulary(
            name="sess_layout_vocab",
            categories=[
                VocabularyCategory(
                    code="FZ01",
                    name_zh="生态保护区",
                    color="#2d6a4f",
                    typing_rules=[{"kind": "dlbm_in", "value": ["0301", "0302"]}],
                )
            ],
        ),
    )
    state = _state(
        intent=SpatialPlanningIntent(
            custom_zone_targets=[
                CustomZoneTarget(
                    vocabulary_name="sess_layout_vocab",
                    category_code="FZ01",
                    target_bsms=["P001"],
                )
            ]
        )
    )

    result = asyncio.run(_execute_layout_node(state))

    layers = result.get("layout_configs", [])
    custom = [c for c in layers if c.get("layerType") == "custom_planning_zone"]
    assert custom, f"expected custom_planning_zone layer, got {[c.get('layerType') for c in layers]}"
    assert len(custom[0]["data"]["features"]) >= 1


def test_layout_node_empty_intent():
    state = _state(intent=SpatialPlanningIntent())

    result = asyncio.run(_execute_layout_node(state))

    errors = result.get("execution_errors", [])
    assert any(e.get("code") == "missing_zone_targets" for e in errors)
