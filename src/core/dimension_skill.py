"""
维度分析Skill基类和实现

将基础维度逻辑封装为可复用的Skill组件，支持：
1. 依赖关系定义
2. 状态筛选
3. 执行逻辑
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
from ..utils.logger import get_logger

logger = get_logger(__name__)


class DimensionSkill(ABC):
    """
    维度规划Skill基类

    每个详细规划维度继承此类并实现抽象方法。
    """

    def __init__(self, dimension_key: str, dimension_name: str):
        """
        初始化Skill

        Args:
            dimension_key: 维度标识（如 "industry"）
            dimension_name: 维度名称（如 "产业规划"）
        """
        self.dimension_key = dimension_key
        self.dimension_name = dimension_name

    @abstractmethod
    def get_dependencies(self) -> Dict[str, Any]:
        """
        获取该维度的依赖关系

        Returns:
            {
                "layer1_analyses": List[str],  # 依赖的现状分析维度
                "layer2_concepts": List[str],  # 依赖的规划思路维度
                "wave": int,                   # 执行波次
                "depends_on_detailed": List[str]  # 依赖的其他详细规划维度
            }
        """
        pass

    @abstractmethod
    def get_prompt_template(self) -> str:
        """
        获取该维度的Prompt模板

        Returns:
            Prompt模板字符串
        """
        pass

    def prepare_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        准备执行所需的状态（可选重写）

        默认实现：直接返回传入的状态
        子类可以重写此方法来进行额外的状态预处理

        Args:
            state: 原始状态

        Returns:
            处理后的状态
        """
        return state

    @abstractmethod
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行该维度的规划生成

        Args:
            state: 包含所有必要信息的状态字典

        Returns:
            {
                "dimension_key": str,
                "dimension_name": str,
                "dimension_result": str  # 生成的规划内容
            }
        """
        pass

    def execute_with_feedback(
        self,
        state: Dict[str, Any],
        feedback: str,
        original_result: str,
        revision_count: int = 0
    ) -> str:
        """
        基于反馈重新执行skill（用于修复流程）

        Args:
            state: 当前状态字典
            feedback: 人工反馈
            original_result: 原始执行结果
            revision_count: 修复次数（用于追踪修复轮数）

        Returns:
            修复后的结果字符串
        """
        logger.info(f"[{self.dimension_name}] 基于反馈重新执行 (第{revision_count + 1}次)")

        # 构建修复prompt
        revision_prompt = f"""
请根据以下人工反馈，修复对应的规划内容：

【原规划内容】
{original_result[:2000]}

【人工反馈】
{feedback}

【要求】
1. 针对反馈意见进行修改
2. 保持原有结构和格式
3. 修改部分要明确标注
4. 这是第{revision_count + 1}次修复
5. 如果这是多次修复，请确保之前的问题都已解决

请生成修复后的规划内容：
"""

        try:
            from ..core.llm_factory import create_llm
            from ..core.config import LLM_MODEL, MAX_TOKENS

            llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)

            result = llm.invoke(revision_prompt)
            revised_content = result.content

            logger.info(f"[{self.dimension_name}] 修复完成，内容长度: {len(revised_content)}")

            return revised_content

        except Exception as e:
            logger.error(f"[{self.dimension_name}] 修复失败: {e}")
            # 返回原始结果
            return original_result

    def validate_dependencies(self, completed_dimensions: List[str]) -> bool:
        """
        验证依赖是否满足

        Args:
            completed_dimensions: 已完成的维度列表

        Returns:
            True 如果依赖满足，False 否则
        """
        deps = self.get_dependencies()
        depends_on = deps.get("depends_on_detailed", [])

        if not depends_on:
            return True

        return all(d in completed_dimensions for d in depends_on)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.dimension_key}/{self.dimension_name})"


# ==========================================
# 具体Skill实现（示例）
# ==========================================

class IndustryPlanningSkill(DimensionSkill):
    """产业规划Skill"""

    def __init__(self):
        super().__init__("industry", "产业规划")

    def get_dependencies(self) -> Dict[str, Any]:
        from .dimension_mapping import FULL_DEPENDENCY_CHAIN
        return FULL_DEPENDENCY_CHAIN.get("industry", {})

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import INDUSTRY_PLANNING_PROMPT
        return INDUSTRY_PLANNING_PROMPT

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行产业规划生成

        注意：此实现为示例，实际执行逻辑在 detailed_plan_subgraph.py 中
        """
        logger.info(f"[Skill] 执行 {self.dimension_name}")

        # 这里应该调用LLM生成规划
        # 但实际实现在 detailed_plan_subgraph.py 的 generate_dimension_plan 中
        # 此Skill主要用于定义依赖关系和元数据

        return {
            "dimension_key": self.dimension_key,
            "dimension_name": self.dimension_name,
            "dimension_result": ""
        }


