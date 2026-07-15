"""Planning text generation module.

Generates complete village planning documents from database-stored
dimension reports, using three-tier strategy routing
(S-COPY / S-ASSEMBLE / S-TEMPLATE / S-GENERATE).
"""

from .config import PlanningTextConfig
from .generator import PlanningTextGenerator, GenerationResult
from .content_extractor import ExtractedData, ContentExtractor, create_extracted_data
from .section_builder import SectionBuilder, BuildReport, ArticleOutput, ARTICLE_DEFS
from .llm_styler import LLMStyler
from .rag_appender import RAGAppender
from .json_exporter import JsonExporter
from .layer_exporter import (
    LayerExportConfig,
    LayerExporter,
    LayerExportResult,
    DimensionReport,
    LAYER_NAMES,
)

__all__ = [
    "PlanningTextConfig",
    "PlanningTextGenerator",
    "GenerationResult",
    "ExtractedData",
    "ContentExtractor",
    "create_extracted_data",
    "SectionBuilder",
    "BuildReport",
    "ArticleOutput",
    "ARTICLE_DEFS",
    "LLMStyler",
    "RAGAppender",
    "JsonExporter",
    "LayerExportConfig",
    "LayerExporter",
    "LayerExportResult",
    "DimensionReport",
    "LAYER_NAMES",
]
