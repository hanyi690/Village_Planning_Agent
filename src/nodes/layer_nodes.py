"""
Layer节点实现

封装Layer执行的通用模式，利用现有基础设施。
"""

from abc import abstractmethod
from typing import Dict, Any
from pathlib import Path

from .base_node import BaseNode, AsyncBaseNode
from ..core.state_builder import StateBuilder
from ..utils.logger import get_logger

logger = get_logger(__name__)


class BaseLayerNode(AsyncBaseNode):
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

    def __init__(
        self,
        layer_number: int,
        layer_name: str,
        output_key: str  # 如 "analysis_report", "planning_concept"
    ):
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

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行Layer节点的标准流程：
        1. 调用子图
        2. 检查成功
        3. 保存输出
        4. 返回状态更新
        """
        # 1. 调用子图（异步）
        result = await self._call_subgraph(state)

        if not result.get("success", False):
            return self._build_failure_updates(result)

        # 2. 保存输出（使用现有工具）
        checkpoint_id = self._save_outputs(state, result)

        # 3. 构建成功状态更新
        return self._build_success_updates(state, result, checkpoint_id)

    @abstractmethod
    async def _call_subgraph(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用对应的子图（子类实现）

        Args:
            state: 当前状态

        Returns:
            子图执行结果字典，包含 success 标志
        """
        pass

    def _save_outputs(
        self,
        state: Dict[str, Any],
        result: Dict[str, Any]
    ) -> str:
        """
        保存输出（OutputManager）

        Checkpoint 由 LangGraph AsyncSqliteSaver 自动管理。

        Args:
            state: 原始状态
            result: 子图执行结果

        Returns:
            空字符串（checkpoint 由 LangGraph 管理）
        """
        # OutputManager保存（使用现有工具）
        output_manager = state.get("output_manager")
        if output_manager and output_manager.use_default_structure:
            try:
                # 根据不同层级调用不同的保存方法，使用正确的键名
                if self.layer_number == 1:
                    save_result = output_manager.save_layer1_results(
                        combined_report="",  # 不再生成综合报告
                        dimension_reports=result.get("analysis_reports", {})
                    )
                elif self.layer_number == 2:
                    save_result = output_manager.save_layer2_results(
                        combined_report="",  # 不再生成综合报告
                        dimension_reports=result.get("concept_reports", {})
                    )
                elif self.layer_number == 3:
                    # Layer 3 使用 detail_reports
                    detail_reports = result.get("detail_reports", {})

                    logger.info(f"[{self.node_name}] detail_reports 包含的维度: {list(detail_reports.keys())}")

                    save_result = output_manager.save_layer3_results(
                        combined_report=result.get("detailed_plan_report", ""),
                        dimension_reports=detail_reports
                    )
                else:
                    save_result = {"saved_count": 0}

                logger.info(f"[{self.node_name}] 保存了 {save_result.get('saved_count', 0)} 个文件")
            except Exception as e:
                logger.warning(f"[{self.node_name}] OutputManager保存失败: {e}")

        # Checkpoint 由 LangGraph 自动保存，无需手动处理
        return ""

    def _build_checkpoint_state(
        self,
        original_state: Dict[str, Any],
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        构建成功状态更新（子类实现）

        Args:
            state: 原始状态
            result: 子图执行结果
            checkpoint_id: checkpoint ID（现在为空字符串，由 LangGraph 管理）

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


class Layer1AnalysisNode(BaseLayerNode):
    """Layer 1: 现状分析节点"""

    def __init__(self):
        super().__init__(layer_number=1, layer_name="现状分析", output_key="analysis_report")

    async def _call_subgraph(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """调用现状分析子图"""
        from ..subgraphs.analysis_subgraph import call_analysis_subgraph
        return await call_analysis_subgraph(
            raw_data=state["village_data"],
            project_name=state["project_name"],
            session_id=state.get("session_id", "")
        )

    def _build_success_updates(
        self,
        state: Dict[str, Any],
        result: Dict[str, Any],
        checkpoint_id: str
    ) -> Dict[str, Any]:
        """构建成功状态更新"""
        return StateBuilder()\
            .set("analysis_reports", result.get("analysis_reports", {}))\
            .set("layer_1_completed", True)\
            .set("current_layer", 2)\
            .set("previous_layer", 1)\
            .set("last_checkpoint_id", checkpoint_id)\
            .add_message(f"现状分析完成，生成了 {len(result.get('analysis_reports', {}))} 个维度报告。")\
            .build()


class Layer2ConceptNode(BaseLayerNode):
    """Layer 2: 规划思路节点"""

    def __init__(self):
        super().__init__(layer_number=2, layer_name="规划思路", output_key="planning_concept")

    async def _call_subgraph(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """调用规划思路子图"""
        from ..subgraphs.concept_subgraph import call_concept_subgraph
        return await call_concept_subgraph(
            project_name=state["project_name"],
            analysis_reports=state.get("analysis_reports", {}),
            task_description=state["task_description"],
            constraints=state.get("constraints", "无特殊约束"),
            session_id=state.get("session_id", "")
        )

    def _build_success_updates(
        self,
        state: Dict[str, Any],
        result: Dict[str, Any],
        checkpoint_id: str
    ) -> Dict[str, Any]:
        """构建成功状态更新"""
        return StateBuilder()\
            .set("concept_reports", result.get("concept_reports", {}))\
            .set("layer_2_completed", True)\
            .set("current_layer", 3)\
            .set("previous_layer", 2)\
            .set("last_checkpoint_id", checkpoint_id)\
            .add_message(f"规划思路已生成，包含 {len(result.get('concept_reports', {}))} 个维度报告。")\
            .build()


class Layer3DetailNode(BaseLayerNode):
    """Layer 3: 详细规划节点"""

    def __init__(self):
        super().__init__(layer_number=3, layer_name="详细规划", output_key="detailed_plan")

    async def _call_subgraph(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """调用详细规划子图"""
        from ..subgraphs.detailed_plan_subgraph import call_detailed_plan_subgraph
        return await call_detailed_plan_subgraph(
            project_name=state["project_name"],
            analysis_reports=state.get("analysis_reports", {}),
            concept_reports=state.get("concept_reports", {}),
            task_description=state.get("task_description", "制定村庄详细规划"),
            constraints=state.get("constraints", "无特殊约束"),
            required_dimensions=state.get("required_dimensions"),
            enable_human_review=state.get("need_human_review", False),
            session_id=state.get("session_id", "")
        )

    def _build_success_updates(
        self,
        state: Dict[str, Any],
        result: Dict[str, Any],
        checkpoint_id: str
    ) -> Dict[str, Any]:
        """构建成功状态更新"""
        # 使用子图返回的 detail_reports
        detail_reports = result.get("detail_reports", {})

        return StateBuilder()\
            .set("detail_reports", detail_reports)\
            .set("layer_3_completed", True)\
            .set("current_layer", 4)\
            .set("previous_layer", 3)\
            .set("last_checkpoint_id", checkpoint_id)\
            .add_message(f"详细规划已生成，包含 {len(result.get('completed_dimensions', []))} 个专业维度。")\
            .build()


__all__ = [
    "BaseLayerNode",
    "Layer1AnalysisNode",
    "Layer2ConceptNode",
    "Layer3DetailNode",
]
