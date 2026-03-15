"""
工具节点实现

将工具调用封装为独立的节点类，利用现有工具。
"""

from typing import Dict, Any, List

from .base_node import BaseNode, AsyncBaseNode
from ..core.state_builder import StateBuilder
from ..core.checkpoint_types import CheckpointMetadata, CheckpointType, PlanningPhase
from ..tools.revision_tool import RevisionTool
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ToolBridgeNode(AsyncBaseNode):
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

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """根据状态标志路由到相应的处理逻辑"""
        # 优先级：适配器调用 > 修复

        # 检查是否需要调用适配器
        if state.get("use_gis_adapter", False):
            return self._run_gis_adapter(state)
        elif state.get("use_network_adapter", False):
            return self._run_network_adapter(state)
        elif state.get("use_population_adapter", False):
            return self._run_population_adapter(state)

        # 修复逻辑 - 使用 await 调用异步节点
        if state.get("need_revision", False):
            return await self.revision_node(state)
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

        return StateBuilder()\
            .set("use_population_adapter", False)\
            .set("last_adapter_result", result.to_dict())\
            .add_message(f"人口预测完成: {prediction_type}")\
            .build()


class RevisionNode(AsyncBaseNode):
    """
    修复工具节点 - 使用 RevisionSubgraph 实现并行修复
    
    特性：
    1. 使用 LangGraph Send 机制实现并行修复
    2. 复用 dimension_metadata.py 的依赖关系计算
    3. 按 wave 分组执行，确保依赖顺序正确
    4. 支持状态筛选，每个维度只接收依赖的上下文
    """

    def __init__(self):
        super().__init__("修复")

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行修复 - 使用 RevisionSubgraph 并行处理
        
        支持两种模式：
        1. 精确维度模式：使用用户选择的维度（revision_target_dimensions）
        2. 自动识别模式：使用关键词自动识别维度（原有机制）
        """
        logger.info("=" * 60)
        logger.info("[修复] RevisionNode.execute 开始执行（并行版本）")
        logger.info("=" * 60)
        
        feedback = state.get("human_feedback", "")
        if not feedback:
            logger.warning("[修复] 没有 human_feedback，跳过修复")
            return StateBuilder().set("need_revision", False).build()

        # 调试日志
        logger.info(f"[修复] human_feedback: {feedback[:100]}...")
        logger.info(f"[修复] need_revision: {state.get('need_revision')}")
        
        # 1. 获取需要修复的维度
        target_dimensions = state.get("revision_target_dimensions")

        if target_dimensions:
            dimensions = target_dimensions
            logger.info(f"[修复] 使用用户指定的维度: {dimensions}")
        else:
            # 使用自动识别
            tool = RevisionTool()
            parse_result = tool.parse_feedback(feedback)
            dimensions = parse_result["dimensions"] if parse_result["success"] else []
            logger.info(f"[修复] 自动识别的维度: {dimensions}")

        if not dimensions:
            logger.warning("[修复] 没有识别到需要修复的维度")
            return StateBuilder().set("need_revision", False).build()

        # 2. 调用 RevisionSubgraph 进行并行修复
        from ..subgraphs.revision_subgraph import call_revision_subgraph
        
        # 获取已完成的维度（用于过滤）
        completed_dimensions = self._get_completed_dimensions(state)
        
        revision_result = await call_revision_subgraph(
            project_name=state.get("project_name", ""),
            feedback=feedback,
            target_dimensions=dimensions,
            analysis_reports=state.get("analysis_reports", {}),
            concept_reports=state.get("concept_reports", {}),
            detail_reports=state.get("detail_reports", {}),
            completed_dimensions=completed_dimensions
        )
        
        logger.info(f"[修复] RevisionSubgraph 结果: success={revision_result['success']}")
        
        if not revision_result["success"]:
            logger.warning("[修复] RevisionSubgraph 执行失败")
            return StateBuilder().set("need_revision", False).build()

        # 3. 更新主状态
        updated_reports = revision_result.get("updated_reports", {})
        revision_history = revision_result.get("revision_history", [])
        
        # 分别更新各层级报告
        from ..config.dimension_metadata import get_dimension_layer
        
        analysis_reports = dict(state.get("analysis_reports", {}))
        concept_reports = dict(state.get("concept_reports", {}))
        detail_reports = dict(state.get("detail_reports", {}))
        
        for dimension, revised_content in updated_reports.items():
            layer = get_dimension_layer(dimension)
            if layer == 1:
                analysis_reports[dimension] = revised_content
            elif layer == 2:
                concept_reports[dimension] = revised_content
            else:
                detail_reports[dimension] = revised_content
        
        # 合并修订历史
        existing_history = list(state.get("revision_history", []))
        existing_history.extend(revision_history)
        
        # 构建日志消息
        msg_parts = [f"已修复 {len(updated_reports)} 个维度（并行处理）"]
        
        logger.info(f"[修复] 完成: {', '.join(msg_parts)}")
        logger.info(f"[修复] 更新的维度: {list(updated_reports.keys())}")
        logger.info("=" * 60)
        
        # 设置 last_revised_dimensions 标志用于 SSE 事件触发
        revised_dimensions = list(updated_reports.keys())
        logger.info(f"[修复] 设置 last_revised_dimensions: {revised_dimensions}")

        # 创建修复完成检查点元数据（标记为关键检查点，支持回滚）
        current_layer = state.get("current_layer", 1)

        # 根据当前层推断修复完成阶段
        phase_map = {
            1: PlanningPhase.LAYER1_ANALYZING,
            2: PlanningPhase.LAYER2_CONCEPTING,
            3: PlanningPhase.LAYER3_PLANNING,
        }
        repair_phase = phase_map.get(current_layer, PlanningPhase.INIT)

        repair_meta = CheckpointMetadata(
            type=CheckpointType.KEY,
            phase=repair_phase,
            layer=current_layer,
            description=f"修复完成（Layer {current_layer}）"
        )

        # 合并现有 metadata
        existing_metadata = state.get("metadata", {})
        new_metadata = {**existing_metadata, **repair_meta.to_dict()}

        return StateBuilder()\
            .set("analysis_reports", analysis_reports)\
            .set("concept_reports", concept_reports)\
            .set("detail_reports", detail_reports)\
            .set("need_revision", False)\
            .set("revision_history", existing_history)\
            .set("last_revised_dimensions", revised_dimensions)\
            .set("metadata", new_metadata)\
            .add_message("，".join(msg_parts))\
            .build()

    def _get_completed_dimensions(self, state: Dict[str, Any]) -> List[str]:
        """获取已完成的维度列表"""
        completed = []
        
        # Layer 1
        analysis_reports = state.get("analysis_reports", {})
        completed.extend(analysis_reports.keys())
        
        # Layer 2
        concept_reports = state.get("concept_reports", {})
        completed.extend(concept_reports.keys())
        
        # Layer 3
        detail_reports = state.get("detail_reports", {})
        completed.extend(detail_reports.keys())
        
        return list(set(completed))  # 去重


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