class MasterPlanSkill(DimensionSkill):
    """村庄总体规划Skill"""

    def __init__(self):
        super().__init__("master_plan", "村庄总体规划")

    def get_dependencies(self) -> Dict[str, Any]:
        from .dimension_mapping import FULL_DEPENDENCY_CHAIN
        return FULL_DEPENDENCY_CHAIN.get("master_plan", {})

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import MASTER_PLAN_PROMPT
        return MASTER_PLAN_PROMPT

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[Skill] 执行 {self.dimension_name}")
        return {
            "dimension_key": self.dimension_key,
            "dimension_name": self.dimension_name,
            "dimension_result": ""
        }


class TrafficPlanningSkill(DimensionSkill):
    """道路交通规划Skill"""

    def __init__(self):
        super().__init__("traffic", "道路交通规划")

    def get_dependencies(self) -> Dict[str, Any]:
        from .dimension_mapping import FULL_DEPENDENCY_CHAIN
        return FULL_DEPENDENCY_CHAIN.get("traffic", {})

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import TRAFFIC_PLANNING_PROMPT
        return TRAFFIC_PLANNING_PROMPT

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[Skill] 执行 {self.dimension_name}")
        return {
            "dimension_key": self.dimension_key,
            "dimension_name": self.dimension_name,
            "dimension_result": ""
        }


class PublicServiceSkill(DimensionSkill):
    """公服设施规划Skill"""

    def __init__(self):
        super().__init__("public_service", "公服设施规划")

    def get_dependencies(self) -> Dict[str, Any]:
        from .dimension_mapping import FULL_DEPENDENCY_CHAIN
        return FULL_DEPENDENCY_CHAIN.get("public_service", {})

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import PUBLIC_SERVICE_PROMPT
        return PUBLIC_SERVICE_PROMPT

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[Skill] 执行 {self.dimension_name}")
        return {
            "dimension_key": self.dimension_key,
            "dimension_name": self.dimension_name,
            "dimension_result": ""
        }


class InfrastructureSkill(DimensionSkill):
    """基础设施规划Skill"""

    def __init__(self):
        super().__init__("infrastructure", "基础设施规划")

    def get_dependencies(self) -> Dict[str, Any]:
        from .dimension_mapping import FULL_DEPENDENCY_CHAIN
        return FULL_DEPENDENCY_CHAIN.get("infrastructure", {})

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import INFRASTRUCTURE_PROMPT
        return INFRASTRUCTURE_PROMPT

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[Skill] 执行 {self.dimension_name}")
        return {
            "dimension_key": self.dimension_key,
            "dimension_name": self.dimension_name,
            "dimension_result": ""
        }


class EcologicalPlanningSkill(DimensionSkill):
    """生态绿地规划Skill"""

    def __init__(self):
        super().__init__("ecological", "生态绿地规划")

    def get_dependencies(self) -> Dict[str, Any]:
        from .dimension_mapping import FULL_DEPENDENCY_CHAIN
        return FULL_DEPENDENCY_CHAIN.get("ecological", {})

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import ECOLOGICAL_PROMPT
        return ECOLOGICAL_PROMPT

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[Skill] 执行 {self.dimension_name}")
        return {
            "dimension_key": self.dimension_key,
            "dimension_name": self.dimension_name,
            "dimension_result": ""
        }


class DisasterPreventionSkill(DimensionSkill):
    """防震减灾规划Skill"""

    def __init__(self):
        super().__init__("disaster_prevention", "防震减灾规划")

    def get_dependencies(self) -> Dict[str, Any]:
        from .dimension_mapping import FULL_DEPENDENCY_CHAIN
        return FULL_DEPENDENCY_CHAIN.get("disaster_prevention", {})

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import DISASTER_PREVENTION_PROMPT
        return DISASTER_PREVENTION_PROMPT

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[Skill] 执行 {self.dimension_name}")
        return {
            "dimension_key": self.dimension_key,
            "dimension_name": self.dimension_name,
            "dimension_result": ""
        }


class HeritageSkill(DimensionSkill):
    """历史文保规划Skill"""

    def __init__(self):
        super().__init__("heritage", "历史文保规划")

    def get_dependencies(self) -> Dict[str, Any]:
        from .dimension_mapping import FULL_DEPENDENCY_CHAIN
        return FULL_DEPENDENCY_CHAIN.get("heritage", {})

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import HERITAGE_PROMPT
        return HERITAGE_PROMPT

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[Skill] 执行 {self.dimension_name}")
        return {
            "dimension_key": self.dimension_key,
            "dimension_name": self.dimension_name,
            "dimension_result": ""
        }


