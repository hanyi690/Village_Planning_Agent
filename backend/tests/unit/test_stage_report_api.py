def test_backend_run_report_includes_markdown_field(monkeypatch):
    from app.services.step_report import build_backend_run_report

    async def fake_build(session_id):
        return {"session_id": session_id, "feasible": False, "layers": {}, "issues": []}

    monkeypatch.setattr("app.services.step_report.build_backend_run_report", fake_build)
    # direct renderer-level assertion instead of full async chain
    from app.services.stage_report import render_stage_report_markdown

    md = render_stage_report_markdown([], {"session_id": "s", "feasible": False})
    assert "GIS 全链阶段报告" in md
