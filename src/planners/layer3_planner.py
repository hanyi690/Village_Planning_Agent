"""
Layer 3 详细规划器 - 使用 Python Code-First 模式

这是一个轻量级的包装器，直接从 detailed_plan_prompts.py 加载 prompts，
而不是从 YAML 配置文件加载。

优势：
1. 支持复杂的数据格式化（JSON 表格、统计数据等）
2. 代码可读性高，易于维护
3. 与 Layer 1 和 Layer 2 保持一致的架构
"""

from typing import Any, Dict, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from .unified_base_planner import UnifiedPlannerBase
from ..utils.logger import get_logger
from ..utils.state_filter import filter_state_for_detailed_dimension_v2
from ..subgraphs.detailed_plan_prompts import get_dimension_prompt

logger = get_logger(__name__)


class Layer3Planner(UnifiedPlannerBase):
    """
    Layer 3 详细规划器 - 使用 Python prompts

    特性:
    1. 直接从 detailed_plan_prompts.py 加载 prompts
    2. 支持状态筛选和 RAG
    3. 支持适配器调用
    4. 轻量级接口，易于维护和扩展
    """

    def __init__(self, dimension_key: str, dimension_name: str):
        """
        初始化 Layer 3 规划器

        Args:
            dimension_key: 维度标识（如 "industry", "traffic"）
            dimension_name: 维度名称（如 "产业规划", "道路交通规划"）
        """
        # 初始化基类
        super().__init__(
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            rag_enabled=True  # Layer 3 启用 RAG
        )

    def validate_state(self, state: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证状态

        Layer 3 需要检查：
        - analysis_report
        - planning_concept
        - dependencies（可选）
        """
        required_fields = ["analysis_report", "planning_concept"]
        for field in required_fields:
            if field not in state:
                return False, f"缺少必需字段: {field}"

        return True, None

    def build_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建 Prompt

        使用 detailed_plan_prompts.py 中的 get_dimension_prompt 函数
        """
        # 使用状态筛选函数
        filtered = filter_state_for_detailed_dimension_v2(
            detailed_dimension=self.dimension_key,
            full_analysis_reports=state.get("dimension_reports"),
            full_analysis_report=state["analysis_report"],
            full_concept_reports=state.get("concept_dimension_reports"),
            full_concept_report=state["planning_concept"],
            completed_detailed_reports=state.get("completed_plans", {})
        )

        # 使用 detailed_plan_prompts.py 中的函数构建 prompt
        prompt_content = get_dimension_prompt(
            dimension_key=self.dimension_key,
            project_name=state.get("project_name", "村庄"),
            analysis_report=filtered.get("filtered_analysis", ""),
            planning_concept=filtered.get("filtered_concepts", ""),
            constraints=state.get("constraints", "无特殊约束")
        )

        # 特殊处理 project_bank 需要前序规划
        if self.dimension_key == "project_bank":
            dimension_plans = self._format_detailed_plans(
                state.get("completed_plans", {})
            )
            # 替换 prompt 中的 {dimension_plans} 占位符
            prompt_content = prompt_content.replace("{dimension_plans}", dimension_plans)

        return prompt_content

    def _format_detailed_plans(self, plans: Dict[str, str]) -> str:
        """格式化详细规划结果（用于 project_bank）"""
        from ..core.dimension_config import DETAILED_DIMENSION_NAMES

        formatted = []
        for key, content in plans.items():
            name = DETAILED_DIMENSION_NAMES().get(key, key)
            formatted.append(f"## {name}\n\n{content}\n")

        return "\n".join(formatted)

    def get_layer(self) -> int:
        """返回规划层级"""
        return 3

    def get_result_key(self) -> str:
        """返回结果字典的键名"""
        return "dimension_result"


class Layer3PlannerFactory:
    """
    Layer 3 规划器工厂

    用于创建 Layer 3 规划器实例
    """

    @classmethod
    def create_planner(cls, dimension_key: str, dimension_name: Optional[str] = None) -> Layer3Planner:
        """
        创建指定维度的 Layer 3 规划器

        Args:
            dimension_key: 维度标识（如 "industry", "traffic"）
            dimension_name: 维度名称（可选，如果不提供则从 dimension_key 推断）

        Returns:
            Layer3Planner 实例
        """
        # 如果没有提供 dimension_name，从 detailed_plan_prompts.py 获取
        if dimension_name is None:
            from ..subgraphs.detailed_plan_prompts import list_detailed_dimensions
            dimensions = list_detailed_dimensions()
            for dim in dimensions:
                if dim["key"] == dimension_key:
                    dimension_name = dim["name"]
                    break
            else:
                dimension_name = dimension_key  # 回退到使用 key 作为 name

        return Layer3Planner(dimension_key, dimension_name)


__all__ = ["Layer3Planner", "Layer3PlannerFactory"]