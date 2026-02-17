"""
工具节点实现

将工具调用封装为独立的节点类，利用现有工具。
"""

from typing import Dict, Any

from .base_node import BaseNode
from ..core.state_builder import StateBuilder
from ..tools.checkpoint_tool import CheckpointTool
from ..tools.revision_tool import RevisionTool
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ToolBridgeNode(BaseNode):
    """
    工具桥接节点 - 统一管理所有工具调用

    支持适配器调用（GIS、Network、Population适配器）

    根据状态标志路由到相应的处理逻辑：
    - use_gis_adapter: GIS适配器分析
    - use_network_adapter: 网络适配器分析
    - use_population_adapter: 人口预测适配器
    - need_revision: 修复
    """

    def __init__(self):
        super().__init__("工具桥接")
        self.revision_node = RevisionNode()
        # 新增：导入适配器工厂（延迟导入避免循环依赖）
        self._adapter_factory = None

    @property
    def adapter_factory(self):
        """延迟加载适配器工厂"""
        if self._adapter_factory is None:
            from ..tools.adapters import get_adapter_factory
            self._adapter_factory = get_adapter_factory()
        return self._adapter_factory

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """根据状态标志路由到相应的处理逻辑"""
        # 优先级：适配器调用 > 修复

        # 检查是否需要调用适配器
        if state.get("use_gis_adapter", False):
            return self._run_gis_adapter(state)
        elif state.get("use_network_adapter", False):
            return self._run_network_adapter(state)
        elif state.get("use_population_adapter", False):
            return self._run_population_adapter(state)

        # 修复逻辑
        if state.get("need_revision", False):
            return self.revision_node(state)
        else:
            return {}  # 无操作

    def _run_gis_adapter(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """运行GIS适配器"""
        analysis_type = state.get("gis_analysis_type", "land_use_analysis")

        result = self.adapter_factory.run_adapter(
            "gis",
            analysis_type=analysis_type,
            village_data=state.get("village_data", {})
        )

        # 发布结果到黑板
        blackboard = state.get("blackboard")
        if blackboard:
            blackboard.publish_tool_result(
                tool_id=f"gis_{analysis_type}",
                tool_name="GIS空间分析",
                result=result.data,
                metadata=result.metadata,
                success=result.success,
                error=result.error
            )

        from ..core.state_builder import StateBuilder
        return StateBuilder()\
            .set("use_gis_adapter", False)\
            .set("last_adapter_result", result.to_dict())\
            .add_message(f"GIS分析完成: {analysis_type}")\
            .build()

    def _run_network_adapter(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """运行网络分析适配器"""
        analysis_type = state.get("network_analysis_type", "connectivity")
        network_data = state.get("network_data", {})

        result = self.adapter_factory.run_adapter(
            "network",
            analysis_type=analysis_type,
            network_data=network_data
        )

        # 发布结果到黑板
        blackboard = state.get("blackboard")
        if blackboard:
            blackboard.publish_tool_result(
                tool_id=f"network_{analysis_type}",
                tool_name="网络分析",
                result=result.data,
                metadata=result.metadata,
                success=result.success,
                error=result.error
            )

        from ..core.state_builder import StateBuilder
        return StateBuilder()\
            .set("use_network_adapter", False)\
            .set("last_adapter_result", result.to_dict())\
            .add_message(f"网络分析完成: {analysis_type}")\
            .build()

    def _run_population_adapter(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """运行人口预测适配器"""
        prediction_type = state.get("population_prediction_type", "basic")
        current_population = state.get("current_population", 0)
        years = state.get("prediction_years", 10)

        result = self.adapter_factory.run_adapter(
            "population",
            prediction_type=prediction_type,
            current_population=current_population,
            years=years
        )

        # 发布结果到黑板
        blackboard = state.get("blackboard")
        if blackboard:
            blackboard.publish_tool_result(
                tool_id=f"population_{prediction_type}",
                tool_name="人口预测",
                result=result.data,
                metadata=result.metadata,
                success=result.success,
                error=result.error
            )

        from ..core.state_builder import StateBuilder
        return StateBuilder()\
            .set("use_population_adapter", False)\
            .set("last_adapter_result", result.to_dict())\
            .add_message(f"人口预测完成: {prediction_type}")\
            .build()


class RevisionNode(BaseNode):
    """修复工具节点 - 使用现有RevisionTool"""

    def __init__(self):
        super().__init__("修复")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行修复 - 增强版：支持精确维度选择

        支持两种模式：
        1. 精确维度模式：使用用户选择的维度（target_dimensions）
        2. 自动识别模式：使用关键词自动识别维度（原有机制）
        """
        feedback = state.get("human_feedback", "")
        if not feedback:
            return StateBuilder().set("need_revision", False).build()

        # 使用现有RevisionTool
        tool = RevisionTool()

        # 1. 获取需要修复的维度
        # 支持用户精确指定维度
        target_dimensions = state.get("revision_target_dimensions")

        if target_dimensions:
            # 使用用户指定的维度
            dimensions = target_dimensions
            logger.info(f"[修复] 使用用户指定的维度: {dimensions}")
        else:
            # 使用自动识别（现有机制）
            parse_result = tool.parse_feedback(feedback)
            dimensions = parse_result["dimensions"] if parse_result["success"] else []
            logger.info(f"[修复] 自动识别的维度: {dimensions}")

        if not dimensions:
            logger.warning("[修复] 没有识别到需要修复的维度")
            return StateBuilder().set("need_revision", False).build()

        # 2. 逐个修复维度（使用DimensionPlanner）
        revise_result = tool.revise_multiple(
            dimensions=dimensions,
            state=state,
            feedback=feedback
        )

        if not revise_result["success"]:
            return StateBuilder().set("need_revision", False).build()

        # 3. 更新状态
        revised_results = revise_result["revised_results"]
        detailed_dimension_reports = state.get("detailed_dimension_reports", {})

        dimension_key_map = {
            "industry": "dimension_industry",
            "master_plan": "dimension_master_plan",
            "traffic": "dimension_traffic",
            "public_service": "dimension_public_service",
            "infrastructure": "dimension_infrastructure",
            "ecological": "dimension_ecological",
            "disaster_prevention": "dimension_disaster_prevention",
            "heritage": "dimension_heritage",
            "landscape": "dimension_landscape",
            "project_bank": "dimension_project_bank"
        }

        for dimension, revised_result in revised_results.items():
            key = dimension_key_map.get(dimension)
            if key:
                detailed_dimension_reports[key] = revised_result

        # 重新组合综合报告
        updated_detailed_plan = state.get("detailed_plan", "")
        for key, result in revised_results.items():
            dimension_name = key.replace("dimension_", "")
            updated_detailed_plan += f"\n\n## 修复后的{dimension_name}规划\n\n{result}"

        return StateBuilder()\
            .set("detailed_dimension_reports", detailed_dimension_reports)\
            .set("detailed_plan", updated_detailed_plan)\
            .set("need_revision", False)\
            .add_message(f"已修复 {len(revised_results)} 个维度")\
            .build()


# ==========================================
# 辅助函数（用于向后兼容main_graph.py中的引用）
# ==========================================

def _run_revision(state: Dict[str, Any]) -> Dict[str, Any]:
    """执行修复（向后兼容函数）"""
    node = RevisionNode()
    return node.execute(state)


__all__ = [
    "ToolBridgeNode",
    "RevisionNode",
    # 辅助函数（用于向后兼容）
    "_run_revision",
]