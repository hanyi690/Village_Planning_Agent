"""EXECUTE _write_l4_node: consumes ParcelChangeSet via planned_state_builder (Wave I Task 6).

The L4 write node must build PlannedState from state.parcel_changeset through
changeset_to_planned_state, keeping the old _layout_configs_to_planned_state
GeoJSON path as fallback when no changeset is present.
"""

import asyncio
from types import SimpleNamespace

from app.agent.execute.execute_agent import _write_l4_node
from app.agent.execute.execute_state import ExecuteAgentState
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
from app.modules.schema.contracts.provenance import Provenance

WKT = "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))"


def _classification(code, source="derived"):
    from app.modules.schema.contracts.classification_ref import ClassificationRef

    return ClassificationRef(
        system="GB/T 21010",
        code=code,
        canonical_name=f"name-{code}",
        source=source,
    )


def _reclassify_change(bsm="P001", after_code="0701"):
    return ParcelChange(
        bsm=bsm,
        action="reclassify",
        derived_from_bsms=[bsm],
        before_classification=_classification("0101", source="preserve"),
        after_classification=_classification(after_code),
        before_geometry_wkt=WKT,
        after_geometry_wkt=WKT,
        new_area_ha=1.2,
    )


def _changeset(changes):
    return ParcelChangeSet(
        changes=changes,
        provenance=Provenance(source="land_design_worker", run_id="r1", module="execute"),
    )


def _patch_kg_deps(monkeypatch):
    calls = {"apply": [], "bump": []}
    kg = SimpleNamespace(graph="fake-kg")

    def fake_apply(kg_arg, planned_state):
        calls["apply"].append(planned_state)

    class FakeManager:
        def get_session_kg(self, _session_id):
            return kg

        def bump_version(self, _session_id):
            calls["bump"].append(1)

    import app.modules.kg.builder.layer4 as layer4
    import app.modules.kg.manager as km

    monkeypatch.setattr(layer4, "apply_planned_state", fake_apply)
    monkeypatch.setattr(km, "get_kg_manager", lambda: FakeManager())
    return calls, kg


def test_l4_uses_changeset_path(monkeypatch):
    calls, kg = _patch_kg_deps(monkeypatch)
    state = ExecuteAgentState(
        session_id="s1",
        validation_result={"passed": True},
        intent=SpatialPlanningIntent(),
        layout_configs=[],
        parcel_changeset=_changeset([_reclassify_change()]),
    )

    result = asyncio.run(_write_l4_node(state))

    assert result == {}
    assert len(calls["apply"]) == 1
    planned_state = calls["apply"][0]
    assert len(planned_state.parcels) == 1
    assert planned_state.parcels[0].bsm == "P001"
    assert planned_state.parcels[0].operation == "reclassify"
    assert calls["bump"] == [1]


def test_l4_fallback_when_no_changeset(monkeypatch):
    calls, kg = _patch_kg_deps(monkeypatch)
    state = ExecuteAgentState(
        session_id="s1",
        validation_result={"passed": True},
        intent=SpatialPlanningIntent(),
        parcel_changeset=None,
        layout_configs=[
            {
                "layerType": "planned_project",
                "data": {
                    "features": [
                        {
                            "properties": {
                                "name": "学校",
                                "facility_type": "school",
                            },
                            "geometry": {"type": "Point", "coordinates": [0.01, 0.02]},
                        }
                    ]
                },
            }
        ],
    )

    result = asyncio.run(_write_l4_node(state))

    assert result == {}
    assert len(calls["apply"]) == 1
    planned_state = calls["apply"][0]
    assert len(planned_state.facilities) == 1
    assert planned_state.facilities[0].name == "学校"
    assert calls["bump"] == [1]


def test_l4_skips_when_validation_not_passed(monkeypatch):
    calls, kg = _patch_kg_deps(monkeypatch)
    state = ExecuteAgentState(
        session_id="s1",
        validation_result={"passed": False},
        parcel_changeset=_changeset([_reclassify_change()]),
    )

    result = asyncio.run(_write_l4_node(state))

    assert result == {}
    assert calls["apply"] == []
    assert calls["bump"] == []


def test_l4_skips_no_session(monkeypatch):
    calls, kg = _patch_kg_deps(monkeypatch)
    state = ExecuteAgentState(
        session_id="",
        validation_result={"passed": True},
        parcel_changeset=_changeset([_reclassify_change()]),
    )

    result = asyncio.run(_write_l4_node(state))

    assert result == {}
    assert calls["apply"] == []
    assert calls["bump"] == []
