"""
统一工具定义模块

使用 LangChain 原生 @tool 装饰器定义所有工具，替代适配器层嵌套。
"""

from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field
from langchain_core.tools import tool

from .core import (
    run_gis_analysis,
    format_gis_result,
    run_network_analysis,
    format_network_result,
    run_population_analysis,
    format_population_result,
    run_accessibility_analysis,
    format_accessibility_result,
)
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# Tool Display Names (Compatibility)
# ==========================================

TOOL_DISPLAY_NAMES = {
    "gis_analysis": "GIS 空间分析",
    "gis_data_fetch": "GIS 数据获取",
    "network_analysis": "交通网络分析",
    "population_prediction": "人口预测",
    "accessibility_analysis": "可达性分析",
    "poi_search": "POI 搜索",
    "route_planning": "路径规划",
    "knowledge_search": "知识检索",
    "web_search": "网络搜索",
}


# ==========================================
# Input Schema 定义
# ==========================================

class GISAnalysisInput(BaseModel):
    """GIS 分析输入参数"""
    analysis_type: str = Field(
        description="分析类型: land_use_analysis, soil_analysis, hydrology_analysis"
    )
    geo_data_path: Optional[str] = Field(
        default=None,
        description="土地利用数据文件路径 (GeoJSON/Shapefile)"
    )
    soil_data_path: Optional[str] = Field(
        default=None,
        description="土壤数据文件路径"
    )
    hydrology_data_path: Optional[str] = Field(
        default=None,
        description="水文数据文件路径"
    )


class NetworkAnalysisInput(BaseModel):
    """网络分析输入参数"""
    analysis_type: str = Field(
        description="分析类型: connectivity_metrics, accessibility_analysis, centrality_analysis"
    )
    network_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="网络数据，包含 nodes 和 edges"
    )
    origins: Optional[List[str]] = Field(
        default=None,
        description="起点列表"
    )
    destinations: Optional[List[str]] = Field(
        default=None,
        description="终点列表"
    )


class PopulationAnalysisInput(BaseModel):
    """人口分析输入参数"""
    analysis_type: str = Field(
        description="分析类型: population_forecast, village_forecast, population_structure, labor_force_analysis"
    )
    baseline_population: Optional[int] = Field(
        default=None,
        description="基期人口数"
    )
    baseline_year: Optional[int] = Field(
        default=None,
        description="基期年份"
    )
    target_year: Optional[int] = Field(
        default=2035,
        description="目标年份 (用于 village_forecast)"
    )
    natural_growth_rate: Optional[float] = Field(
        default=4.0,
        description="自然增长率 (‰, 千分比)"
    )
    mechanical_growth: Optional[int] = Field(
        default=0,
        description="机械增长人口"
    )


class AccessibilityAnalysisInput(BaseModel):
    """可达性分析输入参数"""
    analysis_type: str = Field(
        description="分析类型: driving_accessibility, walking_accessibility, service_coverage, poi_coverage"
    )
    origin: Optional[Tuple[float, float]] = Field(
        default=None,
        description="起点坐标 (lon, lat)"
    )
    destinations: Optional[List[Tuple[float, float]]] = Field(
        default=None,
        description="目标点列表 [(lon, lat), ...]"
    )
    center: Optional[Tuple[float, float]] = Field(
        default=None,
        description="中心坐标 (lon, lat)"
    )
    max_time: Optional[int] = Field(
        default=30,
        description="最大时间限制 (分钟)"
    )
    max_distance: Optional[float] = Field(
        default=20.0,
        description="最大距离限制 (公里)"
    )
    poi_type: Optional[str] = Field(
        default="学校",
        description="POI 类型 (用于 service_coverage)"
    )
    radius: Optional[int] = Field(
        default=500,
        description="服务半径 (米)"
    )


# ==========================================
# 工具定义
# ==========================================

@tool(args_schema=GISAnalysisInput)
def gis_analysis(
    analysis_type: str,
    geo_data_path: Optional[str] = None,
    soil_data_path: Optional[str] = None,
    hydrology_data_path: Optional[str] = None,
    **kwargs
) -> str:
    """
    执行 GIS 空间分析。

    支持土地利用分析、土壤分析、水文分析。
    需要提供对应的数据文件路径。
    """
    result = run_gis_analysis(
        analysis_type=analysis_type,
        geo_data_path=geo_data_path,
        soil_data_path=soil_data_path,
        hydrology_data_path=hydrology_data_path,
        **kwargs
    )
    return format_gis_result(result)


