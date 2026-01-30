"""
详细规划规划器

包含10个专业规划维度的规划器实现。
充分利用现有基础设施：
- llm_factory.create_llm()
- dimension_mapping.get_full_dependency_chain()
- state_filter.filter_state_for_detailed_dimension_v2()
"""

from typing import Dict, Any
from .base_planner import DimensionPlanner
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 10个详细规划规划器
# ==========================================

class IndustryPlanningPlanner(DimensionPlanner):
    """产业规划规划器"""

    def __init__(self):
        super().__init__("industry", "产业规划")

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import INDUSTRY_PLANNING_PROMPT
        return INDUSTRY_PLANNING_PROMPT

    def build_prompt(self, filtered_state: Dict[str, Any]) -> str:
        """构建产业规划的完整prompt"""
        template = self.get_prompt_template()

        # 从filtered_state获取必要信息
        # 注意：execute()方法已经将project_name和constraints添加到filtered_state
        return template.format(
            project_name=filtered_state.get("_project_name", "村庄"),
            analysis_report=filtered_state.get("filtered_analysis", ""),
            planning_concept=filtered_state.get("filtered_concepts", ""),
            constraints=filtered_state.get("_constraints", "无特殊约束")
        )


class MasterPlanPlanner(DimensionPlanner):
    """村庄总体规划规划器"""

    def __init__(self):
        super().__init__("master_plan", "村庄总体规划")

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import MASTER_PLAN_PROMPT
        return MASTER_PLAN_PROMPT

    def build_prompt(self, filtered_state: Dict[str, Any]) -> str:
        """构建总体规划的完整prompt"""
        template = self.get_prompt_template()
        return template.format(
            project_name=filtered_state.get("_project_name", "村庄"),
            analysis_report=filtered_state.get("filtered_analysis", ""),
            planning_concept=filtered_state.get("filtered_concepts", ""),
            constraints=filtered_state.get("_constraints", "无特殊约束")
        )


class TrafficPlanningPlanner(DimensionPlanner):
    """道路交通规划规划器"""

    def __init__(self):
        super().__init__("traffic", "道路交通规划")

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import TRAFFIC_PLANNING_PROMPT
        return TRAFFIC_PLANNING_PROMPT

    def build_prompt(self, filtered_state: Dict[str, Any]) -> str:
        """构建道路交通规划的完整prompt"""
        template = self.get_prompt_template()
        return template.format(
            project_name=filtered_state.get("_project_name", "村庄"),
            analysis_report=filtered_state.get("filtered_analysis", ""),
            planning_concept=filtered_state.get("filtered_concepts", ""),
            constraints=filtered_state.get("_constraints", "无特殊约束")
        )


class PublicServicePlanner(DimensionPlanner):
    """公服设施规划规划器"""

    def __init__(self):
        super().__init__("public_service", "公服设施规划")

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import PUBLIC_SERVICE_PROMPT
        return PUBLIC_SERVICE_PROMPT

    def build_prompt(self, filtered_state: Dict[str, Any]) -> str:
        """构建公共服务设施规划的完整prompt"""
        template = self.get_prompt_template()
        return template.format(
            project_name=filtered_state.get("_project_name", "村庄"),
            analysis_report=filtered_state.get("filtered_analysis", ""),
            planning_concept=filtered_state.get("filtered_concepts", ""),
            constraints=filtered_state.get("_constraints", "无特殊约束")
        )


class InfrastructurePlanner(DimensionPlanner):
    """基础设施规划规划器"""

    def __init__(self):
        super().__init__("infrastructure", "基础设施规划")

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import INFRASTRUCTURE_PROMPT
        return INFRASTRUCTURE_PROMPT

    def build_prompt(self, filtered_state: Dict[str, Any]) -> str:
        """构建基础设施规划的完整prompt"""
        template = self.get_prompt_template()
        return template.format(
            project_name=filtered_state.get("_project_name", "村庄"),
            analysis_report=filtered_state.get("filtered_analysis", ""),
            planning_concept=filtered_state.get("filtered_concepts", ""),
            constraints=filtered_state.get("_constraints", "无特殊约束")
        )


class EcologicalPlanningPlanner(DimensionPlanner):
    """生态绿地规划规划器"""

    def __init__(self):
        super().__init__("ecological", "生态绿地规划")

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import ECOLOGICAL_PROMPT
        return ECOLOGICAL_PROMPT

    def build_prompt(self, filtered_state: Dict[str, Any]) -> str:
        """构建生态绿地规划的完整prompt"""
        template = self.get_prompt_template()
        return template.format(
            project_name=filtered_state.get("_project_name", "村庄"),
            analysis_report=filtered_state.get("filtered_analysis", ""),
            planning_concept=filtered_state.get("filtered_concepts", ""),
            constraints=filtered_state.get("_constraints", "无特殊约束")
        )


class DisasterPreventionPlanner(DimensionPlanner):
    """防震减灾规划规划器"""

    def __init__(self):
        super().__init__("disaster_prevention", "防震减灾规划")

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import DISASTER_PREVENTION_PROMPT
        return DISASTER_PREVENTION_PROMPT

    def build_prompt(self, filtered_state: Dict[str, Any]) -> str:
        """构建防震减灾规划的完整prompt"""
        template = self.get_prompt_template()
        return template.format(
            project_name=filtered_state.get("_project_name", "村庄"),
            analysis_report=filtered_state.get("filtered_analysis", ""),
            planning_concept=filtered_state.get("filtered_concepts", ""),
            constraints=filtered_state.get("_constraints", "无特殊约束")
        )