class LandscapeSkill(DimensionSkill):
    """村庄风貌指引Skill"""

    def __init__(self):
        super().__init__("landscape", "村庄风貌指引")

    def get_dependencies(self) -> Dict[str, Any]:
        from .dimension_mapping import FULL_DEPENDENCY_CHAIN
        return FULL_DEPENDENCY_CHAIN.get("landscape", {})

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import LANDSCAPE_PROMPT
        return LANDSCAPE_PROMPT

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[Skill] 执行 {self.dimension_name}")
        return {
            "dimension_key": self.dimension_key,
            "dimension_name": self.dimension_name,
            "dimension_result": ""
        }


class ProjectBankSkill(DimensionSkill):
    """建设项目库Skill"""

    def __init__(self):
        super().__init__("project_bank", "建设项目库")

    def get_dependencies(self) -> Dict[str, Any]:
        from .dimension_mapping import FULL_DEPENDENCY_CHAIN
        return FULL_DEPENDENCY_CHAIN.get("project_bank", {})

    def get_prompt_template(self) -> str:
        from ..subgraphs.detailed_plan_prompts import PROJECT_BANK_PROMPT
        return PROJECT_BANK_PROMPT

    def prepare_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        项目库需要特殊的状态准备：包含前序维度的规划结果
        """
        # 确保包含前序维度的规划
        completed_plans = state.get("completed_plans", {})
        if not completed_plans:
            logger.warning("[ProjectBankSkill] 缺少前序维度规划结果")

        return state

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[Skill] 执行 {self.dimension_name}")
        return {
            "dimension_key": self.dimension_key,
            "dimension_name": self.dimension_name,
            "dimension_result": ""
        }


# ==========================================
# Skill工厂
# ==========================================

class SkillFactory:
    """
    Skill工厂类

    根据维度名称创建对应的Skill实例
    """

    # Skill类映射
    _SKILL_CLASSES = {
        "industry": IndustryPlanningSkill,
        "master_plan": MasterPlanSkill,
        "traffic": TrafficPlanningSkill,
        "public_service": PublicServiceSkill,
        "infrastructure": InfrastructureSkill,
        "ecological": EcologicalPlanningSkill,
        "disaster_prevention": DisasterPreventionSkill,
        "heritage": HeritageSkill,
        "landscape": LandscapeSkill,
        "project_bank": ProjectBankSkill
    }

    @classmethod
    def create_skill(cls, dimension: str) -> DimensionSkill:
        """
        根据维度名称创建对应的Skill

        Args:
            dimension: 维度标识（如 "industry"）

        Returns:
            DimensionSkill实例

        Raises:
            ValueError: 如果维度不存在
        """
        skill_class = cls._SKILL_CLASSES.get(dimension)

        if not skill_class:
            raise ValueError(f"未找到维度 '{dimension}' 的Skill类")

        return skill_class()

    @classmethod
    def get_all_skills(cls) -> Dict[str, DimensionSkill]:
        """
        获取所有Skill实例

        Returns:
            维度标识 -> Skill实例 的字典
        """
        return {
            dimension: cls.create_skill(dimension)
            for dimension in cls._SKILL_CLASSES.keys()
        }

    @classmethod
    def get_skills_by_wave(cls, wave: int) -> List[DimensionSkill]:
        """
        获取指定波次的所有Skill

        Args:
            wave: 波次编号 (1 或 2)

        Returns:
            Skill列表
        """
        from .dimension_mapping import get_dimensions_by_wave

        dimensions = get_dimensions_by_wave(wave)
        return [cls.create_skill(d) for d in dimensions]


# ==========================================
# 辅助函数
# ==========================================

def validate_skill_dependencies(
    skills: List[DimensionSkill],
    completed_dimensions: List[str]
) -> Dict[str, bool]:
    """
    验证一组Skill的依赖是否满足

    Args:
        skills: Skill列表
        completed_dimensions: 已完成的维度列表

    Returns:
        维度标识 -> 依赖是否满足 的字典
    """
    return {
        skill.dimension_key: skill.validate_dependencies(completed_dimensions)
        for skill in skills
    }


def get_skill_execution_order() -> List[List[str]]:
    """
    获取Skill的执行顺序（按波次）

    Returns:
        二维列表，每个子列表是一个波次的维度列表
    """
    from .dimension_mapping import WAVE_CONFIG

    return [
        WAVE_CONFIG[wave]["dimensions"]
        for wave in sorted(WAVE_CONFIG.keys())
    ]
