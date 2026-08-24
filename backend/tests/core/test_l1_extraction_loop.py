"""Bounded L1 loop and resume behavior."""

from pathlib import Path

import pytest

from app.contracts.domain.l1_contracts import L1DimensionPassState
from app.domain.assessment.input_register import (
    build_l1_source_index,
    materialize_dimension_register_rows,
)
from app.domain.assessment.observation_draft import (
    L1ObservationPassOutput,
    L1ReportOutput,
    L1RegisterRowDraft,
    L1RegisterPassOutput,
)


def _source_index():
    source = (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "public"
        / "demo"
        / "jintian_village.md"
    ).read_text(encoding="utf-8")
    return build_l1_source_index({"village_data": source})


def _source_index_with_rows():
    source_index = _source_index()
    segment = next(
        segment for segment in source_index.source_segments if "村道硬化" in segment.text
    )
    rows, diagnostics = materialize_dimension_register_rows(
        [
            L1RegisterRowDraft(
                ledger_kind="current_asset",
                name="村道硬化",
                source_segment_ids=[segment.segment_id],
                source_quote="村道硬化",
            )
        ],
        source_index,
        "traffic",
    )
    assert diagnostics == []
    return source_index.model_copy(update={"current_assets": rows})


@pytest.mark.asyncio
async def test_l1_loop_uses_targeted_evidence_and_materializes_canonical_rows(monkeypatch):
    from app.domain.assessment import l1_extraction_loop

    source_index = _source_index_with_rows()
    row = source_index.current_assets[0]
    calls: list[type] = []
    checkpoints: list[dict] = []

    async def fake_runner(response_model, _messages, **_kwargs):
        calls.append(response_model)
        if response_model is L1ObservationPassOutput:
            return L1ObservationPassOutput(
                observations=[],
                register_rows=[
                    {
                        "row_id": row.row_id,
                        "ledger_kind": "current_asset",
                        "status": "uncertain",
                    }
                ],
                coverage=[],
            )
        if response_model is L1ReportOutput:
            return L1ReportOutput(report_body="交通现状正文。")
        return L1RegisterPassOutput(
            register_rows=[
                {
                    "row_id": row.row_id,
                    "ledger_kind": "current_asset",
                    "status": "confirmed",
                }
            ],
            coverage=[],
        )

    async def lookup(query: str, required: list[str]) -> str:
        assert row.name in query
        assert row.name in required
        return "统一证据：该行属于交通现状。"

    async def checkpoint(payload: dict):
        checkpoints.append(payload)

    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fake_runner,
    )
    result = await l1_extraction_loop.run_l1_dimension_loop(
        dimension_key="traffic",
        prompt="交通维度",
        source_index=source_index,
        runner_kwargs={"max_retries": 0},
        evidence_lookup=lookup,
        checkpoint_writer=checkpoint,
        max_calls=3,
    )

    assert calls == [
        L1ObservationPassOutput,
        L1RegisterPassOutput,
        L1ReportOutput,
    ]
    assert result.report_body == "交通现状正文。"
    assert result.register_rows[0].name == row.name
    assert result.register_rows[0].status == "confirmed"
    assert result.cursor is not None
    assert result.cursor.status == "complete"
    assert checkpoints[-1]["cursor"]["status"] == "complete"
    assert result.retrieval_trace


@pytest.mark.asyncio
async def test_l1_loop_repairs_generated_registration_without_preparsed_rows(monkeypatch):
    from app.domain.assessment import l1_extraction_loop

    source_index = _source_index()
    segment = next(
        segment for segment in source_index.source_segments if "村道硬化" in segment.text
    )
    draft = {
        "ledger_kind": "current_asset",
        "name": "村道硬化",
        "status": "uncertain",
        "source_segment_ids": [segment.segment_id],
        "source_quote": "村道硬化",
    }
    expected, diagnostics = materialize_dimension_register_rows(
        [draft], source_index, "traffic"
    )
    assert diagnostics == []
    expected_id = expected[0].row_id

    async def fake_runner(response_model, messages, **_kwargs):
        if response_model is L1ObservationPassOutput:
            return L1ObservationPassOutput(
                observations=[],
                register_rows=[draft],
                coverage=[],
            )
        if response_model is L1ReportOutput:
            return L1ReportOutput(report_body="交通现状正文。")
        assert "村道硬化" in str(messages)
        return L1RegisterPassOutput(
            register_rows=[
                {
                    "row_id": expected_id,
                    "ledger_kind": "current_asset",
                    "status": "confirmed",
                }
            ],
            coverage=[],
        )

    async def lookup(query: str, required: list[str]) -> str:
        assert "村道硬化" in query
        assert "村道硬化" in required
        return "统一证据：该行属于交通现状。"

    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fake_runner,
    )
    result = await l1_extraction_loop.run_l1_dimension_loop(
        dimension_key="traffic",
        prompt="交通维度",
        source_index=source_index,
        runner_kwargs={"max_retries": 0},
        evidence_lookup=lookup,
        max_calls=3,
    )

    assert result.register_rows[0].row_id == expected_id
    assert result.register_rows[0].status == "confirmed"
    assert result.cursor is not None
    assert result.cursor.status == "complete"


