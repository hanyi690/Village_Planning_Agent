"""
Layer节点实现

封装Layer执行的通用模式，利用现有基础设施。
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base_node import BaseNode
from ..core.state_builder import StateBuilder
from ..utils.logger import get_logger
from ..utils.checkpoint_manager import get_checkpoint_manager
from ..utils.streaming_context import (
    get_streaming_queue,
    get_storage_pipeline,
    get_dimension_events
)

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = get_logger(__name__)

# Type alias for state dict
StateDict = dict[str, Any]

# 定义运行时专用的key（不应持久化到checkpoint）
RUNTIME_KEYS = {
    "_streaming_queue",
    "_storage_pipeline",
    "_dimension_events",
    "_token_callback_factory",
    "_streaming_enabled",
    "_pending_tokens",
}


class BaseLayerNode(BaseNode):
    """
    Layer节点基类

    封装Layer执行的通用模式：
    1. 调用子图
    2. 检查成功
    3. 保存输出
    4. 返回状态更新

    子类需要实现：
    - _call_subgraph(): 调用对应的子图
    - _build_success_updates(): 构建成功状态更新
    """

    # Layer output key mapping
    OUTPUT_KEYS = {
        1: "analysis_report",
        2: "planning_concept",
        3: "detailed_plan",
    }

    # Dimension report key mapping
    DIMENSION_KEYS = {
        1: "analysis_dimension_reports",
        2: "concept_dimension_reports",
        3: "detailed_dimension_reports",
    }

    # Layer name mapping
    LAYER_NAMES = {
        1: "现状分析",
        2: "规划思路",
        3: "详细规划",
    }

    def __init__(
        self,
        layer_number: int,
        layer_name: str,
        output_key: str  # 如 "analysis_report", "planning_concept"
    ) -> None:
        """
        初始化Layer节点

        Args:
            layer_number: 层级编号 (1/2/3)
            layer_name: 层级名称
            output_key: 输出状态键名
        """
        super().__init__(f"Layer{layer_number}-{layer_name}")
        self.layer_number = layer_number
        self.layer_name = layer_name
        self.output_key = output_key

    def execute(self, state: StateDict) -> StateDict:
        """
        执行Layer节点的标准流程：
        1. 调用子图
        2. 检查成功
        3. 保存输出
        4. 返回状态更新
        """
        result = self._call_subgraph(state)

        if not result.get("success", False):
            return self._build_failure_updates(result)

        checkpoint_id = self._save_outputs(state, result)
        return self._build_success_updates(state, result, checkpoint_id)

    @abstractmethod
    def _call_subgraph(self, state: StateDict) -> StateDict:
        """
        调用对应的子图（子类实现）

        Args:
            state: 当前状态

        Returns:
            子图执行结果字典，包含 success 标志
        """
        pass

    def _save_outputs(self, state: StateDict, result: StateDict) -> str:
        """
        保存输出（OutputManager + Checkpoint）

        使用现有的OutputManager和CheckpointTool。

        Args:
            state: 原始状态
            result: 子图执行结果

        Returns:
            checkpoint_id 或空字符串
        """
        dimension_reports_key = self.DIMENSION_KEYS.get(self.layer_number, "")
        dimension_reports = result.get(dimension_reports_key, {})
        combined_report = self._generate_combined_report(
            state.get("project_name", "项目"),
            dimension_reports,
            self.LAYER_NAMES.get(self.layer_number, "")
        )

        # Add titles to dimension reports
        dimension_reports = self._add_titles_to_dimension_reports(dimension_reports)

        # Save using OutputManager
        self._save_to_output_manager(state, combined_report, dimension_reports)

        # Save checkpoint
        checkpoint_id = self._save_checkpoint(state, result, combined_report, dimension_reports)

        return checkpoint_id

    def _save_to_output_manager(
        self,
        state: StateDict,
        combined_report: str,
        dimension_reports: dict[str, str]
    ) -> None:
        """保存到OutputManager"""
        from ..utils.output_manager_registry import get_output_manager_registry

        registry = get_output_manager_registry()
        output_manager = registry.get(state.get("session_id"))

        if not output_manager or not output_manager.use_default_structure:
            return

        try:
            save_methods = {
                1: output_manager.save_layer1_results,
                2: output_manager.save_layer2_results,
                3: output_manager.save_layer3_results,
            }

            save_method = save_methods.get(self.layer_number)
            if save_method:
                save_result = save_method(
                    combined_report=combined_report,
                    dimension_reports=dimension_reports
                )
                logger.info(f"[{self.node_name}] 保存了 {save_result.get('saved_count', 0)} 个文件")
        except Exception as e:
            logger.warning(f"[{self.node_name}] OutputManager保存失败: {e}")

    def _save_checkpoint(
        self,
        state: StateDict,
        result: StateDict,
        combined_report: str,
        dimension_reports: dict[str, str]
    ) -> str:
        """保存checkpoint"""
        if not state.get("checkpoint_enabled", False):
            return ""

        checkpoint_manager = get_checkpoint_manager(
            project_name=state["project_name"],
            timestamp=state.get("session_id")
        )

        if not checkpoint_manager or not hasattr(checkpoint_manager, 'save'):
            return ""

        try:
            checkpoint_state = self._build_checkpoint_state(
                state, result, combined_report, dimension_reports
            )

            save_result = checkpoint_manager.save(
                state=checkpoint_state,
                layer=self.layer_number,
                description=f"Layer {self.layer_number} {self.layer_name}完成"
            )

            if save_result.get("success"):
                checkpoint_id = save_result.get("checkpoint_id", "")
                logger.info(f"[{self.node_name}] Checkpoint已保存: {checkpoint_id}")
                return checkpoint_id
            else:
                logger.warning(f"[{self.node_name}] Checkpoint保存失败: {save_result.get('error', '未知错误')}")
        except Exception as e:
            logger.warning(f"[{self.node_name}] Checkpoint保存异常: {e}")

        return ""

    def _add_titles_to_dimension_reports(self, dimension_reports: dict[str, str]) -> dict[str, str]:
        """
        为每个维度报告添加中文Markdown标题

        这个方法是幂等的（idempotent），多次调用不会产生重复标题。

        Args:
            dimension_reports: 原始维度报告字典

        Returns:
            带标题的维度报告字典
        """
        from ..core.dimension_config import (
            ANALYSIS_DIMENSION_NAMES,
            CONCEPT_DIMENSION_NAMES,
            DETAILED_DIMENSION_NAMES,
        )

        # Get dimension name mapping for current layer
        dimension_names_map = {
            1: ANALYSIS_DIMENSION_NAMES(),
            2: CONCEPT_DIMENSION_NAMES(),
            3: DETAILED_DIMENSION_NAMES(),
        }.get(self.layer_number, {})

        # Add titles to reports that don't have them
        titled_reports: dict[str, str] = {}
        for dimension_key, content in dimension_reports.items():
            if content.startswith("## "):
                titled_reports[dimension_key] = content
            else:
                chinese_title = dimension_names_map.get(dimension_key, dimension_key)
                titled_reports[dimension_key] = f"## {chinese_title}\n\n{content}"

        return titled_reports

    def _build_checkpoint_state(
        self,
        original_state: StateDict,
        result: StateDict,
        combined_report: str,
        dimension_reports: dict[str, str]
    ) -> StateDict:
        """
        构建用于checkpoint的状态

        Args:
            original_state: 原始状态
            result: 子图执行结果
            combined_report: 综合报告
            dimension_reports: 维度报告字典

        Returns:
            用于checkpoint的状态字典
        """
        # Ensure dimension reports have titles
        if dimension_reports:
            first_content = next(iter(dimension_reports.values()), "")
            if not first_content.startswith("## "):
                dimension_reports = self._add_titles_to_dimension_reports(dimension_reports)

        # Build base state - 排除运行时对象（不应持久化到checkpoint）
        checkpoint_state: StateDict = {
            **{k: v for k, v in original_state.items() if k not in RUNTIME_KEYS},
            self.output_key: combined_report,
            f"layer_{self.layer_number}_completed": True,
            "current_layer": self.layer_number + 1,
        }

        # Add layer-specific outputs
        if self.layer_number == 1:
            checkpoint_state["analysis_report"] = combined_report
            checkpoint_state["analysis_dimension_reports"] = dimension_reports
        elif self.layer_number == 2:
            checkpoint_state["planning_concept"] = combined_report
            checkpoint_state["concept_dimension_reports"] = dimension_reports
        elif self.layer_number == 3:
            checkpoint_state["detailed_plan"] = combined_report
            checkpoint_state["detailed_dimension_reports"] = dimension_reports

        return checkpoint_state

    @abstractmethod
    def _build_success_updates(
        self,
        state: Dict[str, Any],
        result: Dict[str, Any],
        checkpoint_id: str
    ) -> Dict[str, Any]:
        """
        构建成功状态更新（子类实现）

        Args:
            state: 原始状态
            result: 子图执行结果
            checkpoint_id: checkpoint ID

        Returns:
            状态更新字典
        """
        pass

    def _build_failure_updates(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建失败状态更新（子类可重写）

        Args:
            result: 子图执行结果

        Returns:
            状态更新字典
        """
        return StateBuilder()\
            .set(self.output_key, f"执行失败: {result.get('error', 'Unknown error')}")\
            .set(f"layer_{self.layer_number}_completed", False)\
            .add_message(f"{self.node_name}执行失败，请检查输入数据或稍后重试。")\
            .build()

    def _generate_combined_report(
        self,
        project_name: str,
        dimension_reports: Dict[str, str],
        layer_name: str
    ) -> str:
        """
        生成简单的综合报告（拼接各维度报告）

        Args:
            project_name: 项目名称
            dimension_reports: 维度报告字典（键名为英文）
            layer_name: 层级名称

        Returns:
            拼接后的综合报告
        """
        report = f"# {project_name} - {layer_name}报告\n\n"
        report += f"---\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        # 获取维度名称映射（英文键 -> 中文名）
        dimension_names_map = self._get_dimension_names_map()

        # 使用标准顺序（而非字母顺序）
        from ..utils.output_manager import OutputManager
        standard_order = OutputManager._get_dimension_order(self.layer_number)

        # 按标准顺序拼接，使用中文名称作为标题
        for dimension_key in standard_order:
            if dimension_key not in dimension_reports:
                continue
            content = dimension_reports[dimension_key]
            display_name = dimension_names_map.get(dimension_key, dimension_key)

            # 检测内容是否已包含"## 标题"，如果有则直接使用
            # 这样可以避免在 _add_titles_to_dimension_reports 已添加标题的情况下重复添加
            if content.startswith("## "):
                # 已有标题，直接拼接（不添加额外的标题）
                report += f"{content}\n\n"
            else:
                # 没有标题，添加标题
                report += f"## {display_name}\n\n{content}\n\n"

        return report

    def _get_dimension_names_map(self) -> dict[str, str]:
        """
        获取维度的英文名到中文名的映射

        Returns:
            英文键到中文名称的映射字典
        """
        from ..core.dimension_config import (
            ANALYSIS_DIMENSION_NAMES,
            CONCEPT_DIMENSION_NAMES,
            DETAILED_DIMENSION_NAMES,
        )

        mapping = {
            1: ANALYSIS_DIMENSION_NAMES(),
            2: CONCEPT_DIMENSION_NAMES(),
            3: DETAILED_DIMENSION_NAMES(),
        }
        return mapping.get(self.layer_number, {})


