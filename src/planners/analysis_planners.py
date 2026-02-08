"""
现状分析规划器

包含12个现状分析维度的规划器实现。
使用统一基类 UnifiedPlannerBase 消除重复代码。
"""

from typing import Dict, Any, Optional
from .unified_base_planner import UnifiedPlannerBase
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 现状分析规划器基类
# ==========================================

class BaseAnalysisPlanner(UnifiedPlannerBase):
    """
    现状分析规划器基类

    特点：
    - 每个planner只接收raw_data（村庄原始数据）
    - 不需要状态筛选（第一层，没有前置依赖）
    - 直接使用get_dimension_prompt(dimension_key, raw_data)获取prompt
    - 使用统一基类处理LLM调用、错误处理、LangSmith tracing
    """

    def validate_state(self, state: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证状态是否包含必需的字段

        Args:
            state: 当前状态字典

        Returns:
            (is_valid, error_message)
        """
        if "raw_data" not in state:
            return False, "缺少必需字段: raw_data"

        raw_data = state.get("raw_data", "")
        if not raw_data or not raw_data.strip():
            return False, "raw_data 为空"

        return True, None

    def build_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建完整的prompt

        Args:
            state: 当前状态字典（已通过验证）

        Returns:
            完整的prompt字符串
        """
        from ..subgraphs.analysis_prompts import get_dimension_prompt
        raw_data = state.get("raw_data", "")
        return get_dimension_prompt(self.dimension_key, raw_data)

    def get_layer(self) -> int:
        """返回规划层级：1 = 现状分析"""
        return 1

    def get_result_key(self) -> str:
        """返回结果字典的键名"""
        return "analysis_result"


# ==========================================
# 12个现状分析规划器
# ==========================================

class LocationAnalysisPlanner(BaseAnalysisPlanner):
    """区位与对外交通分析规划器"""

    def __init__(self):
        super().__init__("location", "区位与对外交通分析")


class SocioEconomicAnalysisPlanner(BaseAnalysisPlanner):
    """社会经济分析规划器"""

    def __init__(self):
        super().__init__("socio_economic", "社会经济分析")


class VillagerWishesAnalysisPlanner(BaseAnalysisPlanner):
    """村民意愿与诉求分析规划器"""

    def __init__(self):
        super().__init__("villager_wishes", "村民意愿与诉求分析")


class SuperiorPlanningAnalysisPlanner(BaseAnalysisPlanner):
    """上位规划与政策导向分析规划器"""

    def __init__(self):
        super().__init__("superior_planning", "上位规划与政策导向分析")


class NaturalEnvironmentAnalysisPlanner(BaseAnalysisPlanner):
    """自然环境分析规划器"""

    def __init__(self):
        super().__init__("natural_environment", "自然环境分析")


class LandUseAnalysisPlanner(BaseAnalysisPlanner):
    """土地利用分析规划器"""

    def __init__(self):
        super().__init__("land_use", "土地利用分析")


class TrafficAnalysisPlanner(BaseAnalysisPlanner):
    """道路交通分析规划器"""

    def __init__(self):
        super().__init__("traffic", "道路交通分析")


class PublicServicesAnalysisPlanner(BaseAnalysisPlanner):
    """公共服务设施分析规划器"""

    def __init__(self):
        super().__init__("public_services", "公共服务设施分析")


class InfrastructureAnalysisPlanner(BaseAnalysisPlanner):
    """基础设施分析规划器"""

    def __init__(self):
        super().__init__("infrastructure", "基础设施分析")


class EcologicalGreenAnalysisPlanner(BaseAnalysisPlanner):
    """生态绿地分析规划器"""

    def __init__(self):
        super().__init__("ecological_green", "生态绿地分析")


class ArchitectureAnalysisPlanner(BaseAnalysisPlanner):
    """建筑分析规划器"""

    def __init__(self):
        super().__init__("architecture", "建筑分析")


class HistoricalCultureAnalysisPlanner(BaseAnalysisPlanner):
    """历史文化与乡愁保护分析规划器"""

    def __init__(self):
        super().__init__("historical_culture", "历史文化与乡愁保护分析")


# ==========================================
# 规划器工厂
# ==========================================

class AnalysisPlannerFactory:
    """
    现状分析规划器工厂类

    根据维度名称创建对应的规划器实例
    """

    _PLANNER_CLASSES = {
        "location": LocationAnalysisPlanner,
        "socio_economic": SocioEconomicAnalysisPlanner,
        "villager_wishes": VillagerWishesAnalysisPlanner,
        "superior_planning": SuperiorPlanningAnalysisPlanner,
        "natural_environment": NaturalEnvironmentAnalysisPlanner,
        "land_use": LandUseAnalysisPlanner,
        "traffic": TrafficAnalysisPlanner,
        "public_services": PublicServicesAnalysisPlanner,
        "infrastructure": InfrastructureAnalysisPlanner,
        "ecological_green": EcologicalGreenAnalysisPlanner,
        "architecture": ArchitectureAnalysisPlanner,
        "historical_culture": HistoricalCultureAnalysisPlanner
    }

    @classmethod
    def create_planner(cls, dimension: str) -> BaseAnalysisPlanner:
        """
        根据维度名称创建对应的规划器

        Args:
            dimension: 维度标识（如 "location"）

        Returns:
            BaseAnalysisPlanner实例

        Raises:
            ValueError: 如果维度不存在
        """
        planner_class = cls._PLANNER_CLASSES.get(dimension)

        if not planner_class:
            raise ValueError(f"未找到维度 '{dimension}' 的分析规划器类")

        return planner_class()

    @classmethod
    def get_all_planners(cls) -> Dict[str, BaseAnalysisPlanner]:
        """
        获取所有规划器实例

        Returns:
            维度标识 -> 规划器实例 的字典
        """
        return {
            dimension: cls.create_planner(dimension)
            for dimension in cls._PLANNER_CLASSES.keys()
        }

    @classmethod
    def list_dimensions(cls) -> list:
        """列出所有分析维度"""
        return list(cls._PLANNER_CLASSES.keys())


__all__ = [
    "BaseAnalysisPlanner",
    "LocationAnalysisPlanner",
    "SocioEconomicAnalysisPlanner",
    "VillagerWishesAnalysisPlanner",
    "SuperiorPlanningAnalysisPlanner",
    "NaturalEnvironmentAnalysisPlanner",
    "LandUseAnalysisPlanner",
    "TrafficAnalysisPlanner",
    "PublicServicesAnalysisPlanner",
    "InfrastructureAnalysisPlanner",
    "EcologicalGreenAnalysisPlanner",
    "ArchitectureAnalysisPlanner",
    "HistoricalCultureAnalysisPlanner",
    "AnalysisPlannerFactory",
]
