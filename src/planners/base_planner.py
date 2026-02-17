"""
维度规划器基类

定义维度规划器的基础接口和通用功能，充分利用现有的基础设施：
- llm_factory.create_llm() - LLM创建
- dimension_mapping.get_full_dependency_chain() - 依赖管理
- state_filter.filter_state_for_detailed_dimension_v2() - 状态筛选
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
from langchain_core.messages import HumanMessage

from ..core.llm_factory import create_llm
from ..core.dimension_mapping import get_full_dependency_chain
from ..utils.state_filter import filter_state_for_detailed_dimension_v2
from ..utils.logger import get_logger

logger = get_logger(__name__)


class DimensionPlanner(ABC):
    """
    维度规划器基类

    每个详细规划维度继承此类并实现抽象方法。

    关键设计：
    - 使用 llm_factory.create_llm() 创建LLM（不重复造轮）
    - 使用 dimension_mapping.get_full_dependency_chain() 获取依赖
    - 使用 state_filter.filter_state_for_detailed_dimension_v2() 筛选状态
    - execute() 方法包含真正的LLM调用逻辑

    Example:
        >>> class IndustryPlanningPlanner(DimensionPlanner):
        ...     def __init__(self):
        ...         super().__init__("industry", "产业规划")
        ...
        ...     def get_prompt_template(self) -> str:
        ...         from ..subgraphs.detailed_plan_prompts import INDUSTRY_PLANNING_PROMPT
        ...         return INDUSTRY_PLANNING_PROMPT
        ...
        ...     def build_prompt(self, filtered_state: Dict[str, Any]) -> str:
        ...         return self.get_prompt_template().format(
        ...             analysis=filtered_state["filtered_analysis"],
        ...             concept=filtered_state["filtered_concepts"]
        ...         )
    """

    def __init__(
        self,
        dimension_key: str,
        dimension_name: str
    ):
        """
        初始化规划器

        Args:
            dimension_key: 维度标识（如 "industry"）
            dimension_name: 维度名称（如 "产业规划"）
        """
        self.dimension_key = dimension_key
        self.dimension_name = dimension_name

    @abstractmethod
    def get_prompt_template(self) -> str:
        """
        获取Prompt模板

        Returns:
            Prompt模板字符串
        """
        pass

    @abstractmethod
    def build_prompt(self, filtered_state: Dict[str, Any]) -> str:
        """
        构建完整的Prompt（子类必须实现）

        注意：filtered_state 已经通过 state_filter 筛选，
        包含 filtered_analysis 和 filtered_concepts。

        Args:
            filtered_state: 已经过滤的状态（使用 state_filter 筛选后）

        Returns:
            完整的 prompt 字符串
        """
        pass

    def get_dependencies(self) -> Dict[str, Any]:
        """
        获取该维度的依赖关系

        使用现有的 dimension_mapping.get_full_dependency_chain()。

        Returns:
            {
                "layer1_analyses": List[str],  # 依赖的现状分析维度
                "layer2_concepts": List[str],  # 依赖的规划思路维度
                "wave": int,                   # 执行波次
                "depends_on_detailed": List[str]  # 依赖的其他详细规划维度
            }
        """
        return get_full_dependency_chain(self.dimension_key)

    def execute(
        self,
        state: Dict[str, Any],
        use_adapters: bool = False,
        adapter_types: list = None
    ) -> Dict[str, Any]:
        """
        执行该维度的规划生成（默认实现）

        流程：
        1. 如果启用适配器，先调用适配器获取专业分析数据
        2. 从黑板获取适配器结果
        3. 使用 state_filter 筛选状态
        4. 使用 build_prompt 构建 prompt（包含适配器上下文）
        5. 使用 llm_factory 调用 LLM（支持LangSmith tracing）
        6. 返回结果

        子类可以重写此方法以提供自定义逻辑。

        Args:
            state: 完整的状态字典
            use_adapters: 是否使用适配器获取专业分析数据
            adapter_types: 要使用的适配器类型列表 (如 ["gis", "network"])

        Returns:
            {
                "dimension_key": str,
                "dimension_name": str,
                "dimension_result": str  # 生成的规划内容
            }
        """
        logger.info(f"[Planner] 执行 {self.dimension_name}")

        # 1. 如果启用适配器，先调用适配器
        if use_adapters and adapter_types:
            adapter_context = self._execute_adapters(state, adapter_types)
        else:
            adapter_context = {}

        # 2. 筛选状态（使用现有 state_filter）
        filtered_state = self._filter_state(state)

        # 3. 将额外的上下文信息添加到filtered_state（用于prompt构建）
        # 这样build_prompt可以访问project_name和constraints
        filtered_state["_project_name"] = state.get("project_name", "村庄")
        filtered_state["_constraints"] = state.get("constraints", "无特殊约束")

        # 4. 整合适配器结果到过滤状态
        if adapter_context:
            filtered_state["_adapter_context"] = adapter_context
            logger.info(f"[Planner] {self.dimension_name} 已整合适配器数据: {list(adapter_context.keys())}")

        # 5. 构建 prompt
        prompt = self.build_prompt(filtered_state)

        # 6. 调用 LLM（使用现有 llm_factory + LangSmith支持）
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
                        layer=3  # 详细规划层级
                    )
            except Exception as e:
                logger.debug(f"[Planner] LangSmith metadata创建失败: {e}")
                metadata = None

            # 创建LLM实例（自动包含LangSmith callbacks）
            llm = create_llm(
                model="glm-4-flash",
                temperature=0.7,
                max_tokens=2000,
                metadata=metadata  # 传递metadata给LangSmith
            )
            response = llm.invoke([HumanMessage(content=prompt)])
            result = response.content

            logger.info(f"[Planner] {self.dimension_name} 完成，长度: {len(result)}")

            return {
                "dimension_key": self.dimension_key,
                "dimension_name": self.dimension_name,
                "dimension_result": result
            }

        except Exception as e:
            logger.error(f"[Planner] {self.dimension_name} 执行失败: {e}")
            return {
                "dimension_key": self.dimension_key,
                "dimension_name": self.dimension_name,
                "dimension_result": f"[执行失败] {str(e)}"
            }

    def _execute_adapters(
        self,
        state: Dict[str, Any],
        adapter_types: list
    ) -> Dict[str, Any]:
        """
        执行适配器并从黑板获取结果

        Args:
            state: 当前状态字典
            adapter_types: 要执行的适配器类型列表

        Returns:
            适配器上下文字典
        """
        from ..nodes.tool_nodes import ToolBridgeNode
        from ..utils.blackboard_manager import get_blackboard

        # 1. 设置状态标志并调用ToolBridgeNode执行适配器
        tool_bridge = ToolBridgeNode()
        adapter_context = {}

        for adapter_type in adapter_types:
            if adapter_type == "gis":
                state["use_gis_adapter"] = True
                state["gis_analysis_type"] = self._get_gis_analysis_type()
            elif adapter_type == "network":
                state["use_network_adapter"] = True
                state["network_analysis_type"] = self._get_network_analysis_type()
            elif adapter_type == "population":
                state["use_population_adapter"] = True
                state["population_prediction_type"] = "basic"
                # 尝试从状态中获取人口数据
                if "village_data" in state:
                    # 简单解析人口数据
                    import re
                    match = re.search(r'人口[：:]\s*(\d+)', state["village_data"])
                    if match:
                        state["current_population"] = int(match.group(1))

            # 调用 ToolBridgeNode 执行适配器
            state_update = tool_bridge(state)
            state.update(state_update)

        # 2. 从黑板获取适配器结果
        blackboard = state.get("blackboard")
        if blackboard:
            tool_results = blackboard.list_tool_results()
            for tool_id, tool_result in tool_results.items():
                if tool_result.success:
                    adapter_context[f"adapter_{tool_id}"] = tool_result.result
                    logger.debug(f"[Planner] 获取适配器结果: {tool_id}")
        else:
            # 降级：使用黑板管理器全局实例
            try:
                blackboard = get_blackboard()
                tool_results = blackboard.list_tool_results()
                for tool_id, tool_result in tool_results.items():
                    if tool_result.success:
                        adapter_context[f"adapter_{tool_id}"] = tool_result.result
                        logger.debug(f"[Planner] 获取适配器结果（全局）: {tool_id}")
            except Exception as e:
                logger.warning(f"[Planner] 获取黑板结果失败: {e}")

        return adapter_context

    def _get_gis_analysis_type(self) -> str:
        """
        获取该维度需要的GIS分析类型

        子类可以重写此方法以指定特定的GIS分析类型。
        """
        mapping = {
            "industry": "land_use_analysis",
            "ecological": "soil_analysis",
            "infrastructure": "hydrology_analysis",
            "master_plan": "land_use_analysis",
            "landscape": "terrain_analysis",
            "disaster_prevention": "flood_risk_analysis"
        }
        return mapping.get(self.dimension_key, "land_use_analysis")

    def _get_network_analysis_type(self) -> str:
        """
        获取该维度需要的网络分析类型

        子类可以重写此方法以指定特定的网络分析类型。
        """
        mapping = {
            "traffic": "connectivity",
            "infrastructure": "accessibility",
            "public_service": "service_area"
        }
        return mapping.get(self.dimension_key, "connectivity")

    def _filter_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        使用 state_filter 筛选状态（私有方法）

        子类可以重写此方法以自定义筛选逻辑。

        Args:
            state: 完整的状态字典

        Returns:
            筛选后的状态字典，包含：
            - filtered_analysis: 筛选后的现状分析
            - filtered_concepts: 筛选后的规划思路
            - filtered_detailed: 筛选后的前序详细规划（如需要）
            - dependency_chain: 完整依赖链
            - token_stats: Token 统计
        """
        # 默认使用 detailed_plan 的筛选逻辑
        filtered = filter_state_for_detailed_dimension_v2(
            detailed_dimension=self.dimension_key,
            full_analysis_reports=state.get("dimension_reports", {}),
            full_analysis_report=state.get("analysis_report", ""),
            full_concept_reports=state.get("concept_dimension_reports", {}),
            full_concept_report=state.get("planning_concept", ""),
            completed_detailed_reports=state.get("completed_plans", {})
        )

        logger.info(f"[Planner] {self.dimension_name} 状态筛选完成，"
                   f"Token优化: {filtered['token_stats']['reduction_percent']}%")

        return filtered

    def execute_with_feedback(
        self,
        state: Dict[str, Any],
        feedback: str,
        original_result: str,
        revision_count: int = 0
    ) -> str:
        """
        基于反馈重新执行规划器（用于修复流程）

        Args:
            state: 当前状态字典
            feedback: 人工反馈
            original_result: 原始执行结果
            revision_count: 修复次数（用于追踪修复轮数）

        Returns:
            修复后的结果字符串
        """
        logger.info(f"[{self.dimension_name}] 基于反馈重新执行 (第{revision_count + 1}次)")

        # 构建修复 prompt
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
            # 创建LangSmith metadata（如果启用）
            try:
                from ..core.langsmith_integration import get_langsmith_manager
                langsmith = get_langsmith_manager()
                metadata = None
                if langsmith.is_enabled():
                    metadata = langsmith.create_run_metadata(
                        project_name=state.get("project_name", "村庄"),
                        dimension=f"{self.dimension_key}_revision",
                        layer=3,
                        extra_info={"revision_count": revision_count + 1}
                    )
            except Exception as e:
                logger.debug(f"[Planner] LangSmith metadata创建失败: {e}")
                metadata = None

            llm = create_llm(
                model="glm-4-flash",
                temperature=0.7,
                max_tokens=2000,
                metadata=metadata
            )
            response = llm.invoke([HumanMessage(content=revision_prompt)])
            revised_content = response.content

            logger.info(f"[{self.dimension_name}] 修复完成，内容长度: {len(revised_content)}")

            return revised_content

        except Exception as e:
            logger.error(f"[{self.dimension_name}] 修复失败: {e}")
            # 返回原始结果
            return original_result

    def validate_dependencies(self, completed_dimensions: list) -> bool:
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


__all__ = ["DimensionPlanner"]
