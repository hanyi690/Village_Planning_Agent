"""
Experiment Scripts
实验脚本模块

包含两个独立子模块：

1. rag_hallucination - RAG幻觉率实验
   - reference_extractor: 引用提取器
   - hallucination_validator: 幻觉验证器
   - experiment_runner: 实验运行器
   - generate_experiment_outputs: 输出生成器

2. cascade_consistency - 级联一致性实验
   - run_baseline: 基线运行脚本
   - run_scenario: 场景运行脚本
   - consistency_annotation: 一致性标注工具
   - layer_checkpoint_utils: 层级检查点工具

公共配置：
- config: 实验配置（路径、场景定义等）
"""

__all__ = [
    "config",
    "rag_hallucination",
    "cascade_consistency",
]