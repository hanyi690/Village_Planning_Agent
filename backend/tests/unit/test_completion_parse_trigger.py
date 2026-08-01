"""E 子任务：wave 完成触发 PARSE binding 抽取。"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app.agent.state import get_layer_dimensions


def test_layer1_complete_triggers_extraction(monkeypatch):
    import app.agent.completion.node as node_mod

    calls = []

    async def fake_extract(session_id: str, layer: int) -> None:
        calls.append((session_id, layer))

    monkeypatch.setattr(node_mod, "_maybe_extract_bindings", fake_extract)
    monkeypatch.setattr(
        "app.utils.sse_publisher.SSEPublisher.send_layer_complete",
        lambda **kw: None,
    )
    monkeypatch.setattr(
        "app.utils.sse_publisher.SSEPublisher.send_layer_start",
        lambda **kw: None,
    )
    monkeypatch.setattr(node_mod, "_snapshot_bundle", AsyncMock(return_value=None))

    dims = get_layer_dimensions(1)
    state = {
        "phase": "layer1",
        "session_id": "sess-wave",
        "completed_dimensions": {"layer1": dims},
        "layer_char_counts": {1: 500},
        "pending_reports": [],
        "step_mode": False,
    }

    result = asyncio.run(node_mod.layer_completion_check(state))

    assert calls == [("sess-wave", 1)]
    assert result["phase"] == "layer2"


def test_maybe_extract_bindings_is_non_fatal(monkeypatch):
    """无 session KG 时 helper 必须吞掉一切异常，不冒泡。"""
    import app.agent.completion.node as node_mod
    from app.modules.kg import get_kg_manager

    get_kg_manager().remove_session("sess-nokg")

    async def run():
        await node_mod._maybe_extract_bindings("sess-nokg", 1)
        return "ok"

    assert asyncio.run(run()) == "ok"
