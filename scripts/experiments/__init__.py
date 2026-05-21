"""
Experiment Scripts
实验脚本模块

包含两个独立子模块：

1. rag - RAG 质量实验
   - runner: 实验运行器
   - citation: 引用质量评估
   - text_quality: 文本质量评估
   - verify_citations: 引用验证
   - analyze: 分析脚本

2. cascade - 级联修订实验
   - runner: 实验运行器
   - baseline: 基线生成
   - checker: 一致性检验器
   - evaluate: 后评估脚本

公共框架：
- framework: 通用配置、指标、数据访问
"""

__all__ = [
    "config",
    "rag",
    "cascade",
    "framework",
]