class Layer1AnalysisNode(BaseLayerNode):
    """Layer 1: 现状分析节点（集成RAG知识预加载）"""

    def __init__(self) -> None:
        super().__init__(layer_number=1, layer_name="现状分析", output_key="analysis_report")

    def _call_subgraph(self, state: StateDict) -> StateDict:
        """调用现状分析子图（集成RAG）"""
        from ..subgraphs.analysis_subgraph import call_analysis_subgraph

        # ✅ Get runtime objects from context instead of state
        streaming_queue = get_streaming_queue()
        storage_pipeline = get_storage_pipeline()
        dimension_events = get_dimension_events()

        return call_analysis_subgraph(
            raw_data=state["village_data"],
            project_name=state["project_name"],
            _streaming_enabled=state.get("_streaming_enabled", False),
            _token_callback_factory=state.get("_token_callback_factory"),
            rag_enabled=state.get("rag_enabled", True),
            _streaming_queue=streaming_queue,
            _storage_pipeline=storage_pipeline,
            _dimension_events=dimension_events
        )

    def _build_success_updates(
        self,
        state: StateDict,
        result: StateDict,
        checkpoint_id: str
    ) -> StateDict:
        """构建成功状态更新"""
        dimension_reports = result.get("analysis_dimension_reports", {})

        # Add titles if needed
        if dimension_reports:
            first_content = next(iter(dimension_reports.values()), "")
            if not first_content.startswith("## "):
                dimension_reports = self._add_titles_to_dimension_reports(dimension_reports)

        combined_report = self._generate_combined_report(
            state["project_name"],
            dimension_reports,
            "现状分析"
        )

        return (StateBuilder()
                .set("analysis_report", combined_report)
                .set("analysis_dimension_reports", dimension_reports)
                .set("layer_1_completed", True)
                .set("previous_layer", 1)
                .set("current_layer", 2)
                .set("pending_review_layer", 1)
                .set("last_checkpoint_id", checkpoint_id)
                .add_message(f"现状分析完成，生成了 {len(dimension_reports)} 个维度的分析报告。")
                .build())


