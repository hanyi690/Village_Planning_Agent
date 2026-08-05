"""PostL3ChainState retry fields tests (Wave M2)."""

from app.agent.bootstrap.post_l3_state import PostL3ChainState


def test_retry_counts_defaults():
    state = PostL3ChainState()
    assert state.retry_counts == {}
    assert state.max_retries == 3


def test_explore_cache_defaults():
    state = PostL3ChainState()
    assert state.explore_cache == {}


def test_human_review_items_defaults():
    state = PostL3ChainState()
    assert state.human_review_items == []


def test_retry_fields_round_trip():
    state = PostL3ChainState(
        retry_counts={"parse": 1, "validate": 2},
        max_retries=5,
        explore_cache={"key": "value"},
        human_review_items=[{"item_id": "hi-1"}],
    )
    assert state.retry_counts["parse"] == 1
    assert state.max_retries == 5
    assert state.explore_cache["key"] == "value"
    assert len(state.human_review_items) == 1
