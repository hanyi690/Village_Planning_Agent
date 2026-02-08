"""
规划思路规划器

包含4个规划思路维度的规划器实现。
使用统一基类 UnifiedPlannerBase 消除重复代码。
"""

from typing import Dict, Any, Optional
from .unified_base_planner import UnifiedPlannerBase
from ..utils.state_filter import filter_analysis_report_for_concept
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 规划思路规划器基类
# ==========================================

class BaseConceptPlanner(UnifiedPlannerBase):
    """
    规划思路规划器基类

    特点：
    - 接收analysis_report（完整报告）和dimension_reports（维度报告字典）
    - 使用filter_analysis_report_for_concept()筛选相关维度
    - 根据依赖关系只获取需要的分析维度
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
        required_fields = ["analysis_report", "task_description", "constraints"]
        for field in required_fields:
            if field not in state:
                return False, f"缺少必需字段: {field}"

        return True, None

    def build_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建完整的prompt

        Args:
            state: 当前状态字典（已通过验证）

        Returns:
            完整的prompt字符串
        """
        # 1. 筛选状态
        filtered_analysis = self._filter_state(state)

        # 2. 获取模板和参数
        template = self._get_prompt_template()
        task_description = state.get("task_description", "制定村庄总体规划思路")
        constraints = state.get("constraints", "无特殊约束")

        # 3. 构建完整prompt
        return template.format(
            analysis_report=filtered_analysis,
            task_description=task_description,
            constraints=constraints
        )

    def get_layer(self) -> int:
        """返回规划层级：2 = 规划思路"""
        return 2

    def get_result_key(self) -> str:
        """返回结果字典的键名"""
        return "concept_result"

    def _get_prompt_template(self) -> str:
        """获取Prompt模板"""
        from ..subgraphs.concept_prompts import (
            RESOURCE_ENDOWMENT_PROMPT,
            PLANNING_POSITIONING_PROMPT,
            DEVELOPMENT_GOALS_PROMPT,
            PLANNING_STRATEGIES_PROMPT,
        )

        prompts_map = {
            "resource_endowment": RESOURCE_ENDOWMENT_PROMPT,
            "planning_positioning": PLANNING_POSITIONING_PROMPT,
            "development_goals": DEVELOPMENT_GOALS_PROMPT,
            "planning_strategies": PLANNING_STRATEGIES_PROMPT,
        }

        return prompts_map.get(self.dimension_key, "")

    def _filter_state(self, state: Dict[str, Any]) -> str:
        """
        使用state_filter筛选状态（私有方法）

        子类可以重写此方法以自定义筛选逻辑。

        Args:
            state: 完整的状态字典

        Returns:
            筛选后的现状分析报告字符串
        """
        full_dimension_reports = state.get("dimension_reports", {})
        full_analysis_report = state.get("analysis_report", "")

        # 使用现有的筛选逻辑
        filtered = filter_analysis_report_for_concept(
            concept_dimension=self.dimension_key,
            full_analysis_reports=full_dimension_reports,
            full_analysis_report=full_analysis_report
        )

        logger.debug(f"[{self.dimension_name}] 状态筛选完成")

        return filtered


# ==========================================
# 4个规划思路规划器
# ==========================================

class ResourceEndowmentPlanner(BaseConceptPlanner):
    """资源禀赋分析规划器"""

    def __init__(self):
        super().__init__("resource_endowment", "资源禀赋分析")


class PlanningPositioningPlanner(BaseConceptPlanner):
    """规划定位分析规划器"""

    def __init__(self):
        super().__init__("planning_positioning", "规划定位分析")


class DevelopmentGoalsPlanner(BaseConceptPlanner):
    """发展目标分析规划器"""

    def __init__(self):
        super().__init__("development_goals", "发展目标分析")


class PlanningStrategiesPlanner(BaseConceptPlanner):
    """规划策略分析规划器"""

    def __init__(self):
        super().__init__("planning_strategies", "规划策略分析")


# ==========================================
# 规划器工厂
# ==========================================

class ConceptPlannerFactory:
    """
    规划思路规划器工厂类

    根据维度名称创建对应的规划器实例
    """

    _PLANNER_CLASSES = {
        "resource_endowment": ResourceEndowmentPlanner,
        "planning_positioning": PlanningPositioningPlanner,
        "development_goals": DevelopmentGoalsPlanner,
        "planning_strategies": PlanningStrategiesPlanner
    }

    @classmethod
    def create_planner(cls, dimension: str) -> BaseConceptPlanner:
        """
        根据维度名称创建对应的规划器

        Args:
            dimension: 维度标识（如 "resource_endowment"）

        Returns:
            BaseConceptPlanner实例

        Raises:
            ValueError: 如果维度不存在
        """
        planner_class = cls._PLANNER_CLASSES.get(dimension)

        if not planner_class:
            raise ValueError(f"未找到维度 '{dimension}' 的规划思路规划器类")

        return planner_class()

    @classmethod
    def get_all_planners(cls) -> Dict[str, BaseConceptPlanner]:
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
        """列出所有规划思路维度"""
        return list(cls._PLANNER_CLASSES.keys())


__all__ = [
    "BaseConceptPlanner",
    "ResourceEndowmentPlanner",
    "PlanningPositioningPlanner",
    "DevelopmentGoalsPlanner",
    "PlanningStrategiesPlanner",
    "ConceptPlannerFactory",
]
