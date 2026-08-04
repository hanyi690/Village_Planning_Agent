"""L2_STRATEGY profile tests - report -> L2StrategyFragment."""
from __future__ import annotations

from app.modules.parsing.compiler.profiles.l2_strategy import compile_l2_strategy
from app.modules.schema.contracts.l2_contracts import L2StrategyFragment
from app.modules.schema.contracts.parsing_contracts import CompilationProfile


def _compile(dim, content):
    return compile_l2_strategy(dimension_key=dim, content=content, instruction=content, run_id="r1")


def test_planning_strategies_goals_and_strategies():
    report = (
        "## 规划策略分析\n"
        "【核心指标目标】\n"
        "- 耕地保有量：120公顷（约束性）\n"
        "- 常住人口规模：2000人（预期性）\n"
        "【人口规模预测】\n"
        "- 规划期末人口预测：2000人\n"
        "【用地规模预测】\n"
        "- 新增建设用地：10公顷\n"
        "【规划策略】\n"
        "- 生态优先——生态保护网格化（针对生态破碎，划分网格，覆盖全域）\n"
        "- 产业振兴——主导产业特色化（针对产业单一，发展休闲农业，带动200人就业）\n"
        "- 设施完善——基础设施标准化（针对设施不足，完善路网，覆盖12个自然村）\n"
        "策略逻辑关系：生态保护是产业发展的基础。\n"
    )
    frag = _compile("planning_strategies", report)
    assert isinstance(frag, L2StrategyFragment)
    assert any("耕地保有量" in g for g in frag.goals)
    assert any("人口" in g for g in frag.goals)
    assert any("用地" in g for g in frag.goals)
    assert any("生态" in s for s in frag.strategies)
    assert any("产业" in s for s in frag.strategies)
    assert any("生态优先" in s for s in frag.strategies)
    assert any("优先" in p for p in frag.priorities)
    assert frag.trace is not None and frag.trace.profile == CompilationProfile.L2_STRATEGY


def test_planning_strategies_uses_bullet_lines_only_for_strategies():
    report = (
        "## 规划策略分析\n"
        "【规划策略】\n"
        "- 生态优先——生态保护网格化\n"
        "非子弹行的散文不应进入 strategies。\n"
    )
    frag = _compile("planning_strategies", report)
    assert len(frag.strategies) == 1
    assert "生态优先" in frag.strategies[0]


def test_planning_positioning_sets_spatial_structure():
    report = (
        "## 规划定位分析\n"
        "村庄分类：集聚提升类\n"
        "XX生态文化村\n"
        "上位规划衔接：符合乡镇总规\n"
        "【形象定位】\n"
        "田园山水·康养福地\n"
    )
    frag = _compile("planning_positioning", report)
    assert "集聚提升类" in frag.spatial_structure


def test_planning_positioning_falls_back_to_first_line():
    report = "## 规划定位分析\nXX生态文化村\n上位规划衔接：符合乡镇总规\n"
    frag = _compile("planning_positioning", report)
    assert "XX生态文化村" in frag.spatial_structure


def test_development_goals_populates_goals():
    report = "## 发展目标分析\n总体目标：XX市特色综合开发示范村"
    frag = _compile("development_goals", report)
    assert any("示范村" in g for g in frag.goals)


def test_resource_endowment_no_crash_and_empty_strategy_fields():
    report = (
        "## 资源禀赋分析\n"
        "资源类型：耕地（规模120公顷）\n"
        "资源类型：林地（规模50公顷）\n"
        "资源类型：文化资源（数量3处）\n"
    )
    frag = _compile("resource_endowment", report)
    assert isinstance(frag, L2StrategyFragment)
    assert frag.goals == []
    assert frag.strategies == []
    assert frag.priorities == []
    assert frag.spatial_structure == ""


def test_evidence_gap_detection():
    report = (
        "## 规划策略分析\n"
        "【规划策略】\n"
        "- 产业振兴——主导产业特色化\n"
        "人口数据缺失，需进一步调查。\n"
    )
    frag = _compile("planning_strategies", report)
    assert len(frag.evidence_gaps) > 0
    assert frag.evidence_gaps[0].dimension == "planning_strategies"
    assert frag.evidence_gaps[0].gap_id.startswith("planning_strategies-")


def test_conflict_detection():
    report = (
        "## 规划策略分析\n"
        "【规划策略】\n"
        "- 生态优先——生态保护网格化\n"
        "- 产业振兴——主导产业特色化\n"
        "生态保护与产业开发存在矛盾，制约发展平衡。\n"
    )
    frag = _compile("planning_strategies", report)
    assert len(frag.conflicts) > 0
    assert frag.conflicts[0].between == ["planning_strategies"]
    assert frag.conflicts[0].severity == "warning"


def test_strategy_issue_on_contradiction():
    report = (
        "## 规划策略分析\n"
        "【核心指标目标】\n"
        "- 新增建设用地：10公顷\n"
        "- 耕地保有量：120公顷（约束性）\n"
        "【规划策略】\n"
        "- 生态优先——生态保护网格化\n"
        "- 开发优先——集中建设\n"
    )
    frag = _compile("planning_strategies", report)
    assert len(frag.strategy_issues) > 0
    assert frag.strategy_issues[0].code == "strategy_contradiction"
    assert frag.strategy_issues[0].stage == "l2"