@pytest.mark.asyncio
async def test_l1_loop_resume_skips_completed_observe_pass(monkeypatch):
    from app.domain.assessment import l1_extraction_loop

    source_index = _source_index_with_rows()
    row = source_index.current_assets[0]
    calls: list[type] = []

    async def fake_runner(response_model, _messages, **_kwargs):
        calls.append(response_model)
        return L1RegisterPassOutput(
            register_rows=[
                {
                    "row_id": row.row_id,
                    "ledger_kind": "current_asset",
                    "status": "confirmed",
                }
            ],
            coverage=[],
        )

    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fake_runner,
    )
    cursor = L1DimensionPassState(
        dimension_key="traffic",
        source_digest=source_index.source_digest,
        pass_name="register",
        attempt=1,
        calls_used=1,
        pending_row_ids=[row.row_id],
    )
    result = await l1_extraction_loop.run_l1_dimension_loop(
        dimension_key="traffic",
        prompt="不会再次发送完整正文",
        source_index=source_index,
        runner_kwargs={"max_retries": 0},
        previous_cursor=cursor,
        resume_payload={
            "report_body": "已完成的 observe 正文。",
            "observations": [],
            "register_rows": [],
            "coverage": [],
            "cursor": cursor.model_dump(mode="json"),
        },
        max_calls=2,
    )

    assert calls == [L1RegisterPassOutput]
    assert result.report_body == "已完成的 observe 正文。"
    assert result.cursor is not None
    assert result.cursor.status == "complete"


@pytest.mark.asyncio
async def test_l1_loop_does_not_spend_repair_call_on_confirmed_row(monkeypatch):
    from app.domain.assessment import l1_extraction_loop

    source_index = _source_index_with_rows()
    row = source_index.current_assets[0]
    calls: list[type] = []

    async def fake_runner(response_model, _messages, **_kwargs):
        calls.append(response_model)
        if response_model is L1ObservationPassOutput:
            return L1ObservationPassOutput(
            observations=[],
            register_rows=[
                {
                    "row_id": row.row_id,
                    "ledger_kind": "current_asset",
                    "status": "confirmed",
                }
            ],
                coverage=[],
            )
        return L1ReportOutput(report_body="交通现状。")

    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fake_runner,
    )
    result = await l1_extraction_loop.run_l1_dimension_loop(
        dimension_key="traffic",
        prompt="交通维度",
        source_index=source_index,
        max_attempts=2,
        max_calls=4,
    )

    assert calls == [L1ObservationPassOutput, L1ReportOutput]
    assert result.cursor is not None
    assert result.cursor.status == "complete"
    assert result.cursor.confirmed_row_ids == [row.row_id]


@pytest.mark.asyncio
async def test_l1_loop_rejects_stale_cursor_without_reusing_payload(monkeypatch):
    from app.domain.assessment import l1_extraction_loop

    source_index = _source_index()
    calls: list[type] = []

    async def fake_runner(response_model, _messages, **_kwargs):
        calls.append(response_model)
        if response_model is L1ObservationPassOutput:
            return L1ObservationPassOutput(
            observations=[],
            register_rows=[],
                coverage=[],
            )
        return L1ReportOutput(report_body="重新生成正文。")

    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fake_runner,
    )
    stale = L1DimensionPassState(
        dimension_key="landscape",
        source_digest="different-source",
        pass_name="complete",
        status="complete",
    )
    result = await l1_extraction_loop.run_l1_dimension_loop(
        dimension_key="traffic",
        prompt="不得复用旧报告",
        source_index=source_index,
        previous_cursor=stale,
        resume_payload={
            "report_body": "不应返回的旧报告",
            "cursor": stale.model_dump(mode="json"),
        },
    )

    assert calls == [L1ObservationPassOutput, L1ReportOutput]
    assert result.report_body == "重新生成正文。"
    assert "l1_resume_cursor_stale" in result.diagnostics
    assert result.cursor is not None
    assert result.cursor.status == "diagnostic"