class Layer2ConceptNode(BaseLayerNode):
    """Layer 2: 规划思路节点（集成RAG执行摘要）"""

    def __init__(self) -> None:
        super().__init__(layer_number=2, layer_name="规划思路", output_key="planning_concept")

    def _call_subgraph(self, state: StateDict) -> StateDict:
        """调用规划思路子图（集成RAG）"""
        from ..subgraphs.concept_subgraph import call_concept_subgraph

        # ✅ Get runtime objects from context instead of state
        streaming_queue = get_streaming_queue()
        storage_pipeline = get_storage_pipeline()
        dimension_events = get_dimension_events()

        return call_concept_subgraph(
            project_name=state["project_name"],
            analysis_report=state["analysis_report"],
            dimension_reports=state.get("analysis_dimension_reports", {}),
            task_description=state["task_description"],
            constraints=state.get("constraints", "无特殊约束"),
            _streaming_queue=streaming_queue,
            _storage_pipeline=storage_pipeline,
            _dimension_events=dimension_events
        )

    def _build_success_updates(
        self,
        state: StateDict,
        result: StateDict,
        checkpoint_id: str
    ) -> StateDict:
        """构建成功状态更新"""
        dimension_reports = result.get("concept_dimension_reports", {})

        # ✅ 添加调试日志
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[Layer2ConceptNode] === 开始构建成功更新 ===")
        logger.info(f"[Layer2ConceptNode] result keys: {list(result.keys())}")
        logger.info(f"[Layer2ConceptNode] dimension_reports: {dimension_reports}")
        logger.info(f"[Layer2ConceptNode] dimension_reports keys: {list(dimension_reports.keys())}")
        if dimension_reports:
            for key, value in dimension_reports.items():
                logger.info(f"[Layer2ConceptNode]   - {key}: {len(value)} chars")

        # Add titles if needed
        if dimension_reports:
            first_content = next(iter(dimension_reports.values()), "")
            if not first_content.startswith("## "):
                dimension_reports = self._add_titles_to_dimension_reports(dimension_reports)

        combined_report = self._generate_combined_report(
            state.get("project_name", "项目"),
            dimension_reports,
            "规划思路"
        )

        logger.info(f"[Layer2ConceptNode] 设置 concept_dimension_reports: {len(dimension_reports)} 个维度")

        return (StateBuilder()
                .set("planning_concept", combined_report)
                .set("concept_dimension_reports", dimension_reports)
                .set("layer_2_completed", True)
                .set("previous_layer", 2)
                .set("current_layer", 3)
                .set("pending_review_layer", 2)
                .set("last_checkpoint_id", checkpoint_id)
                .add_message(f"规划思路完成，生成了 {len(dimension_reports)} 个维度的分析报告。")
                .build())


