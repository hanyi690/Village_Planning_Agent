"""
通用规划器 - 通过 YAML 配置驱动，支持所有 28 个维度

复用现有基础设施：
- UnifiedPlannerBase: LLM 调用、错误处理、RAG
- state_filter: 状态筛选逻辑
- dimension_mapping: 依赖关系映射
"""

from pathlib import Path
from typing import Any, Dict, Optional
import yaml
import threading

from .unified_base_planner import UnifiedPlannerBase
from ..utils.logger import get_logger
from ..utils.state_filter import (
    filter_analysis_report_for_concept,
    filter_state_for_detailed_dimension_v2
)

logger = get_logger(__name__)


class GenericPlanner(UnifiedPlannerBase):
    """
    通用规划器 - 单一类支持所有 28 个维度

    特性:
    1. YAML 配置驱动
    2. 动态状态筛选（根据层级自动选择）
    3. 灵活 Prompt 构建
    4. 工具钩子支持
    5. 向后兼容
    """

    # 类级别配置缓存
    _dimensions_config: Optional[Dict[str, Any]] = None
    _prompts_config: Optional[Dict[str, str]] = None
    _config_lock = threading.Lock()  # 线程安全锁

    def __init__(self, dimension_key: str):
        """
        初始化通用规划器

        Args:
            dimension_key: 维度标识（如 "location", "industry"）
        """
        # 加载配置
        config = self._load_dimension_config(dimension_key)
        if not config:
            raise ValueError(f"未找到维度配置: {dimension_key}")

        # 保存完整配置（供工具钩子使用）
        self.config = config
        self.layer = config["layer"]
        self.dependencies = config["dependencies"]
        self.state_filter_type = config["state_filter"]
        self.prompt_key = config["prompt_key"]
        self.tool_name = config.get("tool")  # 工具钩子

        # 加载 Prompt 模板
        self.prompt_template = self._load_prompt_template(self.prompt_key)

        # 初始化基类
        super().__init__(
            dimension_key=dimension_key,
            dimension_name=config["name"],
            rag_enabled=config.get("rag_enabled", True)
        )

    @classmethod
    def _load_all_configs(cls) -> None:
        """加载所有配置文件（带缓存 + 线程安全）"""
        # 快速路径：如果已加载，直接返回
        if cls._dimensions_config is not None:
            return

        # 使用锁保护配置加载
        with cls._config_lock:
            # 双重检查：可能在等待锁时已被其他线程加载
            if cls._dimensions_config is not None:
                return

            config_dir = Path(__file__).parent.parent / "config"

            # 加载维度配置
            dimensions_path = config_dir / "dimensions.yaml"
            with open(dimensions_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
                cls._dimensions_config = config_data["dimensions"]

            # 加载 Prompt 配置
            prompts_path = config_dir / "prompts.yaml"
            with open(prompts_path, 'r', encoding='utf-8') as f:
                prompt_data = yaml.safe_load(f)
                cls._prompts_config = prompt_data["prompts"]

            logger.info(f"[GenericPlanner] 配置加载完成: {len(cls._dimensions_config)} 个维度")

    @classmethod
    def _load_dimension_config(cls, dimension_key: str) -> Optional[Dict[str, Any]]:
        """加载指定维度的配置"""
        cls._load_all_configs()
        return cls._dimensions_config.get(dimension_key)

    @classmethod
    def _load_prompt_template(cls, prompt_key: str) -> str:
        """加载 Prompt 模板"""
        cls._load_all_configs()
        if cls._prompts_config is None:
            logger.error(f"[GenericPlanner] prompts_config 未加载")
            return ""
        template = cls._prompts_config.get(prompt_key, "")
        if not template:
            logger.warning(f"[GenericPlanner] 未找到 Prompt 模板: {prompt_key}")
        return template

    def validate_state(self, state: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        根据层级动态验证状态

        Layer 1: 检查 raw_data
        Layer 2: 检查 analysis_report, task_description, constraints
        Layer 3: 检查依赖是否满足
        """
        if self.layer == 1:
            if "raw_data" not in state:
                return False, "缺少必需字段: raw_data"
            if not state.get("raw_data", "").strip():
                return False, "raw_data 为空"

        elif self.layer == 2:
            required_fields = ["analysis_report", "task_description", "constraints"]
            for field in required_fields:
                if field not in state:
                    return False, f"缺少必需字段: {field}"

        elif self.layer == 3:
            # 检查依赖是否满足
            if not self._check_dependencies(state):
                return False, "依赖的前置维度未完成"

        return True, None

    def build_prompt(self, state: Dict[str, Any]) -> str:
        """
        根据层级动态构建 Prompt

        Layer 1: 直接替换 {raw_data}
        Layer 2: 替换 {filtered_analysis}, {task_description}, {constraints}
        Layer 3: 替换 {project_name}, {filtered_analysis}, {filtered_concepts}, {constraints}
        + 工具钩子：如果配置了 tool，执行工具并注入 {tool_output}
        """
        params = self._prepare_prompt_params(state)

        # ⭐ 核心：工具钩子逻辑
        tool_output = self._execute_tool_hook(state)
        params["tool_output"] = tool_output

        try:
            return self.prompt_template.format(**params)
        except KeyError as e:
            logger.error(f"[{self.dimension_name}] Prompt 参数缺失: {e}")
            raise

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

        try:
            from ..tools.registry import ToolRegistry

            # 准备工具上下文
            tool_context = self._prepare_tool_context(state)

            # 执行工具
            tool_result = ToolRegistry.execute_tool(tool_name, tool_context)

            logger.info(f"[{self.dimension_name}] 工具执行成功: {tool_name}")

            return f"\n【参考数据 - {tool_name}】\n{tool_result}\n"

        except ImportError:
            logger.warning(f"[{self.dimension_name}] ToolRegistry 不可用")
            return ""
        except Exception as e:
            logger.error(f"[{self.dimension_name}] 工具执行失败: {e}")
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
            context["dimension_reports"] = state.get("dimension_reports", {})

        if self.layer >= 3:
            # Layer 3: 添加规划思路
            context["planning_concept"] = state.get("planning_concept", "")
            context["concept_dimension_reports"] = state.get("concept_dimension_reports", {})

            # 添加前序详细规划（用于 project_bank 等）
            context["completed_plans"] = state.get("completed_plans", {})

        return context

    def _prepare_prompt_params(self, state: Dict[str, Any]) -> Dict[str, str]:
        """准备 Prompt 参数（根据层级差异化）"""
        params = {}

        if self.layer == 1:
            params["raw_data"] = state.get("raw_data", "")

        elif self.layer == 2:
            # 使用状态筛选函数
            filtered_analysis = filter_analysis_report_for_concept(
                concept_dimension=self.dimension_key,
                full_analysis_reports=state.get("dimension_reports"),
                full_analysis_report=state["analysis_report"]
            )
            params["filtered_analysis"] = filtered_analysis
            params["task_description"] = state.get("task_description", "")
            params["constraints"] = state.get("constraints", "无特殊约束")

        elif self.layer == 3:
            # 使用状态筛选函数
            filtered = filter_state_for_detailed_dimension_v2(
                detailed_dimension=self.dimension_key,
                full_analysis_reports=state.get("dimension_reports"),
                full_analysis_report=state["analysis_report"],
                full_concept_reports=state.get("concept_dimension_reports"),
                full_concept_report=state["planning_concept"],
                completed_detailed_reports=state.get("completed_plans", {})
            )
            params["project_name"] = state.get("project_name", "村庄")
            params["filtered_analysis"] = filtered.get("filtered_analysis", "")
            params["filtered_concepts"] = filtered.get("filtered_concepts", "")
            params["constraints"] = state.get("constraints", "无特殊约束")

            # 特殊处理 project_bank 需要前序规划
            if self.dimension_key == "project_bank":
                params["dimension_plans"] = self._format_detailed_plans(
                    state.get("completed_plans", {})
                )

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
        from ..core.dimension_config import DETAILED_DIMENSION_NAMES

        formatted = []
        for key, content in plans.items():
            name = DETAILED_DIMENSION_NAMES().get(key, key)
            formatted.append(f"## {name}\n\n{content}\n")

        return "\n".join(formatted)

    def get_layer(self) -> int:
        """返回规划层级"""
        return self.layer

    def get_result_key(self) -> str:
        """返回结果字典的键名"""
        # 从配置读取，而不是硬编码
        config = self._load_dimension_config(self.dimension_key)
        return config.get("result_key", "dimension_result")


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
        GenericPlanner._load_all_configs()
        planners = {}

        for key, config in GenericPlanner._dimensions_config.items():
            if layer is None or config["layer"] == layer:
                planners[key] = cls.create_planner(key)

        return planners


__all__ = ["GenericPlanner", "GenericPlannerFactory"]
