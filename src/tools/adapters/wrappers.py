"""
Adapter 工具包装器

将 Adapter 适配器包装为 ToolRegistry 可注册的函数，
实现统一的工具调用接口。
"""

from typing import Dict, Any, Type, Optional, Callable
from ..registry import ToolRegistry
from .base_adapter import BaseAdapter, AdapterResult, AdapterStatus
from ...utils.logger import get_logger

logger = get_logger(__name__)


def adapter_to_tool_function(
    adapter_class: Type[BaseAdapter],
    adapter_name: str,
    default_analysis_type: Optional[str] = None,
    result_formatter: Optional[Callable[[AdapterResult], str]] = None
) -> Callable[[Dict[str, Any]], str]:
    """
    将 Adapter 类转换为 ToolRegistry 可注册的工具函数
    
    Args:
        adapter_class: Adapter 类
        adapter_name: 适配器名称（用于日志）
        default_analysis_type: 默认分析类型
        result_formatter: 自定义结果格式化函数
        
    Returns:
        可注册到 ToolRegistry 的工具函数
    """
    
    def tool_function(context: Dict[str, Any]) -> str:
        """
        工具函数包装器
        
        Args:
            context: 包含所需数据的上下文字典
            
        Returns:
            格式化的工具输出字符串
        """
        logger.info(f"[AdapterWrapper] 执行适配器: {adapter_name}")
        
        try:
            # 创建适配器实例
            adapter = adapter_class()
            
            # 准备执行参数
            kwargs = {}
            
            # 如果有默认分析类型
            if default_analysis_type:
                kwargs["analysis_type"] = default_analysis_type
            
            # 从上下文中提取参数
            if "analysis_type" in context:
                kwargs["analysis_type"] = context["analysis_type"]
            if "village_data" in context:
                kwargs["village_data"] = context["village_data"]
            if "socio_economic" in context:
                kwargs["socio_economic"] = context["socio_economic"]
            if "traffic" in context:
                kwargs["traffic"] = context["traffic"]
            if "land_use" in context:
                kwargs["land_use"] = context["land_use"]
            
            # 执行适配器
            result = adapter.run(**kwargs)
            
            # 格式化结果
            if result_formatter:
                return result_formatter(result)
            else:
                return _default_format_result(result, adapter_name)
                
        except Exception as e:
            logger.error(f"[AdapterWrapper] 适配器执行失败: {adapter_name}, 错误: {e}")
            return f"## {adapter_name} 执行失败\n\n错误: {str(e)}"
    
    return tool_function


def _default_format_result(result: AdapterResult, adapter_name: str) -> str:
    """
    默认结果格式化函数
    
    Args:
        result: 适配器执行结果
        adapter_name: 适配器名称
        
    Returns:
        格式化的字符串
    """
    if not result.success:
        return f"## {adapter_name} 执行失败\n\n错误: {result.error or '未知错误'}"
    
    # 构建输出
    lines = [f"## {adapter_name} 分析结果\n"]
    
    # 添加元数据
    if result.metadata:
        lines.append("**分析参数:**")
        for key, value in result.metadata.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    
    # 添加数据
    if result.data:
        lines.append("**分析结果:**")
        for key, value in result.data.items():
            if isinstance(value, dict):
                lines.append(f"\n### {key}")
                for k, v in value.items():
                    lines.append(f"- {k}: {v}")
            elif isinstance(value, list):
                lines.append(f"\n### {key}")
                for item in value[:10]:  # 限制显示数量
                    lines.append(f"- {item}")
                if len(value) > 10:
                    lines.append(f"- ... 共 {len(value)} 项")
            else:
                lines.append(f"- {key}: {value}")
    
    return "\n".join(lines)


