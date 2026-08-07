from app.agent.plan_state.state import AgentState, create_initial_state

REQUIRED_POST_L3_KEYS = (
    "execution_errors", "layout_configs",
    "artifact_refs",
)

def test_agent_state_declares_post_l3_output_keys():
    hints = AgentState.__annotations__
    for key in REQUIRED_POST_L3_KEYS:
        assert key in hints, f"AgentState missing post-L3 channel: {key}"

def test_create_initial_state_seeds_post_l3_outputs():
    s = create_initial_state("s1", "v1", "data")
    for key in REQUIRED_POST_L3_KEYS:
        assert key in s, f"create_initial_state missing seed for: {key}"
