from app.domain.assessment.analysis_node import _l1_factual_input


def test_l1_factual_input_ignores_legacy_current_status_and_plan_documents() -> None:
    result = _l1_factual_input(
        {
            "village_data": "短会话摘要",
            "current_status": "原始现状报告正文",
            "planning_approach": "未来规划设想",
            "detailed_plan": "规划方案正文",
        }
    )

    assert "短会话摘要" in result
    assert "原始现状报告正文" not in result
    assert "未来规划设想" not in result
    assert "规划方案正文" not in result


def test_l1_factual_input_uses_only_canonical_village_data() -> None:
    result = _l1_factual_input(
        {
            "village_data": "同一份事实",
            "current_status": "同一份事实",
        }
    )

    assert result == "同一份事实"


def test_l1_factual_input_includes_explicit_current_uploads() -> None:
    result = _l1_factual_input({
        "village_data": "会话摘要",
        "upload": "上传的现状报告",
        "task_description": "做规划",
        "constraints": "不得越界",
    })

    assert result == "会话摘要\n\n上传的现状报告"


def test_l1_source_index_reuses_persisted_artifact_on_resume(monkeypatch) -> None:
    from app.contracts.domain.l1_contracts import L1SourceIndex
    from app.domain.assessment.analysis_node import _l1_source_index_for_state

    cached = L1SourceIndex(
        source_documents=["input:village_data"],
        source_digest="sha256:cached",
    )
    monkeypatch.setattr(
        "app.infrastructure.artifacts.runtime.load_artifact",
        lambda *_args, **_kwargs: cached,
    )

    result = _l1_source_index_for_state({"session_id": "resume-session"})

    assert isinstance(result, L1SourceIndex)
    assert result.source_digest == "sha256:cached"
