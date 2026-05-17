"""
Cascade Consistency Experiment Module
级联一致性实验模块

实验目标：
验证驳回操作后，下游维度的修订是否保持语义一致性。

模块组成：
- run_baseline: 基线运行（生成28维度报告）
- run_experiment: 实验运行（驳回+级联修订+一致性检验）
- consistency_checker: 一致性检验器

使用流程：
1. python scripts/experiments/cascade_consistency/run_baseline.py
2. python scripts/experiments/cascade_consistency/run_experiment.py --scenario scenario1

输出：
- baseline_reports.json: 基线报告
- experiment_result.json: 实验结果
- revision_diffs.json: 修订差异
- consistency_scores.json: 一致性评分
"""

from .consistency_checker import (
    ConsistencyChecker,
    ConsistencyResult,
    check_semantic_alignment,
)

__all__ = [
    "ConsistencyChecker",
    "ConsistencyResult",
    "check_semantic_alignment",
]