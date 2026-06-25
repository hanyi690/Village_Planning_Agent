"""LangChain @tool definitions for execute_tools_node.

- population_prediction: 人口预测 (uses InjectedState for context)
- knowledge_search: 知识检索
- web_search: 网络搜索
"""

from typing import Dict, Any, List, Optional, Annotated
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState


class PopulationAnalysisInput(BaseModel):
    analysis_type: str = Field(
        description="分析类型: population_forecast, village_forecast, population_structure, labor_force_analysis"
    )
    baseline_population: Optional[int] = Field(default=None, description="基期人口数")
    baseline_year: Optional[int] = Field(default=None, description="基期年份")
    target_year: Optional[int] = Field(default=2035, description="目标年份")
    natural_growth_rate: Optional[float] = Field(default=4.0, description="自然增长率 (‰)")
    mechanical_growth: Optional[int] = Field(default=0, description="机械增长人口")


@tool(args_schema=PopulationAnalysisInput)
def population_prediction(
    analysis_type: str = "village_forecast",
    baseline_population: Optional[int] = None,
    baseline_year: Optional[int] = None,
    target_year: int = 2035,
    natural_growth_rate: float = 4.0,
    mechanical_growth: int = 0,
    state: Annotated[Optional[Dict[str, Any]], InjectedState()] = None,
) -> str:
    """执行人口预测分析。支持村庄规划标准模型 (Pn = P0 × (1 + K)^n + M)。"""
    from .analytics import calculate_population

    context = {
        "analysis_type": analysis_type,
        "baseline_population": baseline_population,
        "baseline_year": baseline_year,
        "target_year": target_year,
        "natural_growth_rate": natural_growth_rate,
        "mechanical_growth": mechanical_growth,
        "dep_metrics": (state or {}).get("_dep_metrics", {}),
        "structured_summary": (state or {}).get("structured_summary"),
    }
    return calculate_population(context)


class KnowledgeSearchInput(BaseModel):
    query: str = Field(description="搜索查询")
    top_k: int = Field(default=5, description="返回结果数量")
    context_mode: str = Field(default="standard", description="上下文模式")


class WebSearchInput(BaseModel):
    query: str = Field(description="搜索查询")
    backend: str = Field(default="tavily", description="搜索后端: tavily, serper")
    num_results: int = Field(default=5, description="返回结果数量")


@tool(args_schema=KnowledgeSearchInput)
def knowledge_search(query: str, top_k: int = 5, context_mode: str = "standard") -> str:
    """从知识库检索专业数据和法规条文。"""
    from .analytics.knowledge_search import search_knowledge
    return search_knowledge(query=query, top_k=top_k, context_mode=context_mode)


@tool(args_schema=WebSearchInput)
def web_search(query: str, backend: str = "tavily", num_results: int = 5) -> str:
    """从互联网搜索实时信息。"""
    from .analytics import web_search_tool
    return web_search_tool({"query": query, "backend": backend, "num_results": num_results})


ALL_TOOLS: List = [population_prediction, knowledge_search, web_search]
TOOL_REGISTRY: Dict[str, object] = {t.name: t for t in ALL_TOOLS}


def get_tools_for_llm():
    return ALL_TOOLS


__all__ = [
    "population_prediction", "knowledge_search", "web_search",
    "ALL_TOOLS", "TOOL_REGISTRY", "get_tools_for_llm",
]
