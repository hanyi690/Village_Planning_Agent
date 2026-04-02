"""
分析类适配器

提供 GIS 空间分析、交通网络分析、人口预测分析、可达性分析等功能。
"""

from .gis_analysis_adapter import GISAnalysisAdapter
from .network_adapter import NetworkAnalysisAdapter
from .population_adapter import PopulationPredictionAdapter
from .accessibility_adapter import AccessibilityAdapter

__all__ = [
    "GISAnalysisAdapter",
    "NetworkAnalysisAdapter",
    "PopulationPredictionAdapter",
    "AccessibilityAdapter",
]