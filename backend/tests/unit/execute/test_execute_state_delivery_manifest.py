"""EXECUTE Agent state: DELIVER output field (delivery_manifest) defaulting."""

from app.agent.execute.execute_state import ExecuteAgentState
from app.modules.schema.contracts.delivery_manifest_contracts import DeliveryManifest


def test_execute_state_delivery_manifest_defaults_none():
    state = ExecuteAgentState()
    assert state.delivery_manifest is None


def test_execute_state_delivery_manifest_round_trip():
    dm = DeliveryManifest(statutory_complete=True)
    state = ExecuteAgentState(delivery_manifest=dm)
    assert state.delivery_manifest is dm
    assert state.delivery_manifest.statutory_complete is True
