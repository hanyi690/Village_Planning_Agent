"""Compiler projection tests for materialized L1 dimension rows."""

import json
from pathlib import Path

from app.contracts.workflow.parsing_contracts import CompilationProfile
from app.data.ingestion.compiler.core import compile_dimension_report
from app.domain.assessment.input_register import (
    build_l1_source_index,
    materialize_dimension_register_rows,
)
from app.domain.assessment.aggregate import merge_l1_snapshots
from app.domain.assessment.observation_draft import L1RegisterRowDraft


def _source_index_with_rows():
    source = (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "public"
        / "demo"
        / "jintian_village.md"
    ).read_text(encoding="utf-8")
    source_index = build_l1_source_index({"village_data": source})
    current_segment = next(
        segment for segment in source_index.source_segments if "村道硬化" in segment.text
    )
    demand_segment = next(
        segment for segment in source_index.source_segments if "河道修复" in segment.text
    )
    rows, diagnostics = materialize_dimension_register_rows(
        [
            L1RegisterRowDraft(
                ledger_kind="current_asset",
                name="村道硬化",
                source_segment_ids=[current_segment.segment_id],
                source_quote="村道硬化",
            ),
            L1RegisterRowDraft(
                ledger_kind="demand",
                name="河道修复",
                source_segment_ids=[demand_segment.segment_id],
                source_quote="河道修复",
            ),
        ],
        source_index,
        "traffic",
    )
    assert diagnostics == []
    return source_index.model_copy(update={
        "current_assets": [rows[0]],
        "demands": [rows[1]],
    })


def test_compiler_projects_materialized_rows_without_reading_raw_input() -> None:
    register = _source_index_with_rows()
    row = register.current_assets[0].model_copy(update={"dimension_key": "traffic"})
    instruction = json.dumps(
        {
            "observations": [],
            "register_rows": [row.model_dump(mode="json")],
            "source_documents": register.source_documents,
            "source_digest": register.source_digest,
        },
        ensure_ascii=False,
    )

    snapshot = compile_dimension_report(
        CompilationProfile.L1_OBSERVATION,
        dimension_key="traffic",
        content="# 交通\n\n【事实】村道硬化属于现状资产。",
        instruction=instruction,
        report_id="report-traffic-1",
        run_id="run-1",
    )

    assert snapshot is not None
    assert snapshot.register_rows_by_dimension["traffic"][0].name == "村道硬化"
    assert snapshot.input_register is not None
    assert len(snapshot.input_register.current_assets) == 1
    assert snapshot.input_register.source_digest == register.source_digest


def test_dimension_rows_merge_by_dimension_and_keep_current_demand_separate() -> None:
    register = _source_index_with_rows()
    current = register.current_assets[0].model_copy(update={"dimension_key": "traffic"})
    demand = register.demands[0].model_copy(update={"dimension_key": "traffic"})
    current_snapshot = compile_dimension_report(
        CompilationProfile.L1_OBSERVATION,
        dimension_key="traffic",
        content="# 交通\n\n道路现状。",
        instruction=json.dumps(
            {
                "register_rows": [current.model_dump(mode="json")],
                "source_documents": register.source_documents,
                "source_digest": register.source_digest,
            },
            ensure_ascii=False,
        ),
        report_id="report-traffic-1",
        run_id="run-1",
    )
    demand_snapshot = compile_dimension_report(
        CompilationProfile.L1_OBSERVATION,
        dimension_key="public_services",
        content="# 需求\n\n服务需求。",
        instruction=json.dumps(
            {
                "register_rows": [demand.model_copy(update={"dimension_key": "public_services"}).model_dump(mode="json")],
                "source_documents": register.source_documents,
                "source_digest": register.source_digest,
            },
            ensure_ascii=False,
        ),
        report_id="report-public-1",
        run_id="run-1",
    )

    merged = merge_l1_snapshots([current_snapshot, demand_snapshot], run_id="run-1")

    assert merged.register_rows_by_dimension["traffic"][0].ledger_kind == "current_asset"
    assert merged.register_rows_by_dimension["public_services"][0].ledger_kind == "demand"
    assert merged.input_register is not None
    assert merged.input_register.current_assets[0].row_id == current.row_id
    assert merged.input_register.demands[0].row_id == demand.row_id
