"""
工具注册中心 - Hook + Registry 模式

支持特殊维度调用自定义 Python 工具（GIS、人口模型、定量计算等）
"""

from typing import Any, Callable, Dict, Optional
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ToolRegistry:
    """
    工具注册中心

    管理所有自定义工具函数，支持装饰器注册和动态调用
    """

    _tools: Dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str):
        """
        装饰器：注册工具函数

        Usage:
            @ToolRegistry.register("population_model_v1")
            def calculate_population(context: dict) -> str:
                ...
        """
        def decorator(func: Callable) -> Callable:
            cls._tools[name] = func
            logger.info(f"[ToolRegistry] 工具已注册: {name} -> {func.__name__}")
            return func
        return decorator

    @classmethod
    def get_tool(cls, name: str) -> Optional[Callable]:
        """
        获取工具函数

        Args:
            name: 工具名称

        Returns:
            工具函数，未找到返回 None
        """
        return cls._tools.get(name)

    @classmethod
    def list_tools(cls) -> Dict[str, str]:
        """
        列出所有已注册工具

        Returns:
            {工具名称: 函数名} 字典
        """
        return {name: func.__name__ for name, func in cls._tools.items()}

    @classmethod
    def execute_tool(cls, name: str, context: Dict[str, Any]) -> str:
        """
        执行工具并返回结果

        Args:
            name: 工具名称
            context: 上下文数据

        Returns:
            工具输出字符串

        Raises:
            ValueError: 工具不存在或执行失败
        """
        tool_func = cls.get_tool(name)
        if not tool_func:
            raise ValueError(f"工具不存在: {name}")

        try:
            result = tool_func(context)
            logger.info(f"[ToolRegistry] 工具执行成功: {name}")
            return result
        except Exception as e:
            logger.error(f"[ToolRegistry] 工具执行失败: {name}, 错误: {e}")
            raise


def _initialize_adapter_tools():
    """
    初始化 Adapter 工具

    使用新的 tool_wrapper 模块注册适配器工具
    """
    from .adapters.tool_wrapper import (
        create_adapter_tool_function,
        format_population_result,
        format_gis_result,
        format_network_result,
        format_gis_fetch_result,
        format_visualization_result,
        format_accessibility_result,
        format_poi_result
    )

    # Analysis Adapters
    try:
        from .adapters.analysis import (
            GISAnalysisAdapter,
            NetworkAnalysisAdapter,
            PopulationPredictionAdapter,
            AccessibilityAdapter
        )

        tool_func = create_adapter_tool_function(
            GISAnalysisAdapter, "GIS 空间分析", result_formatter=format_gis_result
        )
        ToolRegistry.register("gis_analysis")(tool_func)

        tool_func = create_adapter_tool_function(
            NetworkAnalysisAdapter, "交通网络分析", result_formatter=format_network_result
        )
        ToolRegistry.register("network_analysis")(tool_func)

        tool_func = create_adapter_tool_function(
            PopulationPredictionAdapter, "人口预测分析", result_formatter=format_population_result
        )
        ToolRegistry.register("population_prediction")(tool_func)

        # 可达性分析适配器
        tool_func = create_adapter_tool_function(
            AccessibilityAdapter, "可达性分析", result_formatter=format_accessibility_result
        )
        ToolRegistry.register("accessibility_analysis")(tool_func)
    except ImportError:
        logger.debug("[ToolRegistry] Analysis Adapters 未安装，跳过注册")

    # Data Fetch Adapter
    try:
        from .adapters.data_fetch import GISDataFetchAdapter
        tool_func = create_adapter_tool_function(
            GISDataFetchAdapter, "GIS 数据拉取", result_formatter=format_gis_fetch_result
        )
        ToolRegistry.register("gis_data_fetch")(tool_func)

        # POI 搜索工具
        tool_func = create_adapter_tool_function(
            GISDataFetchAdapter, "POI 数据获取",
            default_analysis_type="poi_fetch",
            result_formatter=format_poi_result
        )
        ToolRegistry.register("poi_search")(tool_func)

        # WFS 数据获取工具
        tool_func = create_adapter_tool_function(
            GISDataFetchAdapter, "WFS 图层获取",
            default_analysis_type="wfs_fetch",
            result_formatter=format_gis_fetch_result
        )
        ToolRegistry.register("wfs_data_fetch")(tool_func)

        # 路径规划工具
        tool_func = create_adapter_tool_function(
            GISDataFetchAdapter, "路径数据获取",
            default_analysis_type="route_fetch",
            result_formatter=format_gis_fetch_result
        )
        ToolRegistry.register("route_planning")(tool_func)

        # 逆地理编码工具
        tool_func = create_adapter_tool_function(
            GISDataFetchAdapter, "逆地理编码",
            default_analysis_type="reverse_geocode",
            result_formatter=format_gis_fetch_result
        )
        ToolRegistry.register("reverse_geocode")(tool_func)
    except ImportError:
        logger.debug("[ToolRegistry] Data Fetch Adapter 未安装，跳过注册")

    # Visualization Adapter
    try:
        from .adapters.visualization import GISVisualizationAdapter
        tool_func = create_adapter_tool_function(
            GISVisualizationAdapter, "GIS 可视化", result_formatter=format_visualization_result
        )
        ToolRegistry.register("gis_visualization")(tool_func)
    except ImportError:
        logger.debug("[ToolRegistry] Visualization Adapter 未安装，跳过注册")


# 导入内置工具模块（自动注册）
from .builtin import knowledge_search_tool, web_search_tool
from .builtin.population import calculate_population
from .builtin.network import calculate_network_accessibility

# 初始化 Adapter 工具
_initialize_adapter_tools()


__all__ = ["ToolRegistry"]