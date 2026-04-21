"""
RAG 元数据模块

提供元数据注入、维度标注、地形识别等功能。
"""

# 统一定义
from .definitions import (
    DIMENSIONS,
    DIMENSION_KEYS,
    get_dimension_keywords,
    get_dimension_definitions,
    TERRAIN_KEYWORDS,
    DOCUMENT_TYPE_KEYWORDS,
)

# 标注器
from .tagging_rules import DimensionTagger, TerrainTagger, DocumentTypeTagger
from .injector import MetadataInjector

__all__ = [
    # 统一定义
    "DIMENSIONS",
    "DIMENSION_KEYS",
    "get_dimension_keywords",
    "get_dimension_definitions",
    "TERRAIN_KEYWORDS",
    "DOCUMENT_TYPE_KEYWORDS",
    # 标注器
    "DimensionTagger",
    "TerrainTagger",
    "DocumentTypeTagger",
    "MetadataInjector",
]