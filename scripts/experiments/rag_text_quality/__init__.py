"""
RAG Text Quality Experiment Module
RAG 文本质量评估实验模块

实验设计：2×2 干净对照 + Oracle 上限

实验组：
- G1（基线）：L1-L2 无 RAG，L3 无 RAG → 纯 LLM 能力
- G2（L3 纯增益）：L1-L2 无 RAG，L3 RAG → L3 RAG 净效益
- G3（全开）：L1 RAG，L2 无 RAG，L3 RAG → 实际应用效果（L2 RAG 默认关闭）

评估指标：
- Faithfulness（自动）：生成文本中可被检索上下文支持的原子陈述比例
- 专业深度（人工）：分析是否有深度
- 实用可操作性（人工）：建议是否可落地
- 论据支撑（人工）：引用是否支撑关键论点
- 引用质量：存在性、准确性、支持性引用比例

使用方法:
    # 使用新的统一框架
    from scripts.experiments.rag_quality.runner import RAGQualityRunner
    from scripts.experiments.framework.config import ExperimentConfig

    config = ExperimentConfig.default("rag_quality")
    runner = RAGQualityRunner(config, group_name="g1", iteration=0)
    result = await runner.run()
"""

from scripts.experiments.rag_text_quality.oracle_knowledge import (
    OracleKnowledge,
    OracleRegulation,
    OracleKnowledgeResult,
    get_oracle_context_for_dimension,
    ORACLE_KNOWLEDGE_CONFIG,
)

from scripts.experiments.rag_text_quality.text_quality_metrics import (
    TextQualityMetrics,
    FaithfulnessCalculator,
    ContentDepthEvaluator,
    FaithfulnessResult,
    TextQualityResult,
    calculate_faithfulness,
    evaluate_text_quality,
)

from scripts.experiments.rag_text_quality.citation_quality import (
    CitationQualityEvaluator,
    CitationExtractor,
    Citation,
    CitationQualityResult,
    evaluate_citation_quality,
)

from scripts.experiments.rag_text_quality.statistical_analysis import (
    StatisticalAnalyzer,
    ComparisonResult,
    GroupStatistics,
    AnalysisResult,
    compare_groups,
    generate_radar_chart_data,
    generate_forest_plot_data,
)

__all__ = [
    # Oracle 知识
    "OracleKnowledge",
    "OracleRegulation",
    "OracleKnowledgeResult",
    "get_oracle_context_for_dimension",
    "ORACLE_KNOWLEDGE_CONFIG",

    # 文本质量指标
    "TextQualityMetrics",
    "FaithfulnessCalculator",
    "ContentDepthEvaluator",
    "FaithfulnessResult",
    "TextQualityResult",
    "calculate_faithfulness",
    "evaluate_text_quality",

    # 引用质量
    "CitationQualityEvaluator",
    "CitationExtractor",
    "Citation",
    "CitationQualityResult",
    "evaluate_citation_quality",

    # 统计分析
    "StatisticalAnalyzer",
    "ComparisonResult",
    "GroupStatistics",
    "AnalysisResult",
    "compare_groups",
    "generate_radar_chart_data",
    "generate_forest_plot_data",
]
