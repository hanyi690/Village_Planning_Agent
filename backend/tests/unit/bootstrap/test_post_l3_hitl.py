"""Post-L3 chain HITL tests (Wave N P5) — interrupt + resume + API.

Covers:
1. HUMAN gate pauses the chain at human_review (ainvoke returns __interrupt__).
2. Resume via Command(resume=...) continues to END and backfills
   human_review_decisions.
3. No HUMAN items -> no pause.
4. gis_agent_node captures the interrupt and returns pending state.
5. resume_post_l3_chain service (pause -> resume -> persist -> AgentState write-back).
6. human-review API routes (GET pending / POST resolve).

All I/O is mocked: no LLM, no DB, no SSE.
"""

from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, Interrupt

from app.agent.bootstrap.post_l3_chain import build_post_l3_chain
from app.agent.bootstrap.post_l3_state import PostL3ChainState
from app.modules.schema.contracts.workflow_contracts import GateDecision, PendingRequest


def _human_gate(stage="parse"):
    return GateDecision(
        stage=stage,
        passed=False,
        feedback_route="HUMAN",
        pending_requests=[
            PendingRequest(
                request_id="pr-1",
                stage=stage,
                request_type="parse_human",
                context={"reason": "HUMAN"},
            ),
        ],
    )


def _pass_gate(stage="parse"):
    return GateDecision(stage=stage, passed=True, feedback_route=None)


async def _fake_node(state):
    return {}


def _patch_chain_nodes(monkeypatch):
    import app.agent.bootstrap.post_l3_chain as chainmod

    for name in (
        "parse_node", "ground_node", "select_node", "execute_node",
        "validate_node", "reconcile_node", "deliver_node",
    ):
        monkeypatch.setattr(chainmod, name, _fake_node)


def _chain_state(session_id="s1", gate=None):
    data = PostL3ChainState(session_id=session_id, context=None, messages=[]).model_dump()
    data["parse_gate"] = gate
    data["human_review_items"] = []
    return data


def _bundle():
    from app.modules.schema.types.canonical import VillageBundle

    return VillageBundle(village_name="金田村")


def _context():
    return SimpleNamespace(
        bundle=_bundle(),
        gazetteer=None,
        kg_session_ref="kg-1",
        village_name="金田村",
        context_version="v1",
        reports={},
        report_summary_index={},
        constraint_index=None,
        village_anchors=[],
    )


# ── 1. HUMAN gate pauses the chain ──

@pytest.mark.asyncio
async def test_human_review_pauses_with_interrupt(monkeypatch):
    _patch_chain_nodes(monkeypatch)
    cp = InMemorySaver()
    graph = build_post_l3_chain(checkpointer=cp)
    config = {"configurable": {"thread_id": "hitl-1"}}

    res = await graph.ainvoke(_chain_state(gate=_human_gate()), config)
    interrupts = res.get("__interrupt__") or []
    assert len(interrupts) == 1
    payload = interrupts[0].value
    assert payload["reason"] == "post_l3_human_review"
    assert payload["human_review_items"][0]["request_id"] == "pr-1"

    snap = await graph.aget_state(config)
    assert "human_review" in snap.next


# ── 2. Resume continues to END and backfills decisions ──

@pytest.mark.asyncio
async def test_human_review_resume_backfills_decisions(monkeypatch):
    _patch_chain_nodes(monkeypatch)
    cp = InMemorySaver()
    graph = build_post_l3_chain(checkpointer=cp)
    config = {"configurable": {"thread_id": "hitl-2"}}

    await graph.ainvoke(_chain_state(gate=_human_gate()), config)

    final = None
    async for chunk in graph.astream(
        Command(resume={"approve": True, "note": "ok"}),
        config,
        stream_mode=["values"],
        version="v2",
    ):
        final = chunk

    data = final.get("data") if isinstance(final, dict) else final
    if hasattr(data, "model_dump"):
        data = data.model_dump()
    assert data["human_review_decisions"] == {"approve": True, "note": "ok"}
    assert len(data["human_review_items"]) == 1

    snap = await graph.aget_state(config)
    assert not snap.next  # reached END


# ── 3. No HUMAN items -> no pause ──

@pytest.mark.asyncio
async def test_human_review_no_items_no_pause(monkeypatch):
    _patch_chain_nodes(monkeypatch)
    cp = InMemorySaver()
    graph = build_post_l3_chain(checkpointer=cp)
    config = {"configurable": {"thread_id": "hitl-3"}}

    res = await graph.ainvoke(_chain_state(gate=_pass_gate()), config)
    assert "__interrupt__" not in res
    assert res["human_review_items"] == []


# ── 4. gis_agent_node captures the interrupt ──

@pytest.mark.asyncio
async def test_gis_agent_node_captures_interrupt(monkeypatch):
    from app.agent.bootstrap.gis_agent_entry import gis_agent_node

    async def fake_build_planning_context(*a, **k):
        return _context()

    async def fake_l3_aggregate(state):
        raise RuntimeError("no reports")

    async def fake_get_global_checkpointer():
        return object()

    class FakeChain:
        async def ainvoke(self, state, config=None):
            return {
                "__interrupt__": [
                    Interrupt(
                        value={
                            "human_review_items": [
                                {"request_id": "pr-1", "stage": "parse"},
                            ],
                            "reason": "post_l3_human_review",
                        },
                        id="x",
                    ),
                ]
            }

    monkeypatch.setattr(
        "app.services.context.build_planning_context", fake_build_planning_context
    )
    monkeypatch.setattr("app.agent.l3_plan.aggregate.l3_aggregate", fake_l3_aggregate)
    monkeypatch.setattr("app.database.engine.get_global_checkpointer", fake_get_global_checkpointer)
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_chain.build_post_l3_chain",
        lambda checkpointer=None: FakeChain(),
    )

    out = await gis_agent_node(
        {
            "session_id": "s1",
            "config": {"village_name": "金田村"},
            "user_uploaded_data": {},
            "messages": [],
        }
    )
    assert out["post_l3_status"] == "needs_human_review"
    assert out["post_l3_thread_id"] == "s1"
    assert out["post_l3_pending_review"][0]["request_id"] == "pr-1"


