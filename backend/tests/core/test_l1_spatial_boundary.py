"""L1 report prose and L1 spatial facts have separate machine boundaries."""

from types import SimpleNamespace

from app.data.ingestion.compiler.profiles.l1_observation import compile_l1_observation
from app.evidence.retrieval.retrievers.l1_retriever import retrieve_from_l1_context
from app.contracts.domain.l1_contracts import L1Fact


def test_report_prose_is_not_promoted_to_l1_fact_records() -> None:
    snapshot = compile_l1_observation(
        dimension_key="socio_economic",
        content="# 社会经济\n人口与产业分析正文，不是空间定位事实。",
        instruction="",
        report_id="report-socio-economic",
    )

    assert snapshot.facts
    assert snapshot.fact_records == []


def test_l1_retriever_includes_dimension_local_non_spatial_typed_records() -> None:
    report_fact = L1Fact(
        fact_id="l1:fact:report-only",
        statement="产业结构以农业为主",
        fact_kind="document_observation",
        dimension_key="socio_economic",
        semantic_type="observation",
        source_refs=["report:socio-economic"],
    )
    spatial_fact = L1Fact(
        fact_id="l1:fact:spatial",
        statement="L1空间事实：祠堂（角色=facility），空间提示=社前村",
        fact_kind="spatial_observation",
        dimension_key="socio_economic",
        semantic_type="facility",
        attributes={"normalized_name": "祠堂", "role": "facility"},
        source_refs=["report:socio-economic"],
    )

    facts, _sources = retrieve_from_l1_context(
        SimpleNamespace(
            l1_snapshot_ref="l1:snapshot",
            l1_fact_records=[report_fact, spatial_fact],
        ),
        query="农业",
    )

    assert [fact.fields["fact_id"] for fact in facts] == ["l1:fact:report-only"]
    assert facts[0].evidence_role == "planning_background"
    assert facts[0].planning_use == "context"


def test_l1_retriever_keeps_non_spatial_facts_dimension_local() -> None:
    report_fact = L1Fact(
        fact_id="l1:fact:report-only",
        statement="产业结构以农业为主",
        fact_kind="document_observation",
        dimension_key="socio_economic",
        semantic_type="observation",
        source_refs=["report:socio-economic"],
    )

    facts, _sources = retrieve_from_l1_context(
        SimpleNamespace(
            l1_snapshot_ref="l1:snapshot",
            l1_fact_records=[report_fact],
        ),
        query="农业",
        dimension_key="traffic",
    )

    assert facts == []


def test_l1_retriever_does_not_project_noncanonical_fact_identity() -> None:
    legacy = L1Fact(
        fact_id="l1:legacy:road",
        statement="历史事实身份不应进入可引用证据",
        fact_kind="spatial_observation",
        dimension_key="traffic",
        semantic_type="road",
        source_refs=["report:traffic"],
    )

    facts, sources = retrieve_from_l1_context(
        SimpleNamespace(
            l1_snapshot_ref="l1:snapshot",
            l1_fact_records=[legacy],
        ),
        query="历史事实",
    )

    assert facts == []
    assert sources == []
