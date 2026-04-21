"""
RAG 切片策略模块

统一 Markdown 切片器（配置驱动），替代原有多个独立切片器类。
"""

from .slicer import (
    UnifiedMarkdownSlicer,
    Chunk,
    SlicerConfig,
    SlicingStrategyFactory,
)

__all__ = [
    "UnifiedMarkdownSlicer",
    "Chunk",
    "SlicerConfig",
    "SlicingStrategyFactory",
]