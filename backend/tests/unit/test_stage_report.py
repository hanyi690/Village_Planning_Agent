def test_render_stage_report_markdown_contains_stage_headings():
    from app.services.stage_report import render_stage_report_markdown

    reports = [
        {"stage": "KG_PREBUILD", "step_name": "kg_prebuild", "timestamp": "2026-08-03T00:00:00",
         "inputs": {"session_id": "sess-1"},
         "outputs": {"triple_count": 30836}, "diagnostics": {"sfTouches": 100}, "artifacts": []},
        {"stage": "EXPLORE", "step_name": "explore_bridge", "timestamp": "2026-08-03T00:00:01",
         "inputs": {"reports_count": 24},
         "outputs": {"instructions": 0}, "diagnostics": {"total": 66, "resolved": 0}, "artifacts": []},
    ]
    md = render_stage_report_markdown(reports, {"session_id": "sess-1", "feasible": False})
    assert "## KG_PREBUILD / kg_prebuild" in md
    assert "## EXPLORE / explore_bridge" in md
    assert "triple_count" in md and "30836" in md
    assert "resolved" in md and "0" in md
    assert "### 输入" in md
    assert "session_id" in md and "reports_count" in md
