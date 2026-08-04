"""REVISION profile tests - deterministic user-revision application.

Wave F Task 5: compile_revision applies ParseRevisionRequest.user_revisions
(dotted-path overrides) to an L3ProgramFragment recompiled from the current
report content. No LLM calls.
"""
from __future__ import annotations

from app.modules.parsing.compiler.profiles.revision import compile_revision
from app.modules.schema.contracts.l3_contracts import L3ProgramFragment
from app.modules.schema.contracts.parse_result_contracts import ParseRevisionRequest
from app.modules.schema.contracts.parsing_contracts import CompilationProfile


def _report_with_instruction_table():
    return (
        "## 产业规划\n"
        "主导产业为休闲农业。\n"
        "\n"
        "【INSTRUCTION】\n"
        "| 类型 | 名称 | 位置 | 描述 | 规模 |\n"
        "|------|------|------|------|------|\n"
        "| 项目 | 休闲农业园 | 村东侧 | 结合耕地集中区 | 30公顷 |\n"
        "| 设施 | 游客服务中心 | 村中心 | 服务游客 | 2000平米 |\n"
    )


def _compile(user_revisions, **kwargs):
    report = kwargs.pop("content", _report_with_instruction_table())
    return compile_revision(
        revision_request=ParseRevisionRequest(user_revisions=user_revisions),
        base_result=None,
        dimension_key=kwargs.pop("dimension_key", "industry"),
        content=report,
        instruction=kwargs.pop("instruction", report),
        run_id="r1",
    )


def test_revision_applies_user_override():
    frag = _compile({"interventions.0.scale": "5ha"})
    assert isinstance(frag, L3ProgramFragment)
    assert frag.trace is not None
    assert frag.trace.profile == CompilationProfile.REVISION
    assert "apply_user_revisions" in frag.trace.steps
    assert frag.interventions[0].scale == "5ha"
    assert frag.interventions[1].scale == "2000平米"


def test_revision_invalid_path_emits_schema_mismatch():
    frag = _compile({"nonexistent.0.scale": "5ha"})
    mismatch = [d for d in frag.diagnostics if d.code == "SCHEMA_MISMATCH"]
    assert len(mismatch) == 1
    assert mismatch[0].severity == "error"
    assert mismatch[0].field_path == "nonexistent.0.scale"


def test_revision_empty_user_revisions_mirrors_baseline():
    frag = _compile({})
    assert isinstance(frag, L3ProgramFragment)
    assert frag.interventions[0].scale == "30公顷"
    assert not any(d.code == "SCHEMA_MISMATCH" for d in frag.diagnostics)
