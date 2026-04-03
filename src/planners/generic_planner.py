"""
通用规划器 - Python Code-First 架构，支持所有 28 个维度

复用现有基础设施：
- UnifiedPlannerBase: LLM 调用、错误处理、RAG
- state_filter: 状态筛选逻辑
- dimension_metadata: 维度元数据配置
- prompts 模块: Python Prompt 模板
"""

from typing import Any, Dict, Optional

from .unified_base_planner import UnifiedPlannerBase
from ..utils.logger import get_logger
from ..config.dimension_metadata import get_dimension_config

logger = get_logger(__name__)


class GenericPlanner(UnifiedPlannerBase):
    """
    通用规划器 - Python Code-First 架构，支持所有 28 个维度

    特性:
    1. Python 模块驱动（不再依赖 YAML）
    2. 动态状态筛选（根据层级自动选择）
    3. 灵活 Prompt 构建
    4. 工具钩子支持
    5. 专业数据 Hook（get_specialized_data）
    6. 统一架构（Layer 1/2/3 使用同一类）
    """

    def __init__(self, dimension_key: str):
        """
        初始化通用规划器

        Args:
            dimension_key: 维度标识（如 "location", "industry"）
        """
        # 加载配置
        config = get_dimension_config(dimension_key)
        if not config:
            raise ValueError(f"未找到维度配置: {dimension_key}")

        # 保存完整配置（供工具钩子使用）
        self.config = config
        self.layer = config["layer"]
        self.dependencies = config["dependencies"]
        self.state_filter_type = config["state_filter"]
        self.prompt_key = config["prompt_key"]
        self.tool_name = config.get("tool")  # 工具钩子

        # 加载 Prompt 模板（根据 layer 动态加载）
        self.prompt_template = self._load_prompt_from_module(dimension_key)

        # 初始化基类
        super().__init__(
            dimension_key=dimension_key,
            dimension_name=config["name"],
            rag_enabled=config.get("rag_enabled", True)
        )

    def _load_prompt_from_module(self, dimension_key: str) -> str:
        """
        从 Python 模块加载 Prompt 模板

        根据层级动态导入对应的 prompts 模块：
        - Layer 1: analysis_prompts.py（字典格式）
        - Layer 2: concept_prompts.py（常量格式）
        - Layer 3: detailed_plan_prompts.py（函数格式）

        Args:
            dimension_key: 维度键名

        Returns:
            Prompt 模板字符串
        """
        try:
            if self.layer == 1:
                from ..subgraphs.analysis_prompts import ANALYSIS_DIMENSIONS
                if dimension_key in ANALYSIS_DIMENSIONS:
                    return ANALYSIS_DIMENSIONS[dimension_key]["prompt"]
                else:
                    logger.warning(f"[GenericPlanner] Layer 1 未找到维度: {dimension_key}")
                    return ""

            elif self.layer == 2:
                # Layer 2 使用常量格式
                from ..subgraphs.concept_prompts import (
                    RESOURCE_ENDOWMENT_PROMPT,
                    PLANNING_POSITIONING_PROMPT,
                    DEVELOPMENT_GOALS_PROMPT,
                    PLANNING_STRATEGIES_PROMPT
                )
                prompt_map = {
                    "resource_endowment": RESOURCE_ENDOWMENT_PROMPT,
                    "planning_positioning": PLANNING_POSITIONING_PROMPT,
                    "development_goals": DEVELOPMENT_GOALS_PROMPT,
                    "planning_strategies": PLANNING_STRATEGIES_PROMPT
                }
                return prompt_map.get(dimension_key, "")

            elif self.layer == 3:
                # Layer 3 使用函数格式，在 build_prompt 中动态调用
                return ""  # 返回空字符串，实际在 build_prompt 中处理

            else:
                logger.error(f"[GenericPlanner] 未知的层级: {self.layer}")
                return ""

        except ImportError as e:
            logger.error(f"[GenericPlanner] 导入 prompts 模块失败: {e}")
            return ""

    def validate_state(self, state: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        根据层级动态验证状态

        Layer 1: 检查 raw_data
        Layer 2: 检查 filtered_analysis, task_description, constraints（filtered_analysis 可为空）
        Layer 3: 检查依赖是否满足
        """
        if self.layer == 1:
            if "raw_data" not in state:
                return False, "缺少必需字段: raw_data"
            if not state.get("raw_data", "").strip():
                return False, "raw_data 为空"

        elif self.layer == 2:
            # filtered_analysis 可以为空字符串（有效值），只检查必要字段
            if "task_description" not in state:
                return False, "缺少必需字段: task_description"

        elif self.layer == 3:
            # 检查依赖是否满足
            if not self._check_dependencies(state):
                return False, "依赖的前置维度未完成"

        return True, None

    def build_prompt(self, state: Dict[str, Any]) -> str:
        """
        根据层级动态构建 Prompt

        Layer 1: 直接替换 {raw_data} + 专业数据 Hook
        Layer 2: 替换 {filtered_analysis}, {task_description}, {constraints}
        Layer 3: 使用函数式 prompt + 专业数据 Hook

        Hooks:
        1. get_specialized_data(): 获取专业脚本数据
        2. tool_hook(): 执行工具（如果配置了 tool）
        3. knowledge_cache: 从状态缓存读取 RAG 知识上下文
        """
        # 1. 获取基础上下文
        params = self._prepare_prompt_params(state)

        # ⭐ 核心 1：专业数据 Hook
        specialized_data = self._get_specialized_data_from_module(state)
        params.update(specialized_data)

        # ⭐ 核心 2：工具钩子逻辑
        tool_output = self._execute_tool_hook(state)
        params["tool_output"] = tool_output

        # ⭐ 核心 3：RAG 知识上下文（预加载模式）
        if self.rag_enabled:
            knowledge_context = self.get_cached_knowledge(state)
            params["knowledge_context"] = knowledge_context
        else:
            params["knowledge_context"] = ""

        # Layer 3 使用函数式 prompt
        if self.layer == 3:
            return self._build_layer3_prompt(state, params)

        # Layer 1 & 2 使用模板格式化
        try:
            return self.prompt_template.format(**params)
        except KeyError as e:
            logger.error(f"[{self.dimension_name}] Prompt 参数缺失: {e}")
            raise

    def _build_layer3_prompt(self, state: Dict[str, Any], params: Dict[str, Any]) -> str:
        """
        构建 Layer 3 的 Prompt（函数式）

        Args:
            state: 当前状态
            params: 已准备的参数（包括专业数据）

        Returns:
            格式化后的 Prompt 字符串
        """
        try:
            from ..subgraphs.detailed_plan_prompts import get_dimension_prompt

            # 提取参数
            project_name = params.get("project_name", "村庄")
            filtered_analysis = params.get("filtered_analysis", "")
            filtered_concept = params.get("filtered_concept", "")  # 统一使用单数形式
            constraints = params.get("constraints", "无特殊约束")
            knowledge_context = params.get("knowledge_context", "")  # RAG 知识上下文

            # 日志：验证 Prompt 构建
            logger.info(f"[GenericPlanner-L3] {self.dimension_key} 构建Prompt: "
                       f"analysis_report={len(filtered_analysis)}字符, "
                       f"planning_concept={len(filtered_concept)}字符, "
                       f"knowledge_context={len(knowledge_context)}字符, "
                       f"prompt_key={self.prompt_key}")

            # 调用函数式 prompt（使用 self.prompt_key 而不是 self.dimension_key）
            return get_dimension_prompt(
                dimension_key=self.prompt_key,
                project_name=project_name,
                analysis_report=filtered_analysis,
                planning_concept=filtered_concept,
                constraints=constraints,
                dimension_plans=params.get("dimension_plans", ""),  # 修复：添加 project_bank 专用参数
                knowledge_context=knowledge_context  # 新增：RAG 知识上下文
            )

        except ImportError as e:
            logger.error(f"[GenericPlanner] 导入 get_dimension_prompt 失败: {e}")
            return ""
        except Exception as e:
            logger.error(f"[GenericPlanner] 构建 Layer 3 Prompt 失败: {e}")
            raise

    def _get_specialized_data_from_module(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 Python 模块获取专业数据（Hook 模式）

        这是 GenericPlanner 的核心 Hook 接口，用于注入专业脚本生成的数据。
        支持的维度：
        - Layer 1: natural_environment, socio_economic, land_use, traffic
        - Layer 2: 目前无专业数据需求
        - Layer 3: industry, spatial_structure, land_use_planning, traffic, infrastructure, disaster_prevention

        Args:
            state: 当前状态字典

        Returns:
            专业数据字典，键值对可直接用于 Prompt 格式化
        """
        try:
            if self.layer == 1:
                from ..subgraphs.analysis_prompts import get_specialized_data
                return get_specialized_data(self.dimension_key, state)

            elif self.layer == 2:
                from ..subgraphs.concept_prompts import get_specialized_data
                return get_specialized_data(self.dimension_key, state)

            elif self.layer == 3:
                from ..subgraphs.detailed_plan_prompts import get_specialized_data
                return get_specialized_data(self.dimension_key, state)

            else:
                return {}

        except ImportError as e:
            logger.error(f"[GenericPlanner] 导入 get_specialized_data 失败: {e}")
            return {}

    def _execute_tool_hook(self, state: Dict[str, Any]) -> str:
        """
        执行工具钩子（如果配置了 tool）

        在调用 LLM 之前，先检查配置中是否指定了工具。
        如果有，执行工具并将结果注入到 Prompt 中。

        Args:
            state: 当前状态

        Returns:
            工具输出字符串，无工具时返回空字符串
        """
        tool_name = self.config.get("tool")  # 从配置读取

        if not tool_name:
            return ""  # 无工具，返回空字符串

        # 获取 session_id 用于 SSE 事件
        session_id = state.get("session_id", "unknown")

        try:
            from ..tools.registry import ToolRegistry

            # 准备工具上下文
            tool_context = self._prepare_tool_context(state)
            tool_context["session_id"] = session_id  # 确保传递 session_id

            # 检查 SSE 事件是否可用
            sse_available = False
            try:
                from backend.api.planning import (
                    append_tool_call_event,
                    append_tool_result_event
                )
                from ..tools.adapters.tool_wrapper import TOOL_DISPLAY_NAMES
                sse_available = True
            except ImportError:
                pass

            # 发送 tool_call 事件（如果 SSE 可用）
            if sse_available:
                display_name = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
                append_tool_call_event(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_display_name=display_name,
                    description=f"执行 {display_name} 为 {self.dimension_name} 维度提供数据支持",
                    estimated_time=3.0
                )

            # 执行工具
            tool_result = ToolRegistry.execute_tool(tool_name, tool_context)

            # 发送 tool_result 事件（如果 SSE 可用）
            if sse_available:
                append_tool_result_event(
                    session_id=session_id,
                    tool_name=tool_name,
                    status="success",
                    summary=f"{display_name} 执行成功",
                    data_preview=tool_result[:200]
                )
                logger.info(f"[{self.dimension_name}] 工具执行成功(带SSE): {tool_name}")
            else:
                logger.info(f"[{self.dimension_name}] 工具执行成功: {tool_name}")

            return f"\n【参考数据 - {tool_name}】\n{tool_result}\n"

        except ImportError:
            logger.warning(f"[{self.dimension_name}] ToolRegistry 不可用")
            return ""
        except Exception as e:
            logger.error(f"[{self.dimension_name}] 工具执行失败: {e}")

            # 尝试发送错误事件
            try:
                from backend.api.planning import append_tool_result_event
                append_tool_result_event(
                    session_id=session_id,
                    tool_name=tool_name,
                    status="error",
                    summary=f"工具执行失败: {str(e)}",
                    data_preview=str(e)
                )
            except ImportError:
                pass

            return f"\n【工具执行失败】\n{str(e)}\n"

    def _prepare_tool_context(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        为工具准备上下文数据

        工具可能需要访问：
        - 现状分析结果
        - 规划思路
        - 村庄基础数据
        - 前序详细规划结果

        Args:
            state: 当前状态

        Returns:
            工具上下文字典
        """
        context = {}

        # 添加基础数据
        context["raw_data"] = state.get("raw_data", "")
        context["project_name"] = state.get("project_name", "村庄")

        # 添加状态筛选后的数据（根据层级）
        if self.layer >= 2:
            # Layer 2/3: 添加现状分析
            context["analysis_report"] = state.get("analysis_report", "")
            context["analysis_reports"] = state.get("analysis_reports", {})

        if self.layer >= 3:
            # Layer 3: 添加规划思路
            context["planning_concept"] = state.get("planning_concept", "")
            context["concept_reports"] = state.get("concept_reports", {})

            # 添加前序详细规划（用于 project_bank 等）
            context["completed_plans"] = state.get("completed_plans", {})

        return context

    def _prepare_prompt_params(self, state: Dict[str, Any]) -> Dict[str, str]:
        """准备 Prompt 参数（根据层级差异化）"""
        params = {}

        if self.layer == 1:
            # Layer 1: 限制数据长度，避免超出 token 上限
            raw_data = state.get("raw_data", "")
            MAX_DATA_LENGTH = 50000  # 约 25k tokens，保留空间给 prompt 和输出
            if len(raw_data) > MAX_DATA_LENGTH:
                raw_data = raw_data[:MAX_DATA_LENGTH] + "\n\n...[数据已截断，原始数据过长]"
            params["raw_data"] = raw_data
            params["professional_data_section"] = ""
            # 添加 task_description 和 constraints（用于 villager_wishes 和 superior_planning）
            params["task_description"] = state.get("task_description", "未提供具体规划任务")
            params["constraints"] = state.get("constraints", "无特殊约束")
        elif self.layer == 2:
            # 直接使用子图预筛选的 filtered_analysis 和 filtered_concept 字段
            # 将前序维度报告合并到 analysis_report 中
            filtered_analysis = state.get("filtered_analysis", "")
            filtered_concept = state.get("filtered_concept", "")
            
            # 合并：现状分析 + 前序规划思路
            if filtered_concept:
                combined_report = f"{filtered_analysis}\n\n### 前序规划思路\n\n{filtered_concept}"
            else:
                combined_report = filtered_analysis
                
            params["analysis_report"] = combined_report
            params["task_description"] = state.get("task_description", "")
            params["constraints"] = state.get("constraints", "无特殊约束")
            params["professional_data_section"] = ""  # Layer 2 也需要这个参数
            
            # 注入上位规划数据（来自 Layer 1 的 superior_planning 维度）
            analysis_reports = state.get("analysis_reports", {})
            superior_planning_content = analysis_reports.get("superior_planning", "")
            if superior_planning_content:
                params["superior_planning_context"] = superior_planning_content
            else:
                params["superior_planning_context"] = "未提供上位规划数据"
            
            # 日志：验证数据传递
            logger.debug(f"[GenericPlanner-L2] {self.dimension_key} 参数准备: "
                       f"filtered_analysis={len(filtered_analysis)}字符, "
                       f"filtered_concept={len(filtered_concept)}字符, "
                       f"combined_report={len(combined_report)}字符, "
                       f"superior_planning_context={len(params['superior_planning_context'])}字符")

        elif self.layer == 3:
            # 直接使用子图预筛选的数据（来自 detailed_plan_subgraph）
            params["project_name"] = state.get("project_name", "村庄")
            params["filtered_analysis"] = state.get("filtered_analysis", "")  # 预筛选的现状分析
            params["filtered_concept"] = state.get("filtered_concept", "")  # 预筛选的规划思路（单数形式，与状态定义一致）
            params["constraints"] = state.get("constraints", "无特殊约束")

            # 日志：验证数据传递（DEBUG级别，详细日志在 _build_prompt 中输出）
            logger.debug(f"[GenericPlanner-L3] {self.dimension_key} 参数准备: "
                       f"filtered_analysis={len(params['filtered_analysis'])}字符, "
                       f"filtered_concept={len(params['filtered_concept'])}字符")

            # 特殊处理 project_bank：优先使用影子缓存
            if self.dimension_key == "project_bank":
                # 优先使用预筛选的 filtered_detail（影子缓存格式化后的内容）
                filtered_detail = state.get("filtered_detail", "")
                if filtered_detail:
                    params["dimension_plans"] = filtered_detail
                    logger.info(f"[GenericPlanner-L3] project_bank 使用影子缓存: {len(filtered_detail)}字符")
                else:
                    # 回退到原始逻辑
                    params["dimension_plans"] = self._format_detailed_plans(
                        state.get("completed_plans", {})
                    )
                    logger.warning(f"[GenericPlanner-L3] project_bank 回退到完整报告")

        return params

    def _check_dependencies(self, state: Dict[str, Any]) -> bool:
        """检查 Layer 3 的依赖是否满足"""
        if self.layer != 3:
            return True

        completed = state.get("completed_plans", {})
        depends_on = self.dependencies.get("depends_on_detailed", [])

        return all(d in completed for d in depends_on)

    def _format_detailed_plans(self, plans: Dict[str, str]) -> str:
        """格式化详细规划结果（用于 project_bank）"""
        from ..config.dimension_metadata import get_detailed_dimension_names

        formatted = []
        for key, content in plans.items():
            name = get_detailed_dimension_names().get(key, key)
            formatted.append(f"## {name}\n\n{content}\n")

        return "\n".join(formatted)

    def get_layer(self) -> int:
        """返回规划层级"""
        return self.layer

    def get_result_key(self) -> str:
        """返回结果字典的键名"""
        # 从配置读取
        return self.config.get("result_key", "dimension_result")


class GenericPlannerFactory:
    """
    通用规划器工厂 - 统一创建入口

    替代原有的 AnalysisPlannerFactory, ConceptPlannerFactory, DetailedPlannerFactory
    """

    @classmethod
    def create_planner(cls, dimension_key: str) -> GenericPlanner:
        """
        创建指定维度的规划器

        Args:
            dimension_key: 维度标识（如 "location", "industry"）

        Returns:
            GenericPlanner 实例
        """
        return GenericPlanner(dimension_key)

    @classmethod
    def create_all_planners(cls, layer: Optional[int] = None) -> Dict[str, GenericPlanner]:
        """
        批量创建规划器

        Args:
            layer: 可选，指定层级（1/2/3），None 表示创建所有

        Returns:
            {dimension_key: GenericPlanner} 字典
        """
        from ..config.dimension_metadata import DIMENSIONS_METADATA

        planners = {}

        for key, config in DIMENSIONS_METADATA.items():
            if layer is None or config["layer"] == layer:
                planners[key] = cls.create_planner(key)

        return planners


__all__ = ["GenericPlanner", "GenericPlannerFactory"]
