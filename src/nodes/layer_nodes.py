"""
Layer节点实现

封装Layer执行的通用模式，利用现有基础设施。
"""

from abc import abstractmethod
from typing import Dict, Any
from pathlib import Path

from .base_node import BaseNode
from ..core.state_builder import StateBuilder
from ..utils.logger import get_logger

logger = get_logger(__name__)


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

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行Layer节点的标准流程：
        1. 调用子图
        2. 检查成功
        3. 保存输出
        4. 返回状态更新
        """
        # 1. 调用子图
        result = self._call_subgraph(state)

        if not result.get("success", False):
            return self._build_failure_updates(result)

        # 2. 保存输出（使用现有工具）
        checkpoint_id = self._save_outputs(state, result)

        # 3. 构建成功状态更新
        return self._build_success_updates(state, result, checkpoint_id)

    @abstractmethod
    def _call_subgraph(self, state: Dict[str, Any]) -> Dict[str, Any]:
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
        保存输出（OutputManager + Checkpoint）

        使用现有的OutputManager和CheckpointTool。

        Args:
            state: 原始状态
            result: 子图执行结果

        Returns:
            checkpoint_id 或空字符串
        """
        checkpoint_id = ""

        # OutputManager保存（使用现有工具）
        output_manager = state.get("output_manager")
        if output_manager and output_manager.use_default_structure:
            try:
                # 根据不同层级调用不同的保存方法，使用正确的键名
                if self.layer_number == 1:
                    save_result = output_manager.save_layer1_results(
                        combined_report=result.get("analysis_report", ""),
                        dimension_reports=result.get("dimension_reports", {})
                    )
                elif self.layer_number == 2:
                    save_result = output_manager.save_layer2_results(
                        combined_report=result.get("concept_report", ""),
                        dimension_reports=result.get("concept_dimension_reports", {})
                    )
                elif self.layer_number == 3:
                    # Layer 3 子图返回 industry_plan, master_plan 等独立字段
                    # 需要转换为 detailed_dimension_reports 字典
                    dimension_reports = {}
                    dimension_key_map = {
                        "industry_plan": "industry",
                        "master_plan": "master_plan",
                        "traffic_plan": "traffic",
                        "public_service_plan": "public_service",
                        "infrastructure_plan": "infrastructure",
                        "ecological_plan": "ecological",
                        "disaster_prevention_plan": "disaster_prevention",
                        "heritage_plan": "heritage",
                        "landscape_plan": "landscape",
                        "project_bank": "project_bank"
                    }
                    for result_key, dimension_key in dimension_key_map.items():
                        plan_content = result.get(result_key, "")
                        if plan_content:
                            dimension_reports[dimension_key] = plan_content

                    save_result = output_manager.save_layer3_results(
                        combined_report=result.get("detailed_plan_report", ""),
                        dimension_reports=dimension_reports
                    )
                else:
                    save_result = {"saved_count": 0}

                logger.info(f"[{self.node_name}] 保存了 {save_result.get('saved_count', 0)} 个文件")
            except Exception as e:
                logger.warning(f"[{self.node_name}] OutputManager保存失败: {e}")

        # Checkpoint保存（使用现有CheckpointTool）
        if state.get("checkpoint_enabled", False):
            checkpoint_manager = state.get("checkpoint_manager")
            if checkpoint_manager and hasattr(checkpoint_manager, 'save'):
                try:
                    # 构建checkpoint状态
                    checkpoint_state = self._build_checkpoint_state(state, result)

                    save_result = checkpoint_manager.save(
                        state=checkpoint_state,
                        layer=self.layer_number,
                        description=f"Layer {self.layer_number} 完成"
                    )
                    checkpoint_id = save_result.get("checkpoint_id", "") if save_result.get("success") else ""
                except Exception as e:
                    logger.warning(f"[{self.node_name}] Checkpoint保存失败: {e}")

        return checkpoint_id

    def _build_checkpoint_state(
        self,
        original_state: Dict[str, Any],
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        构建用于checkpoint的状态（子类可重写）

        Args:
            original_state: 原始状态
            result: 子图执行结果

        Returns:
            用于checkpoint的状态字典
        """
        checkpoint_state = {
            **original_state,
            self.output_key: result.get("report", ""),
            f"layer_{self.layer_number}_completed": True,
            "current_layer": self.layer_number + 1
        }

        # 添加维度报告
        if "dimension_reports" in result:
            if self.layer_number == 1:
                checkpoint_state["dimension_reports"] = result.get("dimension_reports", {})
            elif self.layer_number == 2:
                checkpoint_state["concept_dimension_reports"] = result.get("dimension_reports", {})
            elif self.layer_number == 3:
                checkpoint_state["detailed_dimension_reports"] = result.get("dimension_reports", {})

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


class Layer1AnalysisNode(BaseLayerNode):
    """Layer 1: 现状分析节点"""

    def __init__(self):
        super().__init__(layer_number=1, layer_name="现状分析", output_key="analysis_report")

    def _call_subgraph(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """调用现状分析子图"""
        from ..subgraphs.analysis_subgraph import call_analysis_subgraph
        return call_analysis_subgraph(
            raw_data=state["village_data"],
            project_name=state["project_name"]
        )

    def _build_success_updates(
        self,
        state: Dict[str, Any],
        result: Dict[str, Any],
        checkpoint_id: str
    ) -> Dict[str, Any]:
        """构建成功状态更新"""
        return StateBuilder()\
            .set("analysis_report", result["analysis_report"])\
            .set("dimension_reports", result.get("dimension_reports", {}))\
            .set("layer_1_completed", True)\
            .set("current_layer", 2)\
            .set("last_checkpoint_id", checkpoint_id)\
            .add_message(f"现状分析完成，生成了 {len(result['analysis_report'])} 字符的综合报告。")\
            .build()


class Layer2ConceptNode(BaseLayerNode):
    """Layer 2: 规划思路节点"""

    def __init__(self):
        super().__init__(layer_number=2, layer_name="规划思路", output_key="planning_concept")

    def _call_subgraph(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """调用规划思路子图"""
        from ..subgraphs.concept_subgraph import call_concept_subgraph
        return call_concept_subgraph(
            project_name=state["project_name"],
            analysis_report=state["analysis_report"],
            dimension_reports=state.get("dimension_reports", {}),
            task_description=state["task_description"],
            constraints=state.get("constraints", "无特殊约束")
        )

    def _build_success_updates(
        self,
        state: Dict[str, Any],
        result: Dict[str, Any],
        checkpoint_id: str
    ) -> Dict[str, Any]:
        """构建成功状态更新"""
        return StateBuilder()\
            .set("planning_concept", result["concept_report"])\
            .set("concept_dimension_reports", result.get("concept_dimension_reports", {}))\
            .set("layer_2_completed", True)\
            .set("current_layer", 3)\
            .set("last_checkpoint_id", checkpoint_id)\
            .add_message(f"规划思路已生成，长度 {len(result['concept_report'])} 字符。")\
            .build()


class Layer3DetailNode(BaseLayerNode):
    """Layer 3: 详细规划节点"""

    def __init__(self):
        super().__init__(layer_number=3, layer_name="详细规划", output_key="detailed_plan")

    def _call_subgraph(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """调用详细规划子图"""
        from ..subgraphs.detailed_plan_subgraph import call_detailed_plan_subgraph
        return call_detailed_plan_subgraph(
            project_name=state["project_name"],
            analysis_report=state["analysis_report"],
            planning_concept=state["planning_concept"],
            dimension_reports=state.get("dimension_reports", {}),
            concept_dimension_reports=state.get("concept_dimension_reports", {}),
            task_description=state.get("task_description", "制定村庄详细规划"),
            constraints=state.get("constraints", "无特殊约束"),
            required_dimensions=state.get("required_dimensions"),
            enable_human_review=state.get("need_human_review", False)
        )

    def _build_success_updates(
        self,
        state: Dict[str, Any],
        result: Dict[str, Any],
        checkpoint_id: str
    ) -> Dict[str, Any]:
        """构建成功状态更新"""
        # 构建详细维度报告字典
        detailed_dimension_reports = {
            "dimension_industry": result.get("industry_plan", ""),
            "dimension_master_plan": result.get("master_plan", ""),
            "dimension_traffic": result.get("traffic_plan", ""),
            "dimension_public_service": result.get("public_service_plan", ""),
            "dimension_infrastructure": result.get("infrastructure_plan", ""),
            "dimension_ecological": result.get("ecological_plan", ""),
            "dimension_disaster_prevention": result.get("disaster_prevention_plan", ""),
            "dimension_heritage": result.get("heritage_plan", ""),
            "dimension_landscape": result.get("landscape_plan", ""),
            "dimension_project_bank": result.get("project_bank", ""),
        }

        return StateBuilder()\
            .set("detailed_plan", result["detailed_plan_report"])\
            .set("detailed_dimension_reports", detailed_dimension_reports)\
            .set("layer_3_completed", True)\
            .set("current_layer", 4)\
            .set("last_checkpoint_id", checkpoint_id)\
            .add_message(f"详细规划已生成，包含 {len(result.get('completed_dimensions', []))} 个专业维度。")\
            .build()


__all__ = [
    "BaseLayerNode",
    "Layer1AnalysisNode",
    "Layer2ConceptNode",
    "Layer3DetailNode",
]
