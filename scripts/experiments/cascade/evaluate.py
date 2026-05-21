"""
Cascade Revision Metrics - 级联修订效果评估

只评估修订的维度，生成以下指标：
1. 反馈响应度 (Feedback Response): 目标维度是否正确响应反馈
2. 语义对齐度 (Semantic Alignment): 下游维度是否与目标维度语义对齐
3. 内容变化度 (Content Change): 修订幅度
4. 关键词覆盖率 (Keyword Coverage): 期望关键词出现率
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RevisionMetrics:
    """单个维度的修订指标"""
    dimension_key: str
    wave: int
    feedback_response: float = 0.0  # 目标维度专用
    semantic_alignment: float = 0.0  # 下游维度专用
    content_change: float = 0.0
    keyword_coverage: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CascadeReport:
    """级联修订评估报告"""
    scenario: str
    target_dimension: str
    feedback: str
    impact_tree: Dict[int, List[str]]
    metrics: Dict[str, RevisionMetrics]
    summary: Dict[str, float]


# 场景关键词配置
SCENARIO_KEYWORDS = {
    "scenario1": {
        "target": "planning_positioning",
        "feedback": '金田村根据《平远县国土空间总体规划（2021—2035年）》被划定为"集聚提升类村庄"，而非"特色保护类村庄"。',
        "positive": ["集聚提升类", "南药", "林下经济", "生态旅游", "村集体年收入", "南药产业产值"],
        "negative": ["特色保护类", "闽粤赣边生态保育村", "客家古驿文化传承村"],
        "output_dir": "驳回规划定位-修正村庄分类",
    },
    "scenario2": {
        "target": "development_goals",
        "feedback": "规划指标修正：人口规模1681人、耕地保有量127.18公顷、基本农田81.43公顷、生态红线367.68公顷、建设用地17.66公顷",
        # 正向关键词：期望出现的数据指标（注意空格）
        "positive": ["1681 人", "127.18 公顷", "81.43 公顷", "367.68 公顷", "17.66 公顷", "105.05 ㎡"],
        # 负向关键词：期望移除的旧数据（注意空格）
        "negative": ["1454 人", "85.2 公顷", "78.83 公顷", "362.02 公顷", "30.5 公顷", "555 ㎡"],
        "output_dir": "驳回发展目标-修正规划指标",
    },
    "scenario3": {
        "target": "industry",
        "feedback": "产业规划方向错误，金田村应重点发展南药产业而非林下经济+文旅。",
        # 正向关键词：期望出现的南药产业相关内容
        "positive": ["南药种植", "南药加工", "南药产业", "南药产业年产值", "产业链", "岭南南药"],
        # 负向关键词：期望移除或减少的文旅相关内容
        "negative": ["文化旅游", "民宿集群", "船灯舞演艺", "林下经济+文旅"],
        "output_dir": "驳回产业规划-修正产业方向",
    },
}


def extract_content_from_md(md_path: Path, dim_key: str, is_target: bool = False) -> tuple[str, str]:
    """从 revision_comparison.md 提取维度的原始和修订内容"""
    content = md_path.read_text(encoding="utf-8")

    # 目标维度特殊处理（标题格式不同）
    if is_target:
        pattern = rf"## 1\. 目标维度: [^\n]+ \(`{dim_key}`\)"
        # 目标维度使用 ### 原始报告 格式
        orig_pattern = r"### 原始报告\s*\n\n```markdown\n(.*?)```"
        rev_pattern = r"### 修订后报告\s*\n\n```markdown\n(.*?)```"
    else:
        # 下游维度使用 **原始报告**: 格式
        pattern = rf"#### \d+\. [^\n]+ \(`{dim_key}`\)"
        orig_pattern = r"\*\*原始报告\*\*:\s*\n\n```markdown\n(.*?)```"
        rev_pattern = r"\*\*修订后报告\*\*:\s*\n\n```markdown\n(.*?)```"

    match = re.search(pattern, content)
    if not match:
        return "", ""

    start_pos = match.end()

    # 提取原始报告（使用 DOTALL 模式匹配多行）
    orig_match = re.search(orig_pattern, content[start_pos:start_pos + 5000], re.DOTALL)
    orig_content = orig_match.group(1) if orig_match else ""

    # 提取修订后报告
    rev_match = re.search(rev_pattern, content[start_pos:start_pos + 10000], re.DOTALL)
    rev_content = rev_match.group(1) if rev_match else ""

    return orig_content.strip(), rev_content.strip()


def calculate_content_change(old: str, new: str) -> float:
    """计算内容变化度"""
    if not old and not new:
        return 0.0
    if not old:
        return 1.0
    if not new:
        return 0.0

    from difflib import SequenceMatcher
    similarity = SequenceMatcher(None, old, new).ratio()
    return 1 - similarity


def check_keyword_coverage(content: str, positive: List[str], negative: List[str]) -> float:
    """检查关键词覆盖率"""
    if not positive:
        return 1.0

    positive_found = sum(1 for kw in positive if kw in content)
    positive_coverage = positive_found / len(positive)

    # 检查负向关键词是否清除
    if negative:
        negative_found = sum(1 for kw in negative if kw in content)
        negative_penalty = negative_found / len(negative) * 0.3
        positive_coverage -= negative_penalty

    return max(0, positive_coverage)


async def evaluate_cascade_revision(
    scenario: str,
    output_dir: Path,
) -> CascadeReport:
    """评估级联修订效果"""

    from scripts.experiments.cascade.checker import ConsistencyChecker
    from scripts.experiments.framework.metrics import MetricsSuite

    # 加载场景配置
    kw_config = SCENARIO_KEYWORDS.get(scenario, SCENARIO_KEYWORDS["scenario1"])
    target_dim = kw_config["target"]
    positive_kw = kw_config["positive"]
    negative_kw = kw_config["negative"]
    feedback = kw_config["feedback"]

    # 加载修订对比报告
    comparison_path = output_dir / "revision_comparison.md"
    if not comparison_path.exists():
        raise FileNotFoundError(f"修订对比报告不存在: {comparison_path}")

    # 从报告中提取影响树
    content = comparison_path.read_text(encoding="utf-8")
    impact_tree = extract_impact_tree(content)

    # 初始化评估器
    checker = ConsistencyChecker(auto_calibrate=False)
    metrics_suite = MetricsSuite()

    metrics: Dict[str, RevisionMetrics] = {}

    # 评估目标维度
    orig_target, rev_target = extract_content_from_md(comparison_path, target_dim, is_target=True)
    if rev_target:
        feedback_response = checker.check_feedback_response(
            orig_target, rev_target, feedback,
            {"positive": positive_kw, "negative": negative_kw}
        )
        content_change = calculate_content_change(orig_target, rev_target)
        keyword_coverage = check_keyword_coverage(rev_target, positive_kw, negative_kw)

        metrics[target_dim] = RevisionMetrics(
            dimension_key=target_dim,
            wave=0,
            feedback_response=feedback_response,
            content_change=content_change,
            keyword_coverage=keyword_coverage,
            details={
                "positive_found": [kw for kw in positive_kw if kw in rev_target],
                "negative_found": [kw for kw in negative_kw if kw in rev_target],
            }
        )

    # 评估下游维度
    for wave, dims in impact_tree.items():
        for dim in dims:
            orig_dim, rev_dim = extract_content_from_md(comparison_path, dim)
            if not rev_dim:
                continue

            # 语义对齐度（与目标维度）
            alignment_result = checker.check_semantic_alignment(
                rev_target, rev_dim, dim
            )

            # 内容变化度
            content_change = calculate_content_change(orig_dim, rev_dim)

            # 关键词覆盖率（检查是否包含目标维度的关键词）
            kw_coverage = check_keyword_coverage(rev_dim, positive_kw, [])

            metrics[dim] = RevisionMetrics(
                dimension_key=dim,
                wave=wave,
                semantic_alignment=alignment_result.score,
                content_change=content_change,
                keyword_coverage=kw_coverage,
                details={
                    "embedding_similarity": alignment_result.embedding_similarity,
                    "keyword_alignment": alignment_result.keyword_coverage,
                }
            )

    # 计算汇总指标
    summary = calculate_summary(metrics, impact_tree)

    return CascadeReport(
        scenario=scenario,
        target_dimension=target_dim,
        feedback=feedback,
        impact_tree=impact_tree,
        metrics=metrics,
        summary=summary,
    )


def extract_impact_tree(content: str) -> Dict[int, List[str]]:
    """从报告提取影响树"""
    impact_tree: Dict[int, List[str]] = {}

    # 查找 Wave 标题
    wave_pattern = r"### Wave (\d+) \(下游影响\)"
    for match in re.finditer(wave_pattern, content):
        wave = int(match.group(1))
        # 提取该 Wave 下的维度
        section_start = match.end()
        section_end = content.find("### Wave", section_start)
        if section_end == -1:
            section_end = content.find("## 修订统计", section_start)
        section = content[section_start:section_end]

        # 提取维度 key
        dim_pattern = r"#### \d+\. [^\n]+ \(`([^`]+)`\)"
        dims = re.findall(dim_pattern, section)
        impact_tree[wave] = dims

    return impact_tree


def calculate_summary(
    metrics: Dict[str, RevisionMetrics],
    impact_tree: Dict[int, List[str]]
) -> Dict[str, float]:
    """计算汇总指标"""

    # 目标维度指标
    target_metrics = [m for m in metrics.values() if m.wave == 0]
    target_feedback_response = sum(m.feedback_response for m in target_metrics) / len(target_metrics) if target_metrics else 0

    # 下游维度指标
    downstream_metrics = [m for m in metrics.values() if m.wave > 0]
    avg_alignment = sum(m.semantic_alignment for m in downstream_metrics) / len(downstream_metrics) if downstream_metrics else 0
    avg_change = sum(m.content_change for m in metrics.values()) / len(metrics) if metrics else 0
    avg_kw_coverage = sum(m.keyword_coverage for m in metrics.values()) / len(metrics) if metrics else 0

    # 按 Wave 统计
    wave_stats = {}
    for wave, dims in impact_tree.items():
        wave_metrics = [metrics.get(d) for d in dims if metrics.get(d)]
        if wave_metrics:
            wave_stats[wave] = {
                "avg_alignment": sum(m.semantic_alignment for m in wave_metrics) / len(wave_metrics),
                "avg_change": sum(m.content_change for m in wave_metrics) / len(wave_metrics),
                "count": len(wave_metrics),
            }

    return {
        "target_feedback_response": target_feedback_response,
        "avg_semantic_alignment": avg_alignment,
        "avg_content_change": avg_change,
        "avg_keyword_coverage": avg_kw_coverage,
        "total_revised": len(metrics),
        "wave_stats": wave_stats,
    }


def format_report(report: CascadeReport) -> str:
    """格式化报告为 Markdown"""

    lines = [
        f"# 级联修订效果评估报告",
        f"",
        f"**场景**: {report.scenario}",
        f"**目标维度**: {report.target_dimension}",
        f"**修订维度数**: {len(report.metrics)}",
        f"",
        f"## 汇总指标",
        f"",
        f"| 指标 | 值 | 说明 |",
        f"|------|-----|------|",
        f"| 反馈响应度 | {report.summary['target_feedback_response']:.2%} | 目标维度是否正确响应反馈 |",
        f"| 语义对齐度 | {report.summary['avg_semantic_alignment']:.2%} | 下游维度与目标维度的语义一致性 |",
        f"| 内容变化度 | {report.summary['avg_content_change']:.2%} | 修订幅度 |",
        f"| 关键词覆盖率 | {report.summary['avg_keyword_coverage']:.2%} | 期望关键词出现率 |",
        f"",
        f"## Wave 统计",
        f"",
    ]

    wave_stats = report.summary.get("wave_stats", {})
    if wave_stats:
        lines.extend([
            f"| Wave | 维度数 | 语义对齐度 | 内容变化度 |",
            f"|------|--------|------------|------------|",
        ])
        for wave in sorted(wave_stats.keys()):
            stats = wave_stats[wave]
            lines.append(
                f"| {wave} | {stats['count']} | {stats['avg_alignment']:.2%} | {stats['avg_change']:.2%} |"
            )

    lines.extend([
        f"",
        f"## 各维度详细指标",
        f"",
        f"| 维度 | Wave | 反馈响应 | 语义对齐 | 内容变化 | 关键词覆盖 |",
        f"|------|------|----------|----------|----------|------------|",
    ])

    for dim_key, m in sorted(report.metrics.items(), key=lambda x: x[1].wave):
        feedback_str = f"{m.feedback_response:.2%}" if m.wave == 0 else "-"
        lines.append(
            f"| {dim_key} | {m.wave} | {feedback_str} | {m.semantic_alignment:.2%} | {m.content_change:.2%} | {m.keyword_coverage:.2%} |"
        )

    return "\n".join(lines)


async def main():
    """主函数"""
    import sys

    scenario = sys.argv[1] if len(sys.argv) > 1 else "scenario1"

    # 加载场景配置
    kw_config = SCENARIO_KEYWORDS.get(scenario, SCENARIO_KEYWORDS["scenario1"])

    # 输出目录（根据场景选择）
    scenario_num = scenario.replace("scenario", "")
    output_dir = Path(f"output/experiments/cascade_scenario{scenario_num}")
    run_dir = output_dir / kw_config["output_dir"] / "run0"

    report = await evaluate_cascade_revision(scenario, run_dir)

    # 输出报告
    md_report = format_report(report)
    report_path = run_dir / "cascade_metrics.md"
    report_path.write_text(md_report, encoding="utf-8")

    # 输出 JSON
    json_path = run_dir / "cascade_metrics.json"
    json_data = {
        "scenario": report.scenario,
        "target_dimension": report.target_dimension,
        "impact_tree": report.impact_tree,
        "metrics": {
            k: {
                "wave": v.wave,
                "feedback_response": v.feedback_response,
                "semantic_alignment": v.semantic_alignment,
                "content_change": v.content_change,
                "keyword_coverage": v.keyword_coverage,
                "details": v.details,
            }
            for k, v in report.metrics.items()
        },
        "summary": report.summary,
    }
    json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(md_report)
    print(f"\n报告已保存至: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())