@tool(args_schema=NetworkAnalysisInput)
def network_analysis(
    analysis_type: str,
    network_data: Optional[Dict[str, Any]] = None,
    origins: Optional[List[str]] = None,
    destinations: Optional[List[str]] = None,
    **kwargs
) -> str:
    """
    执行交通网络分析。

    支持连通度分析、可达性分析、中心性分析。
    需要提供网络数据（节点和边）。
    """
    result = run_network_analysis(
        analysis_type=analysis_type,
        network_data=network_data,
        origins=origins,
        destinations=destinations,
        **kwargs
    )
    return format_network_result(result)


@tool(args_schema=PopulationAnalysisInput)
def population_prediction(
    analysis_type: str = "village_forecast",
    baseline_population: Optional[int] = None,
    baseline_year: Optional[int] = None,
    target_year: int = 2035,
    natural_growth_rate: float = 4.0,
    mechanical_growth: int = 0,
    **kwargs
) -> str:
    """
    执行人口预测分析。

    支持村庄规划标准模型 (Pn = P0 × (1 + K)^n + M)、
    通用人口预测、人口结构分析、劳动力供给分析。
    """
    result = run_population_analysis(
        analysis_type=analysis_type,
        baseline_population=baseline_population,
        baseline_year=baseline_year,
        target_year=target_year,
        natural_growth_rate=natural_growth_rate,
        mechanical_growth=mechanical_growth,
        **kwargs
    )
    return format_population_result(result)


@tool(args_schema=AccessibilityAnalysisInput)
def accessibility_analysis(
    analysis_type: str = "driving_accessibility",
    origin: Optional[Tuple[float, float]] = None,
    destinations: Optional[List[Tuple[float, float]]] = None,
    center: Optional[Tuple[float, float]] = None,
    max_time: int = 30,
    max_distance: float = 20.0,
    poi_type: str = "学校",
    radius: int = 500,
    **kwargs
) -> str:
    """
    执行可达性分析。

    支持驾车可达性、步行可达性、服务半径覆盖、POI 设施覆盖分析。
    使用天地图 API 进行真实道路网络计算。
    """
    result = run_accessibility_analysis(
        analysis_type=analysis_type,
        origin=origin,
        destinations=destinations,
        center=center,
        max_time=max_time,
        max_distance=max_distance,
        poi_type=poi_type,
        radius=radius,
        **kwargs
    )
    return format_accessibility_result(result)


# ==========================================
# 知识检索和网络搜索工具
# ==========================================

class KnowledgeSearchInput(BaseModel):
    """知识检索输入参数"""
    query: str = Field(description="搜索查询")
    top_k: int = Field(default=5, description="返回结果数量")
    context_mode: str = Field(default="standard", description="上下文模式")


class WebSearchInput(BaseModel):
    """网络搜索输入参数"""
    query: str = Field(description="搜索查询")
    backend: str = Field(default="tavily", description="搜索后端: tavily, serper")
    num_results: int = Field(default=5, description="返回结果数量")


@tool(args_schema=KnowledgeSearchInput)
def knowledge_search(query: str, top_k: int = 5, context_mode: str = "standard") -> str:
    """
    从知识库检索专业数据和法规条文。

    支持 RAG 知识检索，返回相关文档片段。
    """
    from .builtin import knowledge_search_tool

    context = {
        "query": query,
        "top_k": top_k,
        "context_mode": context_mode
    }
    return knowledge_search_tool(context)


@tool(args_schema=WebSearchInput)
def web_search(query: str, backend: str = "tavily", num_results: int = 5) -> str:
    """
    从互联网搜索实时信息。

    支持新闻、政策、技术数据等查询。
    """
    from .builtin import web_search_tool

    context = {
        "query": query,
        "backend": backend,
        "num_results": num_results
    }
    return web_search_tool(context)


# ==========================================
# 工具集合导出
# ==========================================

ALL_TOOLS = [
    gis_analysis,
    network_analysis,
    population_prediction,
    accessibility_analysis,
    knowledge_search,
    web_search,
]


def get_tools_for_llm():
    """获取用于 LLM bind_tools 的工具列表"""
    return ALL_TOOLS


__all__ = [
    "gis_analysis",
    "network_analysis",
    "population_prediction",
    "accessibility_analysis",
    "knowledge_search",
    "web_search",
    "ALL_TOOLS",
    "get_tools_for_llm",
]