from pathlib import Path

from app.contracts.domain.l1_contracts import L1InputRegister, L1Snapshot
from app.domain.assessment.input_register import (
    build_l1_source_index,
    materialize_dimension_register_rows,
    render_l1_input_register,
    render_l1_source_index,
)
from app.domain.assessment.observation_draft import L1RegisterRowDraft


def _demo_source() -> str:
    return (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "public"
        / "demo"
        / "jintian_village.md"
    ).read_text(encoding="utf-8")


def _segment_containing(register: L1InputRegister, text: str):
    return next(segment for segment in register.source_segments if text in segment.text)


def test_l1_source_index_keeps_arbitrary_input_as_segments_only() -> None:
    register = build_l1_source_index({"village_data": _demo_source()})

    assert isinstance(register, L1InputRegister)
    assert register.source_segments
    assert register.current_assets == []
    assert register.demands == []
    segment = _segment_containing(register, "村道硬化")
    rendered = render_l1_source_index(register)
    assert segment.segment_id in rendered
    assert segment.source_ref in rendered
    assert "村道硬化" in rendered


def test_l1_typed_draft_materializes_row_from_verified_segment() -> None:
    source_index = build_l1_source_index({"village_data": _demo_source()})
    segment = _segment_containing(source_index, "村道硬化")

    rows, diagnostics = materialize_dimension_register_rows(
        [
            L1RegisterRowDraft(
                ledger_kind="current_asset",
                status="confirmed",
                name="村道硬化",
                source_segment_ids=[segment.segment_id],
                source_quote="村道硬化",
                evidence_note="交通维度直接引用该证据段。",
            )
        ],
        source_index,
        "traffic",
    )

    assert diagnostics == []
    assert len(rows) == 1
    assert rows[0].name == "村道硬化"
    assert rows[0].ledger_kind == "current_asset"
    assert rows[0].dimension_key == "traffic"
    assert rows[0].source_ref == segment.source_ref
    assert rows[0].source_span == "村道硬化"


def test_l1_source_index_ignores_legacy_current_status_source() -> None:
    source = _demo_source()
    register = build_l1_source_index(
        {"village_data": source, "current_status": source}
    )

    assert register.source_documents == ["input:village_data"]
    assert len(register.source_segments) > 0
    assert "ignored_source:current_status:not_l1_fact_source" in register.diagnostics


def test_l1_source_index_does_not_infer_rows_from_narrative_input() -> None:
    register = build_l1_source_index({"village_data": "# 只有叙述，没有台账"})

    assert not register.current_assets
    assert not register.demands
    assert register.source_segments
    assert not any("ledger_sections_not_found" in item for item in register.diagnostics)


def test_register_is_nested_in_l1_snapshot_and_downstream_projection_is_not_raw() -> None:
    register = build_l1_source_index({"village_data": _demo_source()})
    snapshot = L1Snapshot(input_register=register)
    restored = L1Snapshot.model_validate(snapshot.model_dump(mode="json"))

    assert restored.input_register is not None
    assert restored.input_register.source_segments
    assert not restored.input_register.current_assets
    projection = render_l1_input_register(restored.input_register)
    assert "source_ref" not in projection
    assert "source_segments=" in projection
    assert "原始资料尚未确认现状资产/需求登记" in projection
    assert "【村庄需求台账】" not in projection
