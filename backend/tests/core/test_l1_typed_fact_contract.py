import json
from types import SimpleNamespace

from app.contracts.domain.l1_contracts import L1Fact
from app.data.ingestion.compiler.profiles.l1_observation import compile_l1_observation
from app.domain.assessment.aggregate import merge_l1_snapshots
from app.evidence.retrieval.retrievers.l1_retriever import retrieve_from_l1_context


def test_l1_snapshot_emits_stable_typed_records_with_source_span() -> None:
    instruction = json.dumps(
        {
            "observations": [
                {
                    "fact_type": "spatial_entity",
                    "entity_type": "现状设施",
                    "name": "祠堂",
                    "locator": {
                        "place_names": ["社前村"],
                        "relation": "位于社前村",
                    },
                    "description": "客家祠堂",
                    "scale": "3处",
                }
            ]
        },
        ensure_ascii=False,
    )
    first = compile_l1_observation(
        dimension_key="socio_economic",
        content="# 社会经济\n社前村有客家祠堂。",
        instruction=instruction,
        report_id="report-current",
    )
    second = compile_l1_observation(
        dimension_key="socio_economic",
        content="# 社会经济\n社前村有客家祠堂。",
        instruction=instruction,
        report_id="report-current",
    )

    assert first.fact_records
    assert [item.fact_id for item in first.fact_records] == [
        item.fact_id for item in second.fact_records
    ]
    facility = next(
        item
        for item in first.fact_records
        if item.semantic_type == "facility"
    )
    assert isinstance(facility, L1Fact)
    assert facility.subject_scope == "祠堂"
    assert facility.source_refs == ["report-current"]
    assert "社前村" in facility.statement
    assert facility.source_span


def test_l1_merge_deduplicates_records_by_fact_id_not_statement() -> None:
    first = compile_l1_observation(
        dimension_key="traffic",
        content="# 道路\n道路较窄。",
        instruction="",
        report_id="report-traffic",
    )
    second = first.model_copy(deep=True)
    merged = merge_l1_snapshots([first, second], run_id="run-1")

    assert len(merged.fact_records) == len(first.fact_records)
    assert len({item.fact_id for item in merged.fact_records}) == len(
        merged.fact_records
    )


def test_l1_retriever_projects_typed_records_with_fact_identity() -> None:
    record = L1Fact(
        fact_id="l1:fact:hall",
        statement="L1空间事实：祠堂（角色=facility），空间提示=社前村",
        confidence=0.94,
        fact_kind="spatial_observation",
        dimension_key="socio_economic",
        subject_scope="祠堂",
        semantic_type="facility",
        attributes={"role": "facility", "normalized_name": "祠堂"},
        source_refs=["report-current#socio_economic"],
        source_span="社前村现状设施包括祠堂",
    )
    facts, sources = retrieve_from_l1_context(
        SimpleNamespace(
            l1_snapshot_ref="l1-snapshot-1",
            l1_fact_records=[record],
            location_facts=[],
        ),
        query="社前村祠堂",
        dimension_key="socio_economic",
    )

    assert len(facts) == 1
    assert facts[0].fact_type == "l1_fact"
    assert facts[0].fields["fact_id"] == "l1:fact:hall"
    assert facts[0].source_refs == ["report-current#socio_economic"]
    assert sources[0].reference == "l1:fact:hall"
