from app.infrastructure.context.planning_context import PlanningContext
from app.infrastructure.context.planning_context_factory import (
    _build_context_demands,
    _build_context_networks,
)


def test_input_texts_uses_session_sources_and_deduplicates_by_source() -> None:
    context = PlanningContext(
        workspace=object(),
        input_documents=[
            {
                "source": "village_data",
                "type": "text",
                "content": "会话摘要",
            },
            {
                "source": "upload",
                "type": "text",
                "content": "现状甲",
            },
            {
                "source": "upload",
                "type": "text",
                "content": "现状乙",
            },
        ],
    )

    texts = context.input_texts()

    assert texts["village_data"] == "会话摘要"
    assert texts["upload"] == "现状甲\n\n现状乙"


def test_input_texts_deduplicates_identical_session_uploads() -> None:
    context = PlanningContext(
        workspace=object(),
        input_documents=[
            {
                "source": "upload",
                "type": "text",
                "content": "同一份现状",
            },
            {
                "source": "upload",
                "type": "text",
                "content": "同一份现状",
            },
        ],
    )

    assert context.input_texts()["upload"] == "同一份现状"


def test_context_network_snapshot_uses_canonical_current_road_ref() -> None:
    class Workspace:
        lines = {
            "roads_current": [
                {
                    "geometry": {"type": "LineString", "coordinates": [[0, 0], [100, 0]]},
                    "crs": "EPSG:3857",
                }
            ]
        }

    networks = _build_context_networks(Workspace())

    assert sorted(networks) == ["network:road:current"]
    snapshot = networks["network:road:current"]
    assert snapshot.fingerprint
    assert snapshot.route(
        {"geometry": "POINT (0 0)", "crs": "EPSG:3857"},
        {"geometry": "POINT (100 0)", "crs": "EPSG:3857"},
    ).reachable is True


def test_context_demand_snapshot_requires_explicit_value_and_unit() -> None:
    class Workspace:
        points = {
            "demand_points": [
                {
                    "geometry": {"type": "Point", "coordinates": [100, 0]},
                    "properties": {
                        "demand_id": "demand-1",
                        "demand_value": 50,
                        "demand_unit": "person",
                        "facility_types": ["clinic"],
                    },
                },
                {
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "properties": {"demand_id": "missing-value"},
                },
            ],
            "annotations_current": [
                {
                    "geometry": {"type": "Point", "coordinates": [50, 0]},
                    "properties": {"text": "人口 100 人"},
                }
            ],
        }

    demands = _build_context_demands(Workspace())

    assert sorted(demands) == ["demand:demand_points"]
    snapshot = demands["demand:demand_points"]
    assert [point.demand_id for point in snapshot.points] == ["demand-1"]
    assert snapshot.points[0].demand_value == 50
    assert snapshot.points[0].demand_unit == "person"
