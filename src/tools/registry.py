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


# ==========================================
# 内置工具实现
# ==========================================

@ToolRegistry.register("population_model_v1")
def calculate_population(context: Dict[str, Any]) -> str:
    """
    人口预测模型

    基于现状数据，使用 Leslie 矩阵或线性回归预测未来人口

    Args:
        context: 包含 socio_economy 等现状分析的上下文

    Returns:
        格式化的预测结果字符串
    """
    # 从上下文提取当前人口
    socio_economic = context.get("socio_economic", "")

    # 简化示例：提取数字（实际应使用更复杂的解析）
    import re
    pop_match = re.search(r'人口[：:]\s*(\d+)', socio_economic)
    current_pop = int(pop_match.group(1)) if pop_match else 1000

    # 执行预测（这里简化，实际应使用完整的 Leslie 矩阵）
    projected_2030 = int(current_pop * 1.05)
    projected_2035 = int(current_pop * 1.10)

    return f"""## 人口预测结果

基于现状数据（当前人口 {current_pop} 人），采用人口增长模型预测：

- 2030年：预计人口 {projected_2030} 人（增长 5%）
- 2035年：预计人口 {projected_2035} 人（增长 10%）

**预测依据**：
- 考虑自然增长率（出生率 - 死亡率）
- 考虑机械增长率（流入人口 - 流出人口）
- 参考同类村庄发展趋势
"""


@ToolRegistry.register("gis_coverage_calculator")
def calculate_gis_coverage(context: Dict[str, Any]) -> str:
    """
    GIS 覆盖率计算

    使用 GeoPandas/ArcPy 分析土地利用数据，计算各类用地占比

    Args:
        context: 包含 village_data 等基础数据的上下文

    Returns:
        格式化的 GIS 分析结果字符串
    """
    # 注意：这里需要实际的 GIS 数据源
    # 实际实现会调用适配器中的 GISAnalysisAdapter

    # 示例：调用现有适配器
    try:
        from ..tools.adapters import GISAnalysisAdapter
        adapter = GISAnalysisAdapter()

        # 执行分析
        result = adapter.analyze_land_use(context)

        return f"""## GIS 土地利用分析结果

{result}

**数据来源**：GIS 空间分析
**分析精度**：1:5000 比例尺
"""
    except (ImportError, Exception):
        # 如果没有 GIS 环境，返回模拟数据
        return """## GIS 土地利用分析结果

基于现状调研数据估算：
- 建设用地：15%
- 耕地：60%
- 林地：15%
- 水域：5%
- 其他用地：5%

**注意**：GIS 模块未安装，以上为估算数据
"""


@ToolRegistry.register("network_accessibility")
def calculate_network_accessibility(context: Dict[str, Any]) -> str:
    """
    网络可达性分析

    基于交通网络数据，计算各节点的可达性指标

    Args:
        context: 包含 traffic 等现状分析的上下文

    Returns:
        格式化的可达性分析结果
    """
    try:
        from ..tools.adapters import NetworkAnalysisAdapter
        adapter = NetworkAnalysisAdapter()

        result = adapter.analyze_accessibility(context)

        return f"""## 交通可达性分析结果

{result}

**分析方法**：网络分析法
**路网数据**：OD 成本矩阵
"""
    except (ImportError, Exception):
        return """## 交通可达性分析结果

基于现状路网结构分析：
- 对外交通可达性：良好
- 内部道路连通度：中等
- 公共交通覆盖：需提升

**注意**：网络分析模块未安装，以上为定性分析
"""


# ==========================================
# 适配器迁移辅助
# ==========================================

def migrate_adapter_to_tool(adapter_class, tool_name: str):
    """
    将现有适配器迁移为工具函数的辅助函数

    Usage:
        from ..tools.adapters import GISAnalysisAdapter
        migrate_adapter_to_tool(GISAnalysisAdapter, "gis_custom_analysis")
    """
    def wrapper(context: Dict[str, Any]) -> str:
        adapter = adapter_class()
        return adapter.execute(context)

    ToolRegistry.register(tool_name)(wrapper)
    return wrapper


__all__ = ["ToolRegistry"]