class HeritagePlanner(DimensionPlanner):
    """历史文保规划规划器"""

    def __init__(self):
        super().__init__("heritage", "历史文保规划")

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import HERITAGE_PROMPT
        return HERITAGE_PROMPT

    def build_prompt(self, filtered_state: Dict[str, Any]) -> str:
        """构建历史文保规划的完整prompt"""
        template = self.get_prompt_template()
        return template.format(
            project_name=filtered_state.get("_project_name", "村庄"),
            analysis_report=filtered_state.get("filtered_analysis", ""),
            planning_concept=filtered_state.get("filtered_concepts", ""),
            constraints=filtered_state.get("_constraints", "无特殊约束")
        )


class LandscapePlanner(DimensionPlanner):
    """村庄风貌指引规划器"""

    def __init__(self):
        super().__init__("landscape", "村庄风貌指引")

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import LANDSCAPE_PROMPT
        return LANDSCAPE_PROMPT

    def build_prompt(self, filtered_state: Dict[str, Any]) -> str:
        """构建村庄风貌指引的完整prompt"""
        template = self.get_prompt_template()
        return template.format(
            project_name=filtered_state.get("_project_name", "村庄"),
            analysis_report=filtered_state.get("filtered_analysis", ""),
            planning_concept=filtered_state.get("filtered_concepts", ""),
            constraints=filtered_state.get("_constraints", "无特殊约束")
        )


class ProjectBankPlanner(DimensionPlanner):
    """建设项目库规划器"""

    def __init__(self):
        super().__init__("project_bank", "建设项目库")

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import PROJECT_BANK_PROMPT
        return PROJECT_BANK_PROMPT

    def build_prompt(self, filtered_state: Dict[str, Any]) -> str:
        """构建建设项目库的完整prompt"""
        template = self.get_prompt_template()

        # 项目库需要包含前序详细规划（如果有的话）
        detailed_plans_text = ""
        filtered_detailed = filtered_state.get("filtered_detailed", {})
        if filtered_detailed:
            from ..core.dimension_mapping import DETAILED_DIMENSION_NAMES
            for dim_key, dim_result in filtered_detailed.items():
                dim_name = DETAILED_DIMENSION_NAMES.get(dim_key, dim_key)
                detailed_plans_text += f"\n\n### {dim_name}\n\n{dim_result}\n"

        return template.format(
            project_name=filtered_state.get("_project_name", "村庄"),
            analysis_report=filtered_state.get("filtered_analysis", ""),
            planning_concept=filtered_state.get("filtered_concepts", ""),
            constraints=filtered_state.get("_constraints", "无特殊约束"),
            detailed_plans=detailed_plans_text or "（无前序详细规划）"
        )

    def _filter_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        项目库需要特殊的状态筛选：包含前序维度的规划结果

        重写父类方法以处理前序详细规划
        """
        # 使用父类的方法获取基础筛选结果
        filtered = super()._filter_state(state)

        # 项目库需要包含所有前序详细规划
        completed_plans = state.get("completed_plans", {})
        if completed_plans:
            # 将前序规划添加到filtered_detailed
            filtered_detailed = filtered.get("filtered_detailed", {})
            for dim_key, dim_result in completed_plans.items():
                if dim_key not in filtered_detailed:
                    filtered_detailed[dim_key] = dim_result

            filtered["filtered_detailed"] = filtered_detailed
            logger.info(f"[ProjectBankPlanner] 包含了 {len(filtered_detailed)} 个前序详细规划")

        return filtered


# ==========================================
# 规划器工厂
# ==========================================

class DetailedPlannerFactory:
    """
    详细规划规划器工厂类

    根据维度名称创建对应的规划器实例
    """

    _PLANNER_CLASSES = {
        "industry": IndustryPlanningPlanner,
        "master_plan": MasterPlanPlanner,
        "traffic": TrafficPlanningPlanner,
        "public_service": PublicServicePlanner,
        "infrastructure": InfrastructurePlanner,
        "ecological": EcologicalPlanningPlanner,
        "disaster_prevention": DisasterPreventionPlanner,
        "heritage": HeritagePlanner,
        "landscape": LandscapePlanner,
        "project_bank": ProjectBankPlanner
    }

    @classmethod
    def create_planner(cls, dimension: str) -> DimensionPlanner:
        """
        根据维度名称创建对应的规划器

        Args:
            dimension: 维度标识（如 "industry"）

        Returns:
            DimensionPlanner实例

        Raises:
            ValueError: 如果维度不存在
        """
        planner_class = cls._PLANNER_CLASSES.get(dimension)

        if not planner_class:
            raise ValueError(f"未找到维度 '{dimension}' 的规划器类")

        return planner_class()

    @classmethod
    def get_all_planners(cls) -> Dict[str, DimensionPlanner]:
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
    def get_planners_by_wave(cls, wave: int) -> list:
        """
        获取指定波次的所有规划器

        Args:
            wave: 波次编号 (1 或 2)

        Returns:
            规划器列表
        """
        from ..core.dimension_mapping import get_dimensions_by_wave

        dimensions = get_dimensions_by_wave(wave)
        return [cls.create_planner(d) for d in dimensions]


__all__ = [
    "IndustryPlanningPlanner",
    "MasterPlanPlanner",
    "TrafficPlanningPlanner",
    "PublicServicePlanner",
    "InfrastructurePlanner",
    "EcologicalPlanningPlanner",
    "DisasterPreventionPlanner",
    "HeritagePlanner",
    "LandscapePlanner",
    "ProjectBankPlanner",
    "DetailedPlannerFactory",
]