class Layer3DetailNode(BaseLayerNode):
    """Layer 3: 详细规划节点（集成RAG章节全文）"""

    def __init__(self) -> None:
        super().__init__(layer_number=3, layer_name="详细规划", output_key="detailed_plan")

    def _call_subgraph(self, state: StateDict) -> StateDict:
        """调用详细规划子图（集成RAG）"""
        from ..subgraphs.detailed_plan_subgraph import call_detailed_plan_subgraph

        # ✅ Get runtime objects from context instead of state
        streaming_queue = get_streaming_queue()
        storage_pipeline = get_storage_pipeline()
        dimension_events = get_dimension_events()

        return call_detailed_plan_subgraph(
            project_name=state["project_name"],
            analysis_report=state["analysis_report"],
            planning_concept=state["planning_concept"],
            dimension_reports=state.get("dimension_reports", {}),
            concept_dimension_reports=state.get("concept_dimension_reports", {}),
            task_description=state.get("task_description", "制定村庄详细规划"),
            constraints=state.get("constraints", "无特殊约束"),
            required_dimensions=state.get("required_dimensions"),
            enable_human_review=state.get("need_human_review", False),
            _streaming_queue=streaming_queue,
            _storage_pipeline=storage_pipeline,
            _dimension_events=dimension_events
        )

    def _build_success_updates(
        self,
        state: StateDict,
        result: StateDict,
        checkpoint_id: str
    ) -> StateDict:
        """构建成功状态更新"""
        dimension_reports = result.get("detailed_dimension_reports", {})

        # Add titles if needed
        if dimension_reports:
            first_content = next(iter(dimension_reports.values()), "")
            if not first_content.startswith("## "):
                dimension_reports = self._add_titles_to_dimension_reports(dimension_reports)

        combined_report = self._generate_combined_report(
            state.get("project_name", "项目"),
            dimension_reports,
            "详细规划"
        )

        return (StateBuilder()
                .set("detailed_plan", combined_report)
                .set("detailed_dimension_reports", dimension_reports)
                .set("layer_3_completed", True)
                .set("previous_layer", 3)
                .set("current_layer", 4)
                .set("pending_review_layer", 3)
                .set("last_checkpoint_id", checkpoint_id)
                .add_message(f"详细规划完成，生成了 {len(dimension_reports)} 个专业维度的规划报告。")
                .build())


__all__ = [
    "BaseLayerNode",
    "Layer1AnalysisNode",
    "Layer2ConceptNode",
    "Layer3DetailNode",
]
