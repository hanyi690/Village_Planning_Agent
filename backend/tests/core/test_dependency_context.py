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
    assert context.missing_keys == ("b",)