def register_adapter_as_tool(
    adapter_class: Type[BaseAdapter],
    tool_name: str,
    adapter_name: Optional[str] = None,
    default_analysis_type: Optional[str] = None,
    result_formatter: Optional[Callable[[AdapterResult], str]] = None
) -> Callable[[Dict[str, Any]], str]:
    """
    将 Adapter 注册为 ToolRegistry 工具
    
    Args:
        adapter_class: Adapter 类
        tool_name: 工具名称（注册到 ToolRegistry）
        adapter_name: 适配器名称（用于日志，默认使用 tool_name）
        default_analysis_type: 默认分析类型
        result_formatter: 自定义结果格式化函数
        
    Returns:
        注册后的工具函数
    """
    adapter_name = adapter_name or tool_name
    
    # 创建工具函数
    tool_func = adapter_to_tool_function(
        adapter_class=adapter_class,
        adapter_name=adapter_name,
        default_analysis_type=default_analysis_type,
        result_formatter=result_formatter
    )
    
    # 注册到 ToolRegistry
    ToolRegistry.register(tool_name)(tool_func)
    
    logger.info(f"[AdapterWrapper] 已将适配器 {adapter_class.__name__} 注册为工具: {tool_name}")
    
    return tool_func


# ==========================================
# 预定义的格式化函数
# ==========================================

def format_population_result(result: AdapterResult) -> str:
    """格式化人口预测结果"""
    if not result.success:
        return f"## 人口预测失败\n\n错误: {result.error or '未知错误'}"
    
    data = result.data
    
    lines = ["## 人口预测结果\n"]
    
    # 当前人口
    if "current_population" in data:
        lines.append(f"**当前人口:** {data['current_population']} 人\n")
    
    # 预测结果
    if "projections" in data:
        lines.append("**人口预测:**")
        for year, pop in data["projections"].items():
            lines.append(f"- {year}年: {pop} 人")
        lines.append("")
    
    # 人口结构
    if "structure" in data:
        lines.append("**人口结构:**")
        structure = data["structure"]
        lines.append(f"- 劳动年龄人口: {structure.get('working_age', 'N/A')}")
        lines.append(f"- 老年人口比例: {structure.get('elderly_ratio', 'N/A')}")
        lines.append(f"- 儿童人口比例: {structure.get('children_ratio', 'N/A')}")
    
    return "\n".join(lines)


def format_gis_result(result: AdapterResult) -> str:
    """格式化 GIS 分析结果"""
    if not result.success:
        return f"## GIS 分析失败\n\n错误: {result.error or '未知错误'}"
    
    data = result.data
    
    lines = ["## GIS 空间分析结果\n"]
    
    # 土地利用
    if "land_use" in data:
        lines.append("**土地利用结构:**")
        for land_type, ratio in data["land_use"].items():
            lines.append(f"- {land_type}: {ratio}%")
        lines.append("")
    
    # 覆盖率
    if "coverage" in data:
        lines.append("**服务覆盖率:**")
        for service, coverage in data["coverage"].items():
            lines.append(f"- {service}: {coverage}%")
    
    return "\n".join(lines)


def format_network_result(result: AdapterResult) -> str:
    """格式化网络分析结果"""
    if not result.success:
        return f"## 网络分析失败\n\n错误: {result.error or '未知错误'}"
    
    data = result.data
    
    lines = ["## 交通网络分析结果\n"]
    
    # 可达性
    if "accessibility" in data:
        lines.append("**可达性指标:**")
        acc = data["accessibility"]
        lines.append(f"- 平均出行时间: {acc.get('avg_travel_time', 'N/A')} 分钟")
        lines.append(f"- 最大出行时间: {acc.get('max_travel_time', 'N/A')} 分钟")
        lines.append("")
    
    # 连通性
    if "connectivity" in data:
        lines.append("**连通性指标:**")
        conn = data["connectivity"]
        lines.append(f"- 道路密度: {conn.get('road_density', 'N/A')} km/km²")
        lines.append(f"- 连通度指数: {conn.get('connectivity_index', 'N/A')}")
    
    return "\n".join(lines)


__all__ = [
    "adapter_to_tool_function",
    "register_adapter_as_tool",
    "format_population_result",
    "format_gis_result",
    "format_network_result",
]
