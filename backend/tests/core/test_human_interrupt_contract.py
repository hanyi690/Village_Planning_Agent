from app.agent.plan_state.state import state_to_ui_status
from app.modules.schema.contracts.human_interrupt_contracts import (
    HumanInterruptChannel,
    build_human_interrupt,
    normalize_human_decision,
    normalize_human_interrupt,
    stable_human_interrupt_id,
)


def test_step_mode_and_post_l3_use_the_same_payload_shape():
    step = build_human_interrupt(
        event_id="step-1",
        channel=HumanInterruptChannel.STEP_MODE,
        layer=1,
        phase="layer1",
        layer_name="现状分析",
        paused_stage="layer1",
        items=[{
            "request_id": "layer-1-completion-review",
            "stage": "layer1",
            "request_type": "layer_completion_review",
        }],
    )
    post_l3 = build_human_interrupt(
        event_id="post-l3-1",
        channel=HumanInterruptChannel.POST_L3_REVIEW,
        paused_stage="validate",
        items=[{
            "request_id": "validate-1",
            "stage": "validate",
            "request_type": "gate_review",
        }],
    )

    assert set(step) == set(post_l3)
    assert step["reason"] == post_l3["reason"] == "human_review_required"
    assert step["channel"] != post_l3["channel"]


def test_legacy_payload_is_normalized_at_the_boundary():
    normalized = normalize_human_interrupt({
        "human_review_event_id": "legacy-1",
        "human_review_items": [{
            "request_id": "validate-1",
            "stage": "validate",
            "request_type": "gate_review",
        }],
        "paused_stage": "validate",
        "reason": "post_l3_human_review",
    })

    assert normalized["event_id"] == "legacy-1"
    assert normalized["channel"] == "post_l3_review"
    assert normalized["items"][0]["request_id"] == "validate-1"
    assert normalized["reason"] == "human_review_required"


def test_decision_alias_is_normalized_before_business_logic():
    assert normalize_human_decision({"action": "accept"}) == {"action": "approve"}
    assert normalize_human_decision(None) == {"action": "approve"}


def test_interrupt_id_is_stable_for_equivalent_item_ordering():
    first = stable_human_interrupt_id(
        "session-1",
        HumanInterruptChannel.POST_L3_REVIEW,
        paused_stage="validate",
        items=[{"request_id": "a", "stage": "validate", "request_type": "gate_review"}],
    )
    second = stable_human_interrupt_id(
        "session-1",
        HumanInterruptChannel.POST_L3_REVIEW,
        paused_stage="validate",
        items=[{"request_type": "gate_review", "stage": "validate", "request_id": "a"}],
    )
    assert first == second


def test_ui_projection_exposes_canonical_interrupt_for_post_l3_pause():
    result = state_to_ui_status(
        {
            "session_id": "session-1",
            "phase": "layer3",
            "metadata": {},
            "human_interrupt": build_human_interrupt(
                event_id="post-l3-1",
                channel=HumanInterruptChannel.POST_L3_REVIEW,
                paused_stage="validate",
                items=[{
                    "request_id": "validate-1",
                    "stage": "validate",
                    "request_type": "gate_review",
                }],
            ),
        },
        is_interrupted=True,
    )

    assert result["status"] == "paused"
    assert result["interrupt_info"]["event_id"] == "post-l3-1"
    assert result["interrupt_info"]["channel"] == "post_l3_review"
    assert result["interrupt_info"]["items"][0]["request_id"] == "validate-1"
