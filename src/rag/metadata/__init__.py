"""
RAG 元数据模块

提供元数据注入、维度标注、地形识别等功能。
"""

from .tagging_rules import DimensionTagger, TerrainTagger, DocumentTypeTagger
from .injector import MetadataInjector

__all__ = [
    "DimensionTagger",
    "TerrainTagger",
    "DocumentTypeTagger",
    "MetadataInjector",
]
