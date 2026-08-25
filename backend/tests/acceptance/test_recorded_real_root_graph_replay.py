"""Acceptance checks for replaying one real JinTian L1/L2/L3 run.

The first test keeps the complete recorded program and proves that the live
spatial pipeline preserves the real evidence boundary (it may stop at SELECT).
The second selects only claims whose original CAS domains were already closed;
it proves that a real-output subset can continue to EXECUTE/DELIVER without
changing claim text or manufacturing a geometry.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from tests.acceptance.test_upload_fixtures import _uploads
from tests.fixtures.db import make_session_with_uploads
from tests.support.recorded_planning_provider import RecordedPlanningProvider


_REAL_RUN_ROOT = Path(
    r"F:\project\Village_Planning_Agent\.run-tmp\real-llm-168aab33e29c4f56a2e1542aedfbc409"
)
_REAL_SESSION_DIR = _REAL_RUN_ROOT / "7ad20404-6e3d-4ce2-b343-bc2409a3c38f"

# These claims are selected from the original PlanningProgram without editing
# their statements, locators, quantities or spatial requirements.  The prior
# real GROUND CAS called this subset closed, but the current P1 contracts
# correctly expose its missing source/relation inputs instead of replaying a
# stale candidate domain.
_CLOSED_POINT_CLAIMS = frozenset({
    "PS-CLM-011",
    "L3-landscape-001",
    "L3-landscape-003",
    "L3-landscape-005",
    "L3-landscape-006",
    "PS-CLM-008",
    "PS-CLM-009",
    "traffic-i2",
    "traffic-i4",
})


def _install_recorded_provider(monkeypatch, provider: RecordedPlanningProvider) -> None:
    from app.infrastructure.llm import planning_claims
    from app.infrastructure.llm import structured
    from app.infrastructure.llm.planning_claims import PlanningClaimGenerator

    monkeypatch.setattr(structured, "run_structured_output", provider.structured_output)
    monkeypatch.setattr(planning_claims, "run_structured_output", provider.structured_output)
    monkeypatch.setattr(PlanningClaimGenerator, "_get_llm", lambda _self: provider)

    # The original upload body is not present in the recorded session.  Use
    # the provider's explicit replay-only CAS source transport so the strict
    # production source validator can still verify original segment IDs and
    # quotes without accepting unknown refs.
    from app.domain.assessment import analysis_node
    replay_source_index = provider.authoritative_source_index()
    monkeypatch.setattr(
        analysis_node,
        "_l1_source_index_for_state",
        lambda _state: replay_source_index,
    )

    from app.infrastructure.context import planning_context_factory
    original_get_cached_context = planning_context_factory.get_cached_context

    def replay_context(session_id: str):
        context = original_get_cached_context(session_id)
        if context is not None:
            context.l1_fact_records = list(
                provider.authoritative_l1_snapshot().fact_records
            )
            context.replay_mode = provider.replay_mode
            context.source_artifact_ref = provider.source_artifact_ref
        return context

    monkeypatch.setattr(
        planning_context_factory,
        "get_cached_context",
        replay_context,
    )


def _assert_replay_source_lineage(final: dict, provider: RecordedPlanningProvider) -> None:
    config = dict((final.get("runtime") or {}).get("config") or {})
    assert config.get("replay_mode") == provider.replay_mode
    assert config.get("source_artifact_ref") == provider.source_artifact_ref
    assert provider.replay_mode == "recorded_cas_source_lineage"
    assert provider.source_artifact_ref.endswith(
        "sha256/aa81723a5f32bdff6f8335963da13bef6b2309936f656af37a831efbf209a8a5"
    )
    assert provider.source_lineage
    assert all(
        mapped_ref.startswith("l1:fact:")
        for mapped_refs in provider.source_lineage.values()
        for mapped_ref in mapped_refs
    )


async def _run_root_graph(
    *,
    session_id: str,
    project_name: str,
    claim_ids,
    monkeypatch,
    tmp_path,
    stop_on_unresolved_classification: bool = False,
):
    provider = RecordedPlanningProvider(
        run_root=_REAL_RUN_ROOT,
        session_dir=_REAL_SESSION_DIR,
        claim_ids=claim_ids,
    )
    _install_recorded_provider(monkeypatch, provider)

    from app.workflow.plan_state.state_factory import StateFactory
    from app.workflow.root_graph import create_unified_planning_graph
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    run_root = tmp_path / "recorded-real-replay"
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(run_root))
    from app.infrastructure.paths import reset_run_tmp_root_cache

    reset_run_tmp_root_cache()
    await make_session_with_uploads(session_id, "金田村", uploads=_uploads())
    initial_state = StateFactory.create(
        session_id=session_id,
        project_name=project_name,
        village_name="金田村",
        rag_enabled=False,
        rag_layer_config={1: False, 2: False, 3: False},
        step_mode=False,
    )
    initial_state["run_id"] = session_id
    initial_state["phase"] = "layer1"
    initial_state["runtime"]["config"]["source_semantic_llm_enabled"] = False
    initial_state["runtime"]["config"]["replay_mode"] = provider.replay_mode
    initial_state["runtime"]["config"]["source_artifact_ref"] = provider.source_artifact_ref
    initial_state["messages"] = [AIMessage(
        content="",
        tool_calls=[{
            "name": "advance_planning_intent",
            "id": "recorded-real-intent",
            "args": {"reason": "recorded real L1/L2/L3 replay"},
        }],
    )]

    graph = create_unified_planning_graph(MemorySaver())
    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": 700,
        # The acceptance replay uses the repository's SQLite fixture.  Keep
        # report persistence serial so same-layer dependency reads observe
        # the preceding recorded worker without a SQLite writer race.
        "max_concurrency": 1,
    }
    values = await graph.ainvoke(initial_state, config)
    seen_interrupt_signatures: set[str] = set()
    terminal_interrupt_context: list[dict] = []
    for _ in range(45):
        snapshot = await graph.aget_state(config)
        iteration = _
        tasks = list(getattr(snapshot, "tasks", ()) or ()) if snapshot else []
        interrupts = [
            item
            for task in tasks
            for item in (getattr(task, "interrupts", ()) or ())
        ]
        if not interrupts:
            values = dict(getattr(snapshot, "values", None) or values or {})
            if values.get("delivery_status") or values.get("diagnostic_terminal"):
                break
            if not tasks:
                break
            values = await graph.ainvoke(None, config)
            continue
        interrupt_context = [
            getattr(item, "value", None)
            for item in interrupts
            if isinstance(getattr(item, "value", None), dict)
        ]
        interrupt_signature = json.dumps(
            interrupt_context,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        if interrupt_signature in seen_interrupt_signatures:
            raise AssertionError(
                "recorded real replay repeated the same HUMAN interrupt: "
                + interrupt_signature[:12000]
            )
        seen_interrupt_signatures.add(interrupt_signature)
        resume_payload = {"action": "approve", "decision": "approve"}
        interrupt_items = [
            row
            for item in interrupts
            if isinstance(getattr(item, "value", None), dict)
            for row in (item.value.get("items") or [])
            if isinstance(row, dict)
        ]
        if stop_on_unresolved_classification and any(
            str(row.get("request_type") or "") == "classification_decision_required"
            for row in interrupt_items
        ):
            terminal_interrupt_context = interrupt_context
            values = dict(getattr(snapshot, "values", None) or values or {})
            break
        decision_payload = next(
            (
                row.get("context", {}).get("decision_fingerprint")
                for row in interrupt_items
                if isinstance(row.get("context"), dict)
                and row["context"].get("decision_fingerprint")
            ),
            None,
        )
        if decision_payload is not None:
            from app.contracts.planning.p1_closure import HumanDecisionRecord

            typed_record = HumanDecisionRecord(
                decision_fingerprint=decision_payload,
                action="approve",
                decided_by="recorded-replay",
                comment="typed replay decision bound to current gate fingerprint",
            )
            resume_payload["decision_record"] = typed_record.model_dump(mode="json")
        values = await graph.ainvoke(Command(resume=resume_payload), config)
    else:
        raise AssertionError("recorded real replay did not reach a terminal state")
    final = dict((await graph.aget_state(config)).values or values or {})
    if terminal_interrupt_context:
        final["_replay_terminal_interrupt"] = terminal_interrupt_context
    _assert_replay_source_lineage(final, provider)
    return final, provider


@pytest.mark.asyncio
@pytest.mark.timeout(900)
@pytest.mark.e2e
async def test_recorded_real_full_program_preserves_classification_boundary(
    sqlite_db, pipeline_reset, monkeypatch, tmp_path
):
    """The complete real program stops at the explicit L3 classification boundary."""

    setup, teardown = sqlite_db
    await setup()
    final, provider = await _run_root_graph(
        session_id="recorded-real-full-" + uuid.uuid4().hex[:8],
        project_name="金田村真实 L1-L3 全量回放",
        claim_ids=None,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        stop_on_unresolved_classification=True,
    )
    from app.infrastructure.artifacts.runtime import load_artifact
    from app.contracts.domain.l1_contracts import L1Snapshot
    from app.contracts.domain.l2_contracts import L2Strategy
    from app.contracts.domain.l3_contracts import PlanningProgram

    refs = dict(final.get("artifact_refs") or {})
    for key in ("l1_snapshot", "l2_strategy", "planning_program"):
        assert refs.get(key), f"recorded full replay missing artifact: {key}"
    l1 = load_artifact(final, "l1_snapshot", L1Snapshot)
    l2 = load_artifact(final, "l2_strategy", L2Strategy)
    program = load_artifact(final, "planning_program", PlanningProgram)
    assert len(l1.fact_records) == 195
    assert len(l2.decision_sets) == 4
    assert len(program.claims) == 196
    assert final.get("phase") == "layer3"
    classification_items = [
        item
        for payload in (final.get("_replay_terminal_interrupt") or [])
        for item in (payload.get("items") or [])
        if isinstance(item, dict)
        and item.get("request_type") == "classification_decision_required"
    ]
    assert classification_items
    assert not refs.get("target_projection")
    assert not refs.get("grounding_result")
    assert not refs.get("select_gate")
    assert not final.get("delivery_status")
    assert provider.calls.get("L1:observe:traffic") == 1
    assert provider.calls.get("L2:planning_positioning") == 1
    assert provider.calls.get("L3:claims:traffic_planning") == 1


@pytest.mark.asyncio
@pytest.mark.timeout(900)
@pytest.mark.e2e
async def test_recorded_real_incomplete_scope_stops_bounded_diagnostic(
    sqlite_db, pipeline_reset, monkeypatch, tmp_path
):
    """An incomplete real-output subset terminates with bounded diagnostics."""

    setup, teardown = sqlite_db
    await setup()
    final, provider = await _run_root_graph(
        session_id="recorded-real-closed-" + uuid.uuid4().hex[:8],
        project_name="金田村真实不闭合范围规划图层回放",
        claim_ids=_CLOSED_POINT_CLAIMS,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    refs = dict(final.get("artifact_refs") or {})
    for key in ("l1_snapshot", "l2_strategy", "planning_program", "target_projection"):
        assert refs.get(key), f"bounded diagnostic replay missing artifact: {key}"
    assert not refs.get("grounding_result")
    assert final.get("delivery_status") == "diagnostic_only"
    terminal = (
        final.get("diagnostic_terminal")
        or final.get("terminal_ref")
        or (final.get("runtime") or {}).get("diagnostic_terminal")
        or {}
    )
    assert terminal.get("stage") == "target_projection"
    assert terminal.get("reason") == "business_retry_exhausted"
    retry_counts = (
        final.get("retry_counts")
        or final.get("retry")
        or (final.get("runtime") or {}).get("retry_counts")
        or {}
    )
    assert retry_counts.get("target_projection") == 3
    assert provider.calls.get("L1:observe:public_services") == 1
    assert provider.calls.get("L3:claims:public_service") == 1
