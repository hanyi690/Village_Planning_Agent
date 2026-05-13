"""
LLM Assisted Planning Document Generation V3.0

V3.0 架构：简化版导出，直接从 Layer3 提取内容

模块：
- config: 配置常量（CRITICAL_NUMBERS、TARGET_DOCUMENT_STRUCTURE）
- simple_export: 简化版导出脚本（核心）
- renderer: Word模板渲染
- pipeline: 主流程编排（简化调用）
- cli: 命令行入口
"""

__version__ = "3.0.0"

from scripts.llm_assisted.config import (
    TARGET_DOCUMENT_STRUCTURE,
    CRITICAL_NUMBERS,
    DEFAULT_VALUES,
)

from scripts.llm_assisted.simple_export import (
    export_planning_document,
    PlanningDocumentBuilder,
    Layer3Parser,
    MarkdownTransformer,
    ExportResult,
)

from scripts.llm_assisted.renderer import (
    WordRenderer,
    RenderResult,
    render_to_word,
)

from scripts.llm_assisted.pipeline import (
    run_pipeline,
)

__all__ = [
    # Config
    "TARGET_DOCUMENT_STRUCTURE",
    "CRITICAL_NUMBERS",
    "DEFAULT_VALUES",
    # Simple Export
    "export_planning_document",
    "PlanningDocumentBuilder",
    "Layer3Parser",
    "MarkdownTransformer",
    "ExportResult",
    # Renderer
    "WordRenderer",
    "RenderResult",
    "render_to_word",
    # Pipeline
    "run_pipeline",
]
