"""
规划思路规划器

包含4个规划思路维度的规划器实现。
充分利用现有基础设施：
- llm_factory.create_llm()
- state_filter.filter_analysis_report_for_concept()
"""

from typing import Dict, Any
from abc import ABC
from langchain_core.messages import HumanMessage

from ..core.llm_factory import create_llm
from ..utils.state_filter import filter_analysis_report_for_concept
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 规划思路规划器基类
# ==========================================

class BaseConceptPlanner(ABC):
    """
    规划思路规划器基类

    特点：
    - 接收analysis_report（完整报告）和dimension_reports（维度报告字典）
    - 使用filter_analysis_report_for_concept()筛选相关维度
    - 根据依赖关系只获取需要的分析维度
    """

    def __init__(self, dimension_key: str, dimension_name: str):
        """
        初始化规划器

        Args:
            dimension_key: 维度标识（如 "resource_endowment"）
            dimension_name: 维度名称（如 "资源禀赋分析"）
        """
        self.dimension_key = dimension_key
        self.dimension_name = dimension_name

    def get_prompt_template(self) -> str:
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

    def build_prompt(self, filtered_analysis: str, task_description: str, constraints: str) -> str:
        """
        构建完整的prompt

        Args:
            filtered_analysis: 已筛选的现状分析报告
            task_description: 规划任务描述
            constraints: 约束条件

        Returns:
            完整的prompt字符串
        """
        template = self.get_prompt_template()
        return template.format(
            analysis_report=filtered_analysis,
            task_description=task_description,
            constraints=constraints
        )

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行该维度的规划思路分析

        流程：
        1. 使用state_filter筛选状态
        2. 构建prompt
        3. 调用LLM（支持LangSmith tracing）
        4. 返回结果

        Args:
            state: 完整的状态字典，必须包含：
                - analysis_report: 完整现状分析报告
                - dimension_reports: 维度报告字典
                - task_description: 规划任务描述
                - constraints: 约束条件

        Returns:
            {
                "dimension_key": str,
                "dimension_name": str,
                "concept_result": str  # 生成的规划思路内容
            }
        """
        logger.info(f"[ConceptPlanner] 执行 {self.dimension_name}")

        # 1. 筛选状态（使用现有state_filter）
        filtered_analysis = self._filter_state(state)

        # 2. 构建prompt
        task_description = state.get("task_description", "制定村庄总体规划思路")
        constraints = state.get("constraints", "无特殊约束")
        prompt = self.build_prompt(filtered_analysis, task_description, constraints)

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
                        layer=2  # 规划思路层级
                    )
            except Exception as e:
                logger.debug(f"[ConceptPlanner] LangSmith metadata创建失败: {e}")
                metadata = None

            llm = create_llm(
                model="glm-4-flash",
                temperature=0.7,
                max_tokens=2000,
                metadata=metadata
            )
            response = llm.invoke([HumanMessage(content=prompt)])
            result = response.content

            logger.info(f"[ConceptPlanner] {self.dimension_name} 完成，长度: {len(result)}")

            return {
                "dimension_key": self.dimension_key,
                "dimension_name": self.dimension_name,
                "concept_result": result
            }

        except Exception as e:
            logger.error(f"[ConceptPlanner] {self.dimension_name} 执行失败: {e}")
            return {
                "dimension_key": self.dimension_key,
                "dimension_name": self.dimension_name,
                "concept_result": f"[执行失败] {str(e)}"
            }

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

        logger.info(f"[ConceptPlanner] {self.dimension_name} 状态筛选完成")

        return filtered

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.dimension_key}/{self.dimension_name})"


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
