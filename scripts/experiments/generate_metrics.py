"""
Metrics Generation Script
指标汇总脚本

汇总实验数据，生成最终报告指标。

使用方法:
    python scripts/experiments/generate_metrics.py

输出:
    - analysis/metrics_summary.json
    - analysis/consistency_report.md
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.experiments.config import (
    BASELINE_DIR,
    SCENARIO1_DIR,
    SCENARIO2_DIR,
    ANALYSIS_DIR,
    SCENARIOS,
    ensure_output_dirs,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ============================================
# Metrics Calculation
# ============================================

def calculate_metrics_for_scenario(scenario_name: str) -> Dict[str, Any]:
    """
    Calculate metrics for a scenario.

    Args:
        scenario_name: Scenario name (scenario1 or scenario2)

    Returns:
        Metrics data
    """
    output_dir = ANALYSIS_DIR.parent / f"scenario{'1' if scenario_name == 'scenario1' else '2'}_{'planning_positioning' if scenario_name == 'scenario1' else 'natural_environment'}"

    # Load impact tree
    impact_file = output_dir / "impact_tree.json"
    if impact_file.exists():
        with open(impact_file, "r", encoding="utf-8") as f:
            impact_data = json.load(f)
    else:
        impact_data = {}
        logger.warning(f"[Metrics] Impact tree not found for {scenario_name}")

    # Load wave allocation
    wave_file = output_dir / "wave_allocation.json"
    if wave_file.exists():
        with open(wave_file, "r", encoding="utf-8") as f:
            wave_data = json.load(f)
    else:
        wave_data = {}
        logger.warning(f"[Metrics] Wave allocation not found for {scenario_name}")

    # Load annotation results
    annotation_file = output_dir / "consistency_annotation.json"
    if annotation_file.exists():
        with open(annotation_file, "r", encoding="utf-8") as f:
            annotation_rows = json.load(f)
    else:
        annotation_rows = []
        logger.warning(f"[Metrics] Annotation not found for {scenario_name}")

    # Load SSE events
    sse_file = output_dir / "sse_events.json"
    if sse_file.exists():
        with open(sse_file, "r", encoding="utf-8") as f:
            sse_events = json.load(f)
    else:
        sse_events = []
        logger.warning(f"[Metrics] SSE events not found for {scenario_name}")

    # Calculate metrics
    total_downstream = impact_data.get("total_downstream", 0)
    max_wave = impact_data.get("max_wave", 0)

    # Calculate consistency rate from annotation
    if annotation_rows:
        # Check human judgment field
        judged_rows = [r for r in annotation_rows if r.get("human_judgment")]
        if judged_rows:
            达标_count = len([r for r in judged_rows if r["human_judgment"] == "达标"])
            partial_count = len([r for r in judged_rows if r["human_judgment"] == "部分达标"])
            fail_count = len([r for r in judged_rows if r["human_judgment"] == "未达标"])

            consistency_rate = 达标_count / len(judged_rows) * 100 if judged_rows else 0
        else:
            # Use automatic keyword coverage as fallback
            coverage_rates = []
            for row in annotation_rows:
                coverage_str = row.get("positive_keyword_coverage", "0%")
                try:
                    coverage_rates.append(float(coverage_str.replace("%", "")))
                except ValueError:
                    coverage_rates.append(0)

            avg_coverage = sum(coverage_rates) / len(coverage_rates) if coverage_rates else 0
            consistency_rate = avg_coverage
    else:
        consistency_rate = 0

    # Calculate SSE timing
    if sse_events:
        timestamps = []
        for event in sse_events:
            ts_str = event.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    timestamps.append(ts)
                except ValueError:
                    pass

        if len(timestamps) >= 2:
            duration_seconds = (max(timestamps) - min(timestamps)).total_seconds()
        else:
            duration_seconds = 0
    else:
        duration_seconds = 0

    return {
        "scenario_name": scenario_name,
        "target_dimension": SCENARIOS[scenario_name]["target_dimension"],
        "target_layer": SCENARIOS[scenario_name]["target_layer"],
        "total_downstream_dimensions": total_downstream,
        "total_waves": max_wave,
        "revised_dimension_count": len(annotation_rows),
        "consistency_rate": f"{consistency_rate:.1f}%",
        "sse_event_count": len(sse_events),
        "revision_duration_seconds": duration_seconds,
        "annotation_rows": annotation_rows,
        "impact_tree": impact_data.get("impact_tree", {}),
        "wave_allocation": wave_data.get("wave_allocation", {}),
    }


def calculate_comparison_metrics(scenario1_metrics: Dict, scenario2_metrics: Dict) -> Dict[str, Any]:
    """
    Calculate comparison metrics between scenarios.

    Args:
        scenario1_metrics: Metrics for scenario1
        scenario2_metrics: Metrics for scenario2

    Returns:
        Comparison data
    """
    return {
        "comparison": {
            "scenario1_downstream": scenario1_metrics.get("total_downstream_dimensions", 0),
            "scenario2_downstream": scenario2_metrics.get("total_downstream_dimensions", 0),
            "scenario1_waves": scenario1_metrics.get("total_waves", 0),
            "scenario2_waves": scenario2_metrics.get("total_waves", 0),
            "scenario1_consistency": scenario1_metrics.get("consistency_rate", "0%"),
            "scenario2_consistency": scenario2_metrics.get("consistency_rate", "0%"),
        },
        "analysis": {
            "同层传播复杂度": "scenario1 (Layer 2 → Layer 2/3) 相对简单",
            "跨层传播复杂度": "scenario2 (Layer 1 → Layer 2 → Layer 3) 更复杂",
            "预期差异": "跨层传播可能产生更大的语义漂移风险",
        },
    }


# ============================================
# Report Generation
# ============================================

def generate_metrics_summary(metrics: List[Dict[str, Any]], comparison: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate metrics summary.

    Args:
        metrics: List of scenario metrics
        comparison: Comparison data

    Returns:
        Summary data
    """
    return {
        "generated_at": datetime.now().isoformat(),
        "experiment_name": "级联一致性检验实验",
        "scenarios": metrics,
        "comparison": comparison,
        "data_sources": {
            "baseline_dir": str(BASELINE_DIR),
            "scenario1_dir": str(SCENARIO1_DIR),
            "scenario2_dir": str(SCENARIO2_DIR),
        },
    }


