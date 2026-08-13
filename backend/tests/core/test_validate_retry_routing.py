from __future__ import annotations

from types import SimpleNamespace

from app.workflow import root_graph


def _state(*, executable_repair: bool) -> dict:
    state = {
        "retry_counts": {"validate": 0},
        "config": {"max_retries": 3},
        "stage_audit": {"VALIDATE": {"issue_fingerprint": "same-issue"}},
    }
    if executable_repair:
        state["repair_impact"] = {
            "status": "ready",
            "earliest_invalid_stage": "SELECT",
            "directive_ids": ["directive-1"],
        }
    return state


def test_validate_repeated_fingerprint_does_not_block_new_executable_repair(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        root_graph,
        "load_root_gate",
        lambda _state, _stage: SimpleNamespace(issue_fingerprint="same-issue"),
    )

    assert root_graph._retry_or_human(_state(executable_repair=True), "validate", "select") == "select"


def test_validate_repeated_fingerprint_still_blocks_without_repair(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        root_graph,
        "load_root_gate",
        lambda _state, _stage: SimpleNamespace(issue_fingerprint="same-issue"),
    )

    assert (
        root_graph._retry_or_human(_state(executable_repair=False), "validate", "select")
        == "human_review"
    )
