from app.contracts.l1.l1_contracts import (
    L1ObservationSnapshot,
    L1SourceIndex,
    L1SourceSegment,
)
from app.modules.l1.aggregation import merge_l1_snapshots
from app.modules.l1.facts import make_l1_fact
from app.modules.l1.gate import evaluate_l1_gate
from app.modules.l1.observation_draft import (
    normalize_l1_observation_provider_output,
)
from app.modules.l1.source_span_validation import validate_observation_sources


def _source_index(text: str = "道路 R1 位于金田村") -> L1SourceIndex:
    return L1SourceIndex(
        source_digest="sha256:source-1",
        source_segments=[
            L1SourceSegment(
                segment_id="segment-1",
                source_key="document-1",
                source_ref="document:1",
                text=text,
                start_char=0,
                end_char=len(text),
            )
        ],
    )


def _observation(quote: str = "道路 R1 位于金田村"):
    output = normalize_l1_observation_provider_output(
        "location",
        {
            "observations": [{
                "fact_type": "spatial_entity",
                "entity_type": "road",
                "name": "道路 R1",
                "source_segment_ids": ["segment-1"],
                "source_quote": quote,
                "status": "confirmed",
            }],
        },
    )
    return output.observations[0]


def test_source_span_validation_persists_report_and_quarantines_invalid_row():
    result = validate_observation_sources(
        [_observation("不存在于来源")],
        _source_index(),
        dimension_key="location",
        source_snapshot_ref="sha256:source-1",
        page_ref="location:page:0",
    )

    assert result.accepted == []
    assert result.reports[0].status == "literal_mismatch"
    assert result.quarantine_records[0].reason_code == "literal_mismatch"
    assert result.quarantine_records[0].page_ref == "location:page:0"


def test_structured_observation_projection_keeps_typed_fact_and_mentions_separate():
    observation = _observation()
    from app.modules.l1.facts import (
        planning_observation_to_l1_fact,
        planning_observation_to_location_mentions,
    )

    fact = planning_observation_to_l1_fact(
        observation,
        dimension_key="location",
        source_snapshot_ref="sha256:source-1",
    )
    mentions = planning_observation_to_location_mentions(
        observation,
        dimension_key="location",
        source_report_ref="dimension:location",
    )

    assert fact is not None
    assert fact.fact_kind == "spatial_observation"
    assert fact.source_span_refs == ["segment:segment-1"]
    assert mentions[0].normalized_name == "道路 R1"
    assert mentions[0].evidence_artifact_refs == []


def test_merge_creates_blocking_conflict_group_and_gate_does_not_pass():
    facts = [
        make_l1_fact(
            statement="金田村人口=10",
            fact_kind="document_observation",
            dimension_key="population",
            subject_scope="金田村",
            semantic_type="population",
            attributes={"metric": "population"},
            value=value,
            unit="person",
            counting_basis="census",
            source_refs=[f"document:{index}"],
        )
        for index, value in enumerate((10, 20), start=1)
    ]
    snapshot = merge_l1_snapshots([
        L1ObservationSnapshot(
            fact_records=[fact for fact in facts if fact is not None],
            facts=[fact.statement for fact in facts if fact is not None],
            sources=[],
        )
    ], run_id="run-1")

    assert len(snapshot.conflict_groups) == 1
    assert snapshot.conflict_groups[0].status == "REQUIRES_EVIDENCE"
    gate = evaluate_l1_gate(snapshot)
    assert gate.passed is False
    assert gate.feedback_route == "L1"


def test_source_span_failure_blocks_gate_even_when_display_facts_exist():
    from app.contracts.l1.validation_contracts import SourceSpanValidationReport

    snapshot = L1ObservationSnapshot(
        facts=["道路 R1"],
        sources=[],
        source_span_validation_reports=[SourceSpanValidationReport(
            validation_ref="validation-1",
            fact_ref="observation-1",
            status="segment_missing",
            validation_errors=("unknown source segment",),
        )],
    )
    gate = evaluate_l1_gate(snapshot)
    assert gate.passed is False
    assert gate.feedback_route == "EXPLORE"
