"""L1 source-index validation and dimension materialization tests."""

from pathlib import Path

from app.domain.assessment.input_register import (
    build_l1_source_index,
    materialize_dimension_register_rows,
    render_l1_source_index,
)
from app.domain.assessment.observation_draft import L1RegisterRowDraft


def _source() -> str:
    return (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "public"
        / "demo"
        / "jintian_village.md"
    ).read_text(encoding="utf-8")


def _source_index_with_rows():
    source_index = build_l1_source_index({"village_data": _source()})
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


def test_dimension_rows_are_materialized_from_canonical_source_ids() -> None:
    source_index = _source_index_with_rows()
    source_row = source_index.current_assets[0]

    rows, diagnostics = materialize_dimension_register_rows(
        [
            {
                "row_id": source_row.row_id,
                "ledger_kind": "current_asset",
                "status": "confirmed",
                "name": "模型改写名称",
                "evidence_note": "交通维度直接引用该行",
            }
        ],
        source_index,
        "traffic",
    )

    assert diagnostics == []
    assert rows[0].name == source_row.name == "村道硬化"
    assert rows[0].dimension_key == "traffic"
    assert rows[0].source_ref.startswith("input:village_data")
    assert rows[0].source_span == source_row.source_span


def test_dimension_rows_fail_closed_on_unknown_id_and_ledger_mismatch() -> None:
    source_index = _source_index_with_rows()
    demand = source_index.demands[0]

    rows, diagnostics = materialize_dimension_register_rows(
        [
            {
                "row_id": "l1:unknown:demand:1:1",
                "ledger_kind": "demand",
                "status": "confirmed",
            },
            {
                "row_id": demand.row_id,
                "ledger_kind": "current_asset",
                "status": "confirmed",
            },
        ],
        source_index,
        "infrastructure",
    )

    assert rows == []
    assert any(item.startswith("register_row_unknown:") for item in diagnostics)
    assert any("ledger_kind_mismatch" in item for item in diagnostics)


def test_source_index_prompt_is_compact_and_row_addressable() -> None:
    source_index = _source_index_with_rows()
    rendered = render_l1_source_index(
        source_index,
        row_ids=[source_index.current_assets[0].row_id],
    )

    assert source_index.source_digest in rendered
    assert source_index.current_assets[0].row_id in rendered
    assert source_index.current_assets[0].name in rendered
    assert source_index.demands[0].row_id not in rendered


def test_narrative_or_mixed_source_is_indexed_without_invented_ledger_rows() -> None:
    source_index = build_l1_source_index({
        "upload": "村口道路雨季积水，村民希望改善通行。\n未提供固定表头。"
    })

    assert source_index.current_assets == []
    assert source_index.demands == []
    assert source_index.source_segments
    assert source_index.source_segments[0].source_ref.startswith("input:upload")
    rendered = render_l1_source_index(source_index)
    assert "村口道路雨季积水" in rendered
