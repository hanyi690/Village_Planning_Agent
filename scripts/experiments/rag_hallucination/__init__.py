"""
RAG Hallucination Experiment Module
RAG幻觉率实验模块

包含：
- reference_extractor: 引用提取器
- hallucination_validator: 幻觉验证器
- experiment_runner: 实验运行器
- generate_experiment_outputs: 输出生成器
- run_rag_experiment: 实验入口脚本
- validate_rag_references: 引用验证脚本
"""

from .reference_extractor import (
    ReferenceExtractor,
    ExtractedReference,
    ReferenceType,
    extract_references_from_report,
    get_reference_statistics,
)

from .hallucination_validator import (
    HallucinationValidator,
    ValidationResult,
    ValidationStatus,
    validate_references_batch,
)

from .experiment_runner import (
    ExperimentRunner,
    SingleRunResult,
    AggregatedDimensionResult,
    ExperimentResult,
    run_full_experiment,
    compare_rag_on_off,
)

__all__ = [
    # Reference extraction
    "ReferenceExtractor",
    "ExtractedReference",
    "ReferenceType",
    "extract_references_from_report",
    "get_reference_statistics",
    # Hallucination validation
    "HallucinationValidator",
    "ValidationResult",
    "ValidationStatus",
    "validate_references_batch",
    # Experiment runner
    "ExperimentRunner",
    "SingleRunResult",
    "AggregatedDimensionResult",
    "ExperimentResult",
    "run_full_experiment",
    "compare_rag_on_off",
]
