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

    使用村庄规划标准模型: Pn = P0 × (1 + K)^n + M

    Args:
        context: 包含人口相关数据的上下文
            - socio_economic: 社会经济分析文本（提取基期人口）
            - baseline_population: 基期人口（可选，优先使用）
            - baseline_year: 基期年份（可选，默认2024）
            - target_year: 目标年份（可选，默认2035）
            - natural_growth_rate: 自然增长率‰（可选，默认4‰）
            - mechanical_growth: 机械增长人口（可选，默认0）

    Returns:
        格式化的预测结果字符串
    """
    import re
    from datetime import datetime

    # 提取基期人口
    baseline_population = context.get("baseline_population")
    if baseline_population is None:
        # 从 socio_economic 文本中提取
        socio_economic = context.get("socio_economic", "")
        pop_match = re.search(r'(?:户籍)?人口[：:]\s*(\d+)', socio_economic)
        baseline_population = int(pop_match.group(1)) if pop_match else 1000

    # 其他参数
    current_year = datetime.now().year
    baseline_year = context.get("baseline_year", current_year)
    target_year = context.get("target_year", 2035)
    natural_growth_rate = context.get("natural_growth_rate", 4.0)  # ‰
    mechanical_growth = context.get("mechanical_growth", 0)

    try:
        from .adapters.population_adapter import PopulationPredictionAdapter

        adapter = PopulationPredictionAdapter()
        result = adapter.execute(
            analysis_type="village_forecast",
            baseline_population=baseline_population,
            baseline_year=baseline_year,
            target_year=target_year,
            natural_growth_rate=natural_growth_rate,
            mechanical_growth=mechanical_growth,
            intermediate_years=[2030]  # 中间年份
        )

        if result.success:
            data = result.data
            intermediate = data.get("intermediate_results", {})

            return f"""## 人口预测结果

**预测模型**: Pn = P0 × (1 + K)^n + M（村庄规划标准模型）

**基础参数**:
- 基期年份: {data['baseline_year']}年
- 基期人口: {data['baseline_population']}人
- 自然增长率: {data['natural_growth_rate_permillage']}‰
- 机械增长人口: {data['mechanical_growth']}人

**预测结果**:
- 预测年限: {data['forecast_years']}年
- 自然增长系数: {data['natural_growth_factor']}
- **{data['target_year']}年预测人口: {data['forecast_population']}人**
{f"- 2030年预测人口: {intermediate.get(2030, 'N/A')}人" if 2030 in intermediate else ""}

**计算过程**:
P{n} = {baseline_population} × (1 + {natural_growth_rate/1000})^{data['forecast_years']} + {mechanical_growth}
     = {baseline_population} × {data['natural_growth_factor']} + {mechanical_growth}
     = {data['forecast_population']}人
"""
        else:
            logger.warning(f"[population_model_v1] Adapter 预测失败: {result.error}，使用简化模型")
            raise Exception(result.error)

    except Exception as e:
        # 降级到简化模型
        n = target_year - baseline_year
        K = natural_growth_rate / 1000
        forecast_pop = int(baseline_population * ((1 + K) ** n) + mechanical_growth)

        logger.warning(f"[population_model_v1] 使用简化模型（{e}）")

        return f"""## 人口预测结果

**预测模型**: Pn = P0 × (1 + K)^n + M（简化计算）

**基础参数**:
- 基期人口: {baseline_population}人
- 自然增长率: {natural_growth_rate}‰
- 机械增长人口: {mechanical_growth}人

**预测结果**:
- **{target_year}年预测人口: {forecast_pop}人**

**注意**: 适配器不可用，使用简化计算
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
        logger.warning("[gis_coverage_calculator] GIS 模块不可用，返回估算模拟数据")
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
        logger.warning("[network_accessibility] 网络分析模块不可用，返回定性分析（模拟数据）")
        return """## 交通可达性分析结果

基于现状路网结构分析：
- 对外交通可达性：良好
- 内部道路连通度：中等
- 公共交通覆盖：需提升

**注意**：网络分析模块未安装，以上为定性分析
"""


@ToolRegistry.register("knowledge_search")
def knowledge_search_tool(context: Dict[str, Any]) -> str:
    """
    RAG 知识检索工具

    从知识库中检索相关信息，支持专业数据和法规条文的查询。

    Args:
        context: 包含 query 和可选参数的上下文字典
            - query: 查询字符串（必需）
            - top_k: 返回结果数量（可选，默认 5）
            - context_mode: 上下文模式（可选，默认 "standard"）

    Returns:
        格式化的知识检索结果
    """
    try:
        from ..rag.core.tools import knowledge_search_tool as rag_search_tool

        query = context.get("query", "")
        top_k = context.get("top_k", 5)
        context_mode = context.get("context_mode", "standard")

        if not query:
            return "## 知识检索错误\n\n错误: 缺少查询参数 'query'"

        result = rag_search_tool.invoke({
            "query": query,
            "top_k": top_k,
            "context_mode": context_mode
        })

        logger.info(f"[ToolRegistry] 知识检索成功: query='{query[:50]}...'")
        return result

    except Exception as e:
        logger.error(f"[ToolRegistry] 知识检索失败: {e}")
        return f"## 知识检索错误\n\n错误: {str(e)}"


# ==========================================
# 工具初始化
# ==========================================

def _initialize_adapter_tools():
    """
    初始化 Adapter 工具

    尝试使用 wrappers 模块注册所有可用的 Adapter
    """
    from .adapters.wrappers import register_adapter_as_tool, format_population_result, format_gis_result, format_network_result

    # 尝试注册 GIS Adapter
    try:
        from .adapters.gis_adapter import GISAnalysisAdapter
        register_adapter_as_tool(
            GISAnalysisAdapter,
            "gis_analysis",
            adapter_name="GIS 空间分析",
            result_formatter=format_gis_result
        )
    except ImportError:
        logger.debug("[ToolRegistry] GIS Adapter 未安装，跳过注册")

    # 尝试注册 Network Adapter
    try:
        from .adapters.network_adapter import NetworkAnalysisAdapter
        register_adapter_as_tool(
            NetworkAnalysisAdapter,
            "network_analysis",
            adapter_name="交通网络分析",
            result_formatter=format_network_result
        )
    except ImportError:
        logger.debug("[ToolRegistry] Network Adapter 未安装，跳过注册")

    # 尝试注册 Population Adapter
    try:
        from .adapters.population_adapter import PopulationPredictionAdapter
        register_adapter_as_tool(
            PopulationPredictionAdapter,
            "population_prediction",
            adapter_name="人口预测分析",
            result_formatter=format_population_result
        )
    except ImportError:
        logger.debug("[ToolRegistry] Population Adapter 未安装，跳过注册")


# 模块加载时初始化 Adapter 工具
_initialize_adapter_tools()


__all__ = ["ToolRegistry"]
