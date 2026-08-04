"""L3_PLANNING profile tests - report -> L3ProgramFragment."""
from __future__ import annotations

from app.modules.parsing.compiler.core import compile_dimension_report
from app.modules.parsing.compiler.profiles.l3_planning import compile_l3_planning
from app.modules.schema.contracts.l3_contracts import L3ProgramFragment
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


def test_compile_l3_planning_from_instruction_table():
    report = _report_with_instruction_table()
    frag = compile_l3_planning(
        dimension_key="industry",
        content=report,
        instruction=report,
        run_id="r1",
    )
    assert isinstance(frag, L3ProgramFragment)
    assert len(frag.interventions) >= 2
    names = [i.name for i in frag.interventions]
    assert "休闲农业园" in names
    assert "游客服务中心" in names
    cats = {i.category for i in frag.interventions}
    assert "project" in cats
    assert "facility" in cats
    assert frag.trace is not None and frag.trace.profile == CompilationProfile.L3_PLANNING


def test_compile_l3_planning_evidence_gaps():
    report = (
        "## 土地利用规划\n"
        "规划期末建设用地规模预测。\n"
        "人口数据缺失，需进一步调查。\n"
    )
    frag = compile_l3_planning(
        dimension_key="land_use_planning",
        content=report,
        instruction=report,
    )
    assert len(frag.evidence_gaps) > 0
    assert frag.evidence_gaps[0].dimension == "land_use_planning"
    assert frag.evidence_gaps[0].gap_id.startswith("land_use_planning-")


def test_compile_l3_planning_omissions():
    report = (
        "## 防震减灾规划\n"
        "应急避难场所规划。\n"
        "消防通道布局未规划。\n"
    )
    frag = compile_l3_planning(
        dimension_key="disaster_prevention",
        content=report,
        instruction=report,
    )
    assert len(frag.omissions) > 0
    assert any("消防" in o for o in frag.omissions)


def test_compile_l3_planning_duplicate_intervention_issue():
    report = (
        "## 产业规划\n"
        "【INSTRUCTION】\n"
        "| 类型 | 名称 | 位置 | 描述 | 规模 |\n"
        "|------|------|------|------|------|\n"
        "| 项目 | 休闲农业园 | 村东侧 | 描述 | 30公顷 |\n"
        "| 项目 | 休闲农业园 | 村西侧 | 描述2 | 20公顷 |\n"
    )
    frag = compile_l3_planning(
        dimension_key="industry",
        content=report,
        instruction=report,
    )
    assert any(i.code == "program_contradiction" for i in frag.program_issues)


def test_l3_planning_dispatch_returns_fragment():
    frag = compile_dimension_report(
        CompilationProfile.L3_PLANNING,
        dimension_key="industry",
        content=(
            "【INSTRUCTION】\n"
            "| 类型 | 名称 | 位置 | 描述 | 规模 |\n"
            "|---|---|---|---|---|\n"
            "| 项目 | 项目A | 东 | 描述 | 10公顷 |\n"
        ),
        instruction="",
    )
    assert isinstance(frag, L3ProgramFragment)
