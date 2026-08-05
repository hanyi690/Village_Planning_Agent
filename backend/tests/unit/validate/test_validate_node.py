"""EXECUTE _execution_review_node: execution checks only (Wave O).

The Wave O refactor replaced the internal full-VALIDATE node with a lightweight
execution review (input completeness / worker-output completeness / change
lineage / geometry validity / worker conflicts) that produces
``validation_result`` for the outer post-L3 VALIDATE stage. Covers the pass
path, and the input / execution-error / geometry / conflict failure paths.
"""

import asyncio
from pathlib import Path

from app.agent.execute.execute_agent import _execution_review_node
from app.agent.execute.execute_state import ExecuteAgentState
from app.modules.schema.contracts.classification_ref import ClassificationRef
from app.modules.schema.contracts.execution_plan_contracts import WorkerResult
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent

_EXECUTE_AGENT_PATH = (
    Path(__file__).resolve().parents[3] / "app" / "agent" / "execute" / "execute_agent.py"
)

WKT = "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))"


def _classified_change(bsm="P001", code="0701"):
    return ParcelChange(
        bsm=bsm,
        action="reclassify",
        derived_from_bsms=[bsm],
        after_classification=ClassificationRef(
            system="ghytbm", code=code, canonical_name="林地", source="derived"
        ),
        after_geometry_wkt=WKT,
        new_area_ha=1.0,
    )


def _make_changeset(changes=None):
    return ParcelChangeSet(changes=list(changes or []))


def _zone_result():
    return WorkerResult(
        worker_type="zone",
        layers=[{"layerType": "function_zone", "data": {"features": []}}],
        parcel_changes=[_classified_change()],
    )


def _state(**overrides):
    defaults = dict(
        session_id="s1",
        validation_result={},
        layout_configs=[{"layerType": "function_zone", "data": {"features": []}}],
        parcel_changeset=_make_changeset([_classified_change()]),
        intent=SpatialPlanningIntent(),
        gis_bundle=None,
        parcel_by_bsm={"P001": object()},
        tasks_to_run=["layout"],
        worker_results=[_zone_result()],
        worker_conflict_diagnostics=[],
        geometry_materialize_report={
            "geometry_valid": True,
            "checked_changes": 1,
            "diagnostics": [],
        },
    )
    defaults.update(overrides)
    return ExecuteAgentState(**defaults)


def test_execution_review_passes_with_complete_inputs():
    state = _state()

    result = asyncio.run(_execution_review_node(state))

    assert result["validation_result"]["passed"] is True
    assert result["validation_result"]["status"] == "pass"
    assert result["execution_review_report"]["passed"] is True
    assert result["validation_round"] == 1


def test_execution_review_fails_missing_inputs():
    state = _state(parcel_by_bsm={}, worker_results=[])

    result = asyncio.run(_execution_review_node(state))

    assert result["validation_result"]["passed"] is False
    assert result["validation_result"]["reason"] == "execution_review_failed"
    checks = {check["check"]: check["passed"] for check in result["execution_review_report"]["checks"]}
    assert checks["input_completeness"] is False
    assert checks["worker_output_completeness"] is False


def test_execution_review_fails_execution_errors():
    state = _state(
        execution_errors=[{"stage": "route", "code": "missing_session_kg", "message": "x"}],
    )

    result = asyncio.run(_execution_review_node(state))

    assert result["validation_result"]["passed"] is False
    violations = result["validation_result"]["violations"]
    assert any(v["check"] == "missing_session_kg" for v in violations)


def test_execution_review_fails_geometry_invalid():
    state = _state(
        geometry_materialize_report={
            "geometry_valid": False,
            "checked_changes": 1,
            "diagnostics": [
                {"code": "missing_after_geometry", "bsm": "P001", "action": "create"}
            ],
        },
    )

    result = asyncio.run(_execution_review_node(state))

    assert result["validation_result"]["passed"] is False
    violations = result["validation_result"]["violations"]
    assert any(v["check"] == "missing_after_geometry" for v in violations)


def test_execution_review_fails_worker_conflict():
    state = _state(
        worker_conflict_diagnostics=[
            {
                "type": "bsm_conflict",
                "bsm": "P001",
                "workers": [{"worker_type": "project", "after_code": "0701"}],
            }
        ],
    )

    result = asyncio.run(_execution_review_node(state))

    assert result["validation_result"]["passed"] is False
    violations = result["validation_result"]["violations"]
    assert any(v["check"] == "worker_conflict" for v in violations)


def test_execution_review_no_layout_validator_import():
    source = _EXECUTE_AGENT_PATH.read_text(encoding="utf-8")

    assert "from app.tools.gis._validation.layout_validator import" not in source
    assert "LayoutValidator" not in source


def test_state_validation_report_field():
    state = ExecuteAgentState()

    assert state.validation_report is None
