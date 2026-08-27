import pytest


def test_direct_dependency_keys_preserve_edge_order_and_deduplicate():
    from types import SimpleNamespace
    from app.infrastructure.llm.dependency_context import direct_dependency_keys

    config = SimpleNamespace(depends_on=["a", "b"], layer_depends_on=["b", "c"], phase_depends_on=["a", "d"])
    assert direct_dependency_keys(config) == ("a", "b", "c", "d")


@pytest.mark.asyncio
async def test_context_renders_metadata_and_never_body(monkeypatch):
    from types import SimpleNamespace
    from app.infrastructure.llm.dependency_context import load_dependency_context

    class Store:
        async def get_latest_dependency_records(self, session_id, keys):
            assert keys == ("a", "b")
            return {"a": {"layer": 1, "version": 2, "report_id": "r1", "summary": "pending", "instruction": '{"x":1}', "content": "SECRET BODY"}}

    monkeypatch.setattr("app.infrastructure.llm.dependency_context.ReportStore.get_instance", lambda: Store())
    context = await load_dependency_context("s", "consumer", SimpleNamespace(depends_on=["a"], layer_depends_on=["b"]), 2)
    rendered = context.render_for_prompt()
    assert "SECRET BODY" not in rendered
    assert '"x":1' in rendered
    assert "| dimension_key | layer | version | report_id |" in rendered
    assert context.missing_keys == ("b",)


def test_decision_projection_preserves_semantics_without_raw_payload():
    from app.infrastructure.llm.dependency_context import _decision_projection

    projected = _decision_projection({
        "strategies": [{"statement": "strategy-%s" % index} for index in range(20)],
        "evidence_gaps": [{"description": "gap"}],
        "report_body": "raw report body",
        "retrieval_trace": {"query": "raw trace"},
    })

    assert len(projected["strategies"]) == 20
    assert projected["strategies"][-1]["statement"] == "strategy-19"
    assert "report_body" not in projected
    assert "retrieval_trace" not in projected


def test_decision_projection_does_not_truncate_abstract_statement():
    from app.infrastructure.llm.dependency_context import _decision_projection

    statement = "抽象决策内容。" * 400
    projected = _decision_projection({
        "objectives": [{"objective_id": "o-1", "statement": statement}],
    })

    assert projected["objectives"][0]["statement"] == statement