@pytest.mark.asyncio
async def test_gis_agent_node_captures_graph_interrupt_exception(monkeypatch):
    """Defensive path: ainvoke raises GraphInterrupt (e.g. no checkpointer)."""
    from langgraph.errors import GraphInterrupt

    from app.agent.bootstrap.gis_agent_entry import gis_agent_node

    async def fake_build_planning_context(*a, **k):
        return _context()

    async def fake_l3_aggregate(state):
        raise RuntimeError("no reports")

    async def fake_get_global_checkpointer():
        return object()

    class FakeChain:
        async def ainvoke(self, state, config=None):
            raise GraphInterrupt(
                [
                    Interrupt(
                        value={
                            "human_review_items": [
                                {"request_id": "pr-1", "stage": "parse"},
                            ],
                            "reason": "post_l3_human_review",
                        },
                        id="x",
                    ),
                ]
            )

    monkeypatch.setattr(
        "app.services.context.build_planning_context", fake_build_planning_context
    )
    monkeypatch.setattr("app.agent.l3_plan.aggregate.l3_aggregate", fake_l3_aggregate)
    monkeypatch.setattr("app.database.engine.get_global_checkpointer", fake_get_global_checkpointer)
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_chain.build_post_l3_chain",
        lambda checkpointer=None: FakeChain(),
    )

    out = await gis_agent_node(
        {
            "session_id": "s1",
            "config": {"village_name": "金田村"},
            "user_uploaded_data": {},
            "messages": [],
        }
    )
    assert out["post_l3_status"] == "needs_human_review"
    assert out["post_l3_pending_review"][0]["request_id"] == "pr-1"


# ── 5. resume_post_l3_chain service ──

@pytest.mark.asyncio
async def test_resume_post_l3_chain_service(monkeypatch, tmp_path):
    import app.services.post_l3_resume as resumemod
    from app.services.post_l3_resume import PostL3ResultStore, resume_post_l3_chain

    _patch_chain_nodes(monkeypatch)

    cp = InMemorySaver()

    async def fake_get_global_checkpointer():
        return cp

    monkeypatch.setattr(resumemod, "get_global_checkpointer", fake_get_global_checkpointer)

    fake_store = PostL3ResultStore(base_dir=str(tmp_path))
    monkeypatch.setattr(resumemod, "PostL3ResultStore", lambda: fake_store)

    # Pause the chain on the shared checkpointer (same thread_id).
    graph = build_post_l3_chain(checkpointer=cp)
    config = {"configurable": {"thread_id": "hitl-resume"}}
    await graph.ainvoke(_chain_state(session_id="hitl-resume", gate=_human_gate()), config)

    write_back = {}

    async def fake_aupdate_state(session_id, updates, as_node=None):
        write_back["updates"] = updates
        write_back["as_node"] = as_node

    from app.services.runtime import PlanningRuntimeService

    monkeypatch.setattr(
        PlanningRuntimeService, "aupdate_state", fake_aupdate_state
    )

    result = await resume_post_l3_chain("hitl-resume", {"approve": True, "note": "ok"})
    assert result["session_id"] == "hitl-resume"
    assert result["human_review_decisions"] == {"approve": True, "note": "ok"}
    assert len(result["human_review_items"]) == 1
    assert write_back["updates"]["post_l3_status"] == "resumed"
    assert write_back["updates"]["post_l3_pending_review"] == []

    stored = fake_store.get("hitl-resume")
    assert stored is not None
    assert stored["result"]["human_review_decisions"] == {"approve": True, "note": "ok"}


# ── 6. human-review API routes ──

@pytest.mark.asyncio
async def test_human_review_api_get_and_resolve(monkeypatch):
    import app.api.human_review_routes as hr
    from app.api.human_review_routes import ResolveRequest, get_human_review, resolve_human_review

    async def fake_aget_state_values(session_id):
        return {
            "session_id": session_id,
            "post_l3_pending_review": [{"request_id": "pr-1"}],
            "post_l3_status": "needs_human_review",
        }

    from app.services.runtime import PlanningRuntimeService

    monkeypatch.setattr(
        PlanningRuntimeService, "aget_state_values", fake_aget_state_values
    )

    async def fake_resume(session_id, decisions):
        return {
            "session_id": session_id,
            "status": "done",
            "human_review_decisions": decisions,
        }

    monkeypatch.setattr(hr, "resume_post_l3_chain", fake_resume)

    resp = await get_human_review("s1")
    assert resp["count"] == 1
    assert resp["post_l3_status"] == "needs_human_review"
    assert resp["pending_items"][0]["request_id"] == "pr-1"

    resp2 = await resolve_human_review("s1", ResolveRequest(decisions={"approve": True}))
    assert resp2["resolved"] is True
    assert resp2["result"]["human_review_decisions"] == {"approve": True}


@pytest.mark.asyncio
async def test_human_review_api_get_404(monkeypatch):
    from app.api.human_review_routes import get_human_review
    from fastapi import HTTPException

    from app.services.runtime import PlanningRuntimeService

    async def fake_aget_state_values(session_id):
        return None

    monkeypatch.setattr(
        PlanningRuntimeService, "aget_state_values", fake_aget_state_values
    )

    with pytest.raises(HTTPException) as exc:
        await get_human_review("missing")
    assert exc.value.status_code == 404
