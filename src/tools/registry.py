"""
工具注册中心 - Hook + Registry 模式

支持特殊维度调用自定义 Python 工具（GIS、人口模型、定量计算等）

支持两种执行模式：
1. 传统模式：execute_tool() 返回格式化字符串
2. 对话模式：execute_tool_structured() 返回结构化结果 + SSE 事件
"""

from typing import Any, Callable, Dict, List, Optional, Union
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ToolMetadata:
    """工具元数据（用于 LLM bind_tools）"""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: Optional[Dict[str, Any]] = None,
        display_name: Optional[str] = None
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema or {}
        self.display_name = display_name or name

    def to_langchain_tool(self):
        """转换为 LangChain Tool 格式"""
        from langchain_core.tools import StructuredTool

        return StructuredTool(
            name=self.name,
            description=self.description,
            args_schema=self.input_schema
        )


class ToolRegistry:
    """
    工具注册中心

    管理所有自定义工具函数，支持装饰器注册和动态调用

    支持两种模式：
    - 传统模式：execute_tool() 返回字符串（用于 Planner Hook）
    - 对话模式：execute_tool_structured() 返回 ToolExecutionResult（用于对话式 Agent）
    """

    _tools: Dict[str, Callable] = {}
    _tool_metadata: Dict[str, ToolMetadata] = {}
    _structured_tools: Dict[str, Callable] = {}  # 返回 ToolExecutionResult 的工具

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
        执行工具并返回结果（传统模式，返回字符串）

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

    @classmethod
    def register_with_metadata(cls, metadata: ToolMetadata):
        """
        装饰器：带元数据注册工具（用于 LLM bind_tools）

        Usage:
            @ToolRegistry.register_with_metadata(ToolMetadata(
                name="gis_analysis",
                description="GIS 空间分析",
                display_name="GIS 空间分析"
            ))
            def gis_analysis(context: dict) -> str:
                ...
        """
        def decorator(func: Callable) -> Callable:
            cls._tools[metadata.name] = func
            cls._tool_metadata[metadata.name] = metadata
            logger.info(f"[ToolRegistry] 工具已注册(带元数据): {metadata.name}")
            return func
        return decorator

    @classmethod
    def register_structured(cls, name: str):
        """
        装饰器：注册结构化工具（返回 ToolExecutionResult）

        Usage:
            @ToolRegistry.register_structured("gis_analysis")
            def gis_analysis(context: dict) -> ToolExecutionResult:
                ...
        """
        def decorator(func: Callable) -> Callable:
            cls._structured_tools[name] = func
            cls._tools[name] = func  # 同时注册到普通工具
            logger.info(f"[ToolRegistry] 结构化工具已注册: {name}")
            return func
        return decorator

    @classmethod
    def get_tool_metadata(cls, name: str) -> Optional[ToolMetadata]:
        """获取工具元数据"""
        return cls._tool_metadata.get(name)

    @classmethod
    def get_all_metadata(cls) -> Dict[str, ToolMetadata]:
        """获取所有工具元数据"""
        return cls._tool_metadata.copy()

    @classmethod
    def execute_tool_structured(cls, name: str, context: Dict[str, Any]) -> "ToolExecutionResult":
        """
        执行工具并返回结构化结果（对话模式）

        Args:
            name: 工具名称
            context: 上下文数据（必须包含 session_id）

        Returns:
            ToolExecutionResult: 结构化工具结果
        """
        from .adapters.base_adapter import ToolExecutionResult, DisplayHints

        # 优先使用结构化工具
        tool_func = cls._structured_tools.get(name) or cls._tools.get(name)
        if not tool_func:
            return ToolExecutionResult(
                tool_name=name,
                status="error",
                data={},
                display_hints=DisplayHints(),
                summary=f"工具不存在: {name}",
                error=f"工具不存在: {name}"
            )

        try:
            result = tool_func(context)

            # 如果返回的是 ToolExecutionResult，直接返回
            if isinstance(result, ToolExecutionResult):
                return result

            # 如果返回的是字符串，包装为 ToolExecutionResult
            if isinstance(result, str):
                return ToolExecutionResult(
                    tool_name=name,
                    status="success",
                    data={"text": result},
                    display_hints=DisplayHints(),
                    summary=result[:200] if len(result) > 200 else result
                )

            # 其他类型
            return ToolExecutionResult(
                tool_name=name,
                status="success",
                data={"result": result},
                display_hints=DisplayHints(),
                summary=str(result)[:200]
            )

        except Exception as e:
            logger.error(f"[ToolRegistry] 结构化工具执行失败: {name}, 错误: {e}")
            return ToolExecutionResult(
                tool_name=name,
                status="error",
                data={},
                display_hints=DisplayHints(),
                summary=f"执行失败: {str(e)}",
                error=str(e)
            )

    @classmethod
    def to_langchain_tools(cls) -> List:
        """
        转换为 LangChain 工具列表（用于 bind_tools）

        Returns:
            LangChain Tool 列表
        """
        tools = []
        for name, metadata in cls._tool_metadata.items():
            tools.append(metadata.to_langchain_tool())
        return tools

    @classmethod
    def get_tools_for_context(cls, context: Dict[str, Any]) -> List[ToolMetadata]:
        """
        根据上下文获取可用工具列表

        Args:
            context: 当前对话上下文

        Returns:
            相关工具元数据列表
        """
        # 目前返回所有工具，后续可以根据 phase/dimension 过滤
        return list(cls._tool_metadata.values())


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

# 初始化 Adapter 工具
_initialize_adapter_tools()


__all__ = ["ToolRegistry"]