"""Intent tools as LangChain BaseTools.

Replaces dict-based ADVANCE_PLANNING_TOOL / GIS_ANALYSIS_TOOL constants.
These tools are used by the conversation node's bind_tools and routed
by after_conversation to dispatch dimension analysis or trigger the
GIS Agent subgraph.
"""

from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool


class AdvancePlanningIntentInput(BaseModel):
    """推进规划意图参数"""
    reason: Optional[str] = Field(
        default=None,
        description="推进规划的原因"
    )


class GisAnalysisInput(BaseModel):
    """GIS 分析意图参数"""
    dimension_key: str = Field(
        description="维度标识（如 traffic, land_use, natural_environment, public_services 等）"
    )
    village_name: Optional[str] = Field(
        default=None,
        description="村庄名称（可选，默认使用当前规划项目的村庄名）"
    )


@tool(args_schema=AdvancePlanningIntentInput)
def advance_planning_intent(reason: Optional[str] = None) -> str:
    """推进规划流程到下一阶段。

    当用户表示要继续规划、开始分析、下一步时调用。
    """
    return f"advance_planning_intent: reason={reason or '未说明'}"


@tool(args_schema=GisAnalysisInput)
def gis_analysis(dimension_key: str, village_name: Optional[str] = None) -> str:
    """触发 GIS 空间布局规划。

    调用 ReAct Agent 子图，自动选择数据获取、知识图谱构建、冲突检测、
    分区分配、布局生成等工具。当用户请求空间分析、用地布局、GIS
    可视化时调用。
    """
    return f"gis_analysis: dimension_key={dimension_key}, village_name={village_name or '默认'}"


__all__ = [
    "advance_planning_intent",
    "gis_analysis",
    "AdvancePlanningIntentInput",
    "GisAnalysisInput",
]
