"""Offline coverage for the MiniMax L1 text compatibility path."""

from types import SimpleNamespace

import pytest

from app.domain.assessment.analysis_node import _parse_l1_markdown_fallback


def _retry_exception_with_content(content: str):
    from instructor.core import InstructorRetryException

    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
            )
        ]
    )
    return InstructorRetryException(
        "No tool calls or function call found in response (mode: TOOLS)",
        last_completion=completion,
        n_attempts=1,
        total_usage=0,
    )


def test_l1_markdown_fallback_keeps_narrative_and_parses_explicit_observation_table():
    result = _parse_l1_markdown_fallback(
        """<think>reasoning is not report content</think>
# 金田村上位规划分析与生态保护约束现状

【事实】金田村存在永久基本农田保护地块。

## observations
| entity_type | name | location | relation | description | scale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 地物 | 永久基本农田 | 金田村 | 分布于村域 | 现状保护约束 | 96个地块 |
"""
    )

    assert result is not None
    assert "## observations" not in result.report_body
    assert "永久基本农田" in result.report_body
    assert len(result.observations) == 1
    assert result.observations[0].location == "金田村"


def test_l1_markdown_fallback_without_table_keeps_report_and_has_no_invented_observations():
    result = _parse_l1_markdown_fallback(
        """# 交通现状

【事实】村内道路以现状村道为主，部分路段缺少照明设施。

【问题】道路设施仍需结合实际数据进一步核实。
"""
    )

    assert result is not None
    assert result.observations == []
    assert "交通现状" in result.report_body


def test_l1_markdown_fallback_rejects_empty_or_protocol_error_content():
    assert _parse_l1_markdown_fallback("<think>only reasoning</think>") is None
    assert _parse_l1_markdown_fallback("<failed_attempts>provider error</failed_attempts>") is None
    assert _parse_l1_markdown_fallback("InstructorRetryException: no tool call") is None


def test_l1_text_fallback_rejects_pure_think_and_reraises_original():
    from instructor.core import InstructorRetryException

    from app.domain.assessment.analysis_node import _l1_text_fallback_from_retry

    exc = _retry_exception_with_content("<think>only reasoning</think>")

    with pytest.raises(InstructorRetryException) as raised:
        _l1_text_fallback_from_retry(exc, "dim-l1")

    assert raised.value is exc


def test_l1_text_fallback_does_not_log_provider_error_content(monkeypatch):
    from app.domain.assessment.analysis_node import _l1_text_fallback_from_retry

    content = "Internal Server Error: provider diagnostic should stay private"
    exc = _retry_exception_with_content(content)
    warning_args: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        "app.domain.assessment.analysis_node.logger.warning",
        lambda *args, **_kwargs: warning_args.append(args),
    )

    with pytest.raises(type(exc)):
        _l1_text_fallback_from_retry(exc, "dim-l1")

    assert content not in " ".join(str(item) for args in warning_args for item in args)