def generate_report_markdown(summary: Dict[str, Any], output_path: Path):
    """
    Generate report in Markdown format.

    Args:
        summary: Summary data
        output_path: Output file path
    """
    lines = []

    lines.append("# 级联一致性检验实验报告")
    lines.append("")
    lines.append(f"生成时间: {summary.get('generated_at', '')}")
    lines.append("")

    # Table header
    lines.append("## 实验数据汇总")
    lines.append("")
    lines.append("| 指标 | 场景一 (规划定位) | 场景二 (自然环境) |")
    lines.append("|------|------------------|------------------|")

    scenarios = summary.get("scenarios", [])
    if len(scenarios) >= 2:
        s1 = scenarios[0]
        s2 = scenarios[1]

        lines.append(f"| 目标层级 | Layer {s1.get('target_layer', 0)} | Layer {s2.get('target_layer', 0)} |")
        lines.append(f"| 目标维度 | {s1.get('target_dimension', '')} | {s2.get('target_dimension', '')} |")
        lines.append(f"| 受影响下游维度数 | {s1.get('total_downstream_dimensions', 0)} | {s2.get('total_downstream_dimensions', 0)} |")
        lines.append(f"| 修复波次数量 | {s1.get('total_waves', 0)} | {s2.get('total_waves', 0)} |")
        lines.append(f"| 语义一致性达标率 | {s1.get('consistency_rate', '0%')} | {s2.get('consistency_rate', '0%')} |")
        lines.append(f"| SSE 事件数量 | {s1.get('sse_event_count', 0)} | {s2.get('sse_event_count', 0)} |")
        lines.append(f"| 修复耗时(秒) | {s1.get('revision_duration_seconds', 0)} | {s2.get('revision_duration_seconds', 0)} |")

    lines.append("")

    # Analysis section
    comparison = summary.get("comparison", {})
    analysis = comparison.get("analysis", {})

    lines.append("## 分析结论")
    lines.append("")
    lines.append(f"- {analysis.get('同层传播复杂度', '')}")
    lines.append(f"- {analysis.get('跨层传播复杂度', '')}")
    lines.append(f"- {analysis.get('预期差异', '')}")
    lines.append("")

    # Impact tree visualization
    lines.append("## 影响树结构")
    lines.append("")

    for scenario in scenarios:
        name = scenario.get("scenario_name", "")
        lines.append(f"### {name}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(scenario.get("impact_tree", {}), indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")

    # Write file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"[Metrics] Saved report: {output_path}")


# ============================================
# Main Entry Point
# ============================================

def generate_all_metrics():
    """
    Generate all metrics and reports.
    """
    ensure_output_dirs()

    logger.info("=" * 60)
    logger.info("[Metrics] Generating metrics summary")
    logger.info("=" * 60)

    # Calculate metrics for each scenario
    metrics = []
    for scenario_name in ["scenario1", "scenario2"]:
        try:
            scenario_metrics = calculate_metrics_for_scenario(scenario_name)
            metrics.append(scenario_metrics)
            logger.info(f"[Metrics] {scenario_name}: {scenario_metrics.get('total_downstream_dimensions', 0)} downstream, {scenario_metrics.get('total_waves', 0)} waves")
        except Exception as e:
            logger.warning(f"[Metrics] Failed to calculate metrics for {scenario_name}: {e}")

    # Calculate comparison
    if len(metrics) >= 2:
        comparison = calculate_comparison_metrics(metrics[0], metrics[1])
    else:
        comparison = {}

    # Generate summary
    summary = generate_metrics_summary(metrics, comparison)

    # Save summary JSON
    with open(ANALYSIS_DIR / "metrics_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    logger.info(f"[Metrics] Saved summary: {ANALYSIS_DIR / 'metrics_summary.json'}")

    # Generate report markdown
    generate_report_markdown(summary, ANALYSIS_DIR / "consistency_report.md")

    logger.info("=" * 60)
    logger.info("[Metrics] Metrics generation completed")
    logger.info("=" * 60)

    # Print summary
    print("\n实验指标汇总:")
    print("-" * 60)
    for m in metrics:
        print(f"场景: {m.get('scenario_name', '')}")
        print(f"  目标维度: {m.get('target_dimension', '')} (Layer {m.get('target_layer', '')})")
        print(f"  受影响下游: {m.get('total_downstream_dimensions', 0)} 个")
        print(f"  修复波次: {m.get('total_waves', 0)} 次")
        print(f"  一致性达标率: {m.get('consistency_rate', '0%')}")
        print("-" * 60)

    return summary


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Generate metrics summary")
    args = parser.parse_args()

    generate_all_metrics()


if __name__ == "__main__":
    main()