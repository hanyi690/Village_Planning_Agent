"""P1: StateFactory output keys must match AgentState fields exactly."""
from app.agent.plan_state.state import AgentState
from app.agent.plan_state.state_factory import StateFactory


def test_factory_keys_subset_of_agent_state():
    state = StateFactory.create(session_id="s1", project_name="p", village_data="v")
    agent_keys = set(AgentState.__annotations__.keys())
    factory_keys = set(state.keys())
    extra = factory_keys - agent_keys
    assert not extra, (
        f"StateFactory sets keys not in AgentState (will be dropped by LangGraph): {extra}"
    )


def test_factory_sets_all_required_agent_state_fields():
    state = StateFactory.create(session_id="s1", project_name="p", village_data="v")
    required = {"session_id", "project_name", "phase", "current_wave", "messages", "config"}
    assert required.issubset(state.keys())


def test_factory_sets_dimension_key_and_explore_done():
    state = StateFactory.create(session_id="s1", project_name="p", village_data="v")
    assert "dimension_key" in state, "dimension_key must be in factory output"
    assert "explore_done" in state, "explore_done must be in factory output"
    assert state["dimension_key"] is None
    assert state["explore_done"] is False
