"""EXECUTE _validate_node: consume the VALIDATE aggregate subgraph (Wave J Task 5).

Covers the happy path (typed ValidationReport stored on state), the
classification-missing failure, the no-layout and execution-error short
circuits, the removal of the legacy LayoutValidator import, and the new
validation_report state field default.
"""

import asyncio
from pathlib import Path

from app.agent.execute.execute_agent import _validate_node
from app.agent.execute.execute_state import ExecuteAgentState
from app.modules.schema.contracts.classification_ref import ClassificationRef
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent

_EXECUTE_AGENT_PATH = (
    Path(__file__).resolve().parents[3] / "app" / "agent" / "execute" / "execute_agent.py"
)

WKT = "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))"
LAYOUT_A = [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]


def _layer(layer_type="function_zone", features=None):
    return {
        "layerType": layer_type,
        "data": {"type": "FeatureCollection", "features": list(features or [])},
    }


def _polygon_feature(coords, name=""):
    return {
        "type": "Feature",
        "properties": {"name": name},
        "geometry": {"type": "Polygon", "coordinates": [coords]},
    }


def _make_changeset(changes=None, area_conservation_verified=True):
    return ParcelChangeSet(
        changes=list(changes or []),
        area_conservation_verified=area_conservation_verified,
        geometry_validity_verified=True,
    )


def _classified_change(bsm="P001", code="0701"):
    return ParcelChange(
        bsm=bsm,
        action="reclassify",
        after_classification=ClassificationRef(
            system="ghytbm", code=code, canonical_name="林地", source="derived"
        ),
        after_geometry_wkt=WKT,
        new_area_ha=1.0,
    )


def _state(**overrides):
    defaults = dict(
        session_id="s1",
        validation_result={},
        layout_configs=[_layer("function_zone", [_polygon_feature(LAYOUT_A, "Z1")])],
        parcel_changeset=_make_changeset(changes=[_classified_change()]),
        intent=SpatialPlanningIntent(),
        gis_bundle=None,
    )
    defaults.update(overrides)
    return ExecuteAgentState(**defaults)


def test_validate_node_returns_report():
    state = _state()

    result = asyncio.run(_validate_node(state))

    report = result.get("validation_report")
    assert report is not None
    assert isinstance(report.overall_passed, bool)
    assert result["validation_result"]["passed"] == report.overall_passed
    assert result["validation_round"] == 1
    assert result["constraint_adjustments"] == []


def test_validate_node_classification_failure():
    state = _state(
        session_id="s2",
        parcel_changeset=_make_changeset(
            changes=[ParcelChange(bsm="P001", action="reclassify", after_classification=None)]
        ),
    )

    result = asyncio.run(_validate_node(state))

    assert result["validation_result"]["passed"] is False
    violations = result["validation_result"]["violations"]
    assert any(v["check"] == "classification_missing" for v in violations)
    report = result.get("validation_report")
    assert report is not None
    assert "EXECUTE" in report.issues_by_stage
    assert any(i.code == "classification_missing" for i in report.issues_by_stage["EXECUTE"])


def test_validate_node_no_layout():
    state = _state(session_id="s3", layout_configs=[])

    result = asyncio.run(_validate_node(state))

    assert result["validation_result"]["passed"] is False
    assert result["validation_result"]["reason"] == "no_layout"


def test_validate_node_execution_errors():
    state = _state(
        session_id="s4",
        execution_errors=[{"code": "road_failed", "message": "x"}],
    )

    result = asyncio.run(_validate_node(state))

    assert result["validation_result"]["passed"] is False
    assert result["validation_result"]["reason"] == "execution_errors"


def test_validate_node_no_layout_validator_import():
    source = _EXECUTE_AGENT_PATH.read_text(encoding="utf-8")

    assert "from app.tools.gis._validation.layout_validator import" not in source
    assert "LayoutValidator" not in source


def test_state_validation_report_field():
    state = ExecuteAgentState()

    assert state.validation_report is None
