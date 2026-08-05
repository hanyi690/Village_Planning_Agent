"""P7 单测：EXECUTE zone worker 接线 CustomZoningGenerator → custom_functional_zone 层。"""

import asyncio

from app.agent.execute.execute_agent import _zone_worker_node
from app.agent.execute.execute_state import ExecuteAgentState
from app.modules.schema.contracts.custom_zone_contracts import (
    CustomZoneTarget,
    Vocabulary,
    VocabularyCategory,
)
from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
from app.modules.schema.encodings.dicts.vocabularies.loader import register_vocabulary

_LANDUSE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"BSM": "P1", "DLBM": "0301"},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        },
        {
            "type": "Feature",
            "properties": {"BSM": "P2", "DLBM": "0101"},
            "geometry": {"type": "Polygon", "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]]},
        },
    ],
}


def test_execute_layout_adds_custom_functional_zone_layer():
    register_vocabulary(
        "sess_exec_vocab",
        Vocabulary(
            name="sess_exec_vocab",
            categories=[
                VocabularyCategory(
                    code="FZ01", name_zh="生态保护区", color="#2d6a4f",
                    typing_rules=[{"kind": "dlbm_in", "value": ["0301", "0302"]}],
                )
            ],
        ),
    )
    intent = SpatialPlanningIntent(
        custom_zone_targets=[
            CustomZoneTarget(vocabulary_name="sess_exec_vocab", category_code="FZ01", target_bsms=[])
        ]
    )
    state = ExecuteAgentState(
        session_id="sess-exec",
        village_name="金田村",
        gis_data={"landuse_current_geojson": _LANDUSE},
        intent=intent,
    )
    result = asyncio.run(_zone_worker_node(state))
    layers = result["worker_results"][0].layers
    custom = [c for c in layers if c.get("layerType") == "custom_planning_zone"]
    assert custom, f"expected custom_planning_zone layer, got {[c.get('layerType') for c in layers]}"
    features = custom[0]["data"]["features"]
    generated = [f for f in features if f["properties"].get("status") == "generated"]
    assert len(generated) == 1
    props = generated[0]["properties"]
    assert props["category_code"] == "FZ01"
    assert props["evidence_bsms"] == ["P1"]  # 规则选择 0301 地块
    assert props["parcel_ids"] == ["P1"]
    assert props["color"] == "#2d6a4f"
    pending = [f for f in features if f["properties"].get("status") == "pending"]
    assert len(pending) == 1
    assert pending[0]["properties"]["parcel_ids"] == ["P2"]
