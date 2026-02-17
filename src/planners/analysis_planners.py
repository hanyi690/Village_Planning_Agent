"""
现状分析规划器

包含12个现状分析维度的规划器实现。
充分利用现有基础设施：
- llm_factory.create_llm()
- analysis_prompts.get_dimension_prompt()
"""

from typing import Dict, Any
from abc import ABC
from langchain_core.messages import HumanMessage

from ..core.llm_factory import create_llm
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 现状分析规划器基类
# ==========================================

class BaseAnalysisPlanner(ABC):
    """
    现状分析规划器基类

    特点：
    - 每个planner只接收raw_data（村庄原始数据）
    - 不需要状态筛选（第一层，没有前置依赖）
    - 直接使用get_dimension_prompt(dimension_key, raw_data)获取prompt
    """

    def __init__(self, dimension_key: str, dimension_name: str):
        """
        初始化规划器

        Args:
            dimension_key: 维度标识（如 "location"）
            dimension_name: 维度名称（如 "区位与对外交通分析"）
        """
        self.dimension_key = dimension_key
        self.dimension_name = dimension_name

    def get_prompt_template(self) -> str:
        """获取Prompt模板"""
        from ..subgraphs.analysis_prompts import get_dimension_prompt
        return get_dimension_prompt(self.dimension_key, "{raw_data}")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行该维度的现状分析

        流程：
        1. 从state获取raw_data
        2. 构建prompt
        3. 调用LLM（支持LangSmith tracing）
        4. 返回结果

        Args:
            state: 完整的状态字典，必须包含 "raw_data"

        Returns:
            {
                "dimension_key": str,
                "dimension_name": str,
                "analysis_result": str  # 生成的分析内容
            }
        """
        logger.info(f"[AnalysisPlanner] 执行 {self.dimension_name}")

        # 1. 获取raw_data
        raw_data = state.get("raw_data", "")
        if not raw_data:
            logger.warning(f"[AnalysisPlanner] {self.dimension_name} 未提供原始数据")
            return {
                "dimension_key": self.dimension_key,
                "dimension_name": self.dimension_name,
                "analysis_result": "[分析失败] 未提供原始数据"
            }

        # 2. 构建prompt
        from ..subgraphs.analysis_prompts import get_dimension_prompt
        prompt = get_dimension_prompt(self.dimension_key, raw_data)

        # 3. 调用LLM（支持LangSmith tracing）
        try:
            # 创建LangSmith metadata（如果启用）
            try:
                from ..core.langsmith_integration import get_langsmith_manager
                langsmith = get_langsmith_manager()
                metadata = None
                if langsmith.is_enabled():
                    metadata = langsmith.create_run_metadata(
                        project_name=state.get("project_name", "村庄"),
                        dimension=self.dimension_key,
                        layer=1  # 现状分析层级
                    )
            except Exception as e:
                logger.debug(f"[AnalysisPlanner] LangSmith metadata创建失败: {e}")
                metadata = None

            llm = create_llm(
                model="glm-4-flash",
                temperature=0.7,
                max_tokens=2000,
                metadata=metadata
            )
            response = llm.invoke([HumanMessage(content=prompt)])
            result = response.content

            logger.info(f"[AnalysisPlanner] {self.dimension_name} 完成，长度: {len(result)}")

            return {
                "dimension_key": self.dimension_key,
                "dimension_name": self.dimension_name,
                "analysis_result": result
            }

        except Exception as e:
            logger.error(f"[AnalysisPlanner] {self.dimension_name} 执行失败: {e}")
            return {
                "dimension_key": self.dimension_key,
                "dimension_name": self.dimension_name,
                "analysis_result": f"[执行失败] {str(e)}"
            }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.dimension_key}/{self.dimension_name})"


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


class HistoricalCulturalAnalysisPlanner(BaseAnalysisPlanner):
    """历史文化分析规划器"""

    def __init__(self):
        super().__init__("historical_cultural", "历史文化分析")


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
        "historical_cultural": HistoricalCulturalAnalysisPlanner
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
    "HistoricalCulturalAnalysisPlanner",
    "AnalysisPlannerFactory",
]
