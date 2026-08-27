from app.infrastructure.llm.context_manager import render_dependency_table, render_table


def test_prompt_context_renderer_is_tabular_and_preserves_structured_cells():
    rendered = render_table(
        ("id", "value"),
        [{"id": "f-1", "value": {"metric": 0, "ok": False}}],
    )
    assert "| id | value |" in rendered
    assert '{"metric":0,"ok":false}' in rendered
    assert "<table" not in rendered


def test_dependency_renderer_has_one_canonical_header():
    rendered = render_dependency_table([{"dimension_key": "traffic", "layer": 1}])
    assert rendered.count("dimension_key") == 1
    assert "| traffic | 1 |" in rendered
