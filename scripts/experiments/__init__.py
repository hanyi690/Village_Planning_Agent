"""
Cascade Consistency Experiment Scripts
级联一致性检验实验

验证级联修复机制在同层传播和跨层传播两种路径下能否保持语义一致性。

实验场景:
- 场景一: 驳回"规划定位"(Layer 2)
- 场景二: 驳回"自然环境分析"(Layer 1)
"""

__all__ = [
    "config",
    "run_baseline",
    "run_scenario",
    "consistency_annotation",
    "generate_metrics",
]