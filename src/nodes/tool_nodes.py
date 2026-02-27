"""
工具节点实现

将工具调用封装为独立的节点类，利用现有工具。
"""

from typing import Dict, Any

from .base_node import BaseNode
from ..core.state_builder import StateBuilder
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
    """修复工具节点 - 使用现有RevisionTool，支持依赖维度级联更新"""

    def __init__(self):
        super().__init__("修复")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行修复 - 增强版：支持精确维度选择 + 依赖维度级联更新

        支持两种模式：
        1. 精确维度模式：使用用户选择的维度（target_dimensions）
        2. 自动识别模式：使用关键词自动识别维度（原有机制）

        修复完成后会自动更新依赖该维度的下游维度。
        """
        logger.info("=" * 60)
        logger.info("[修复] RevisionNode.execute 开始执行")
        logger.info("=" * 60)
        
        feedback = state.get("human_feedback", "")
        if not feedback:
            logger.warning("[修复] 没有 human_feedback，跳过修复")
            return StateBuilder().set("need_revision", False).build()

        # 调试日志：显示状态信息
        logger.info(f"[修复] human_feedback: {feedback[:100]}...")
        logger.info(f"[修复] need_revision: {state.get('need_revision')}")
        logger.info(f"[修复] revision_target_dimensions: {state.get('revision_target_dimensions')}")
        logger.info(f"[修复] current_layer: {state.get('current_layer')}")
        
        # 检查状态中的报告
        detail_reports = state.get("detail_reports", {})
        logger.info(f"[修复] detail_reports 键列表: {list(detail_reports.keys())}")
        
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
        logger.info(f"[修复] 开始调用 revise_multiple，维度: {dimensions}")
        revise_result = tool.revise_multiple(
            dimensions=dimensions,
            state=state,
            feedback=feedback
        )
        
        logger.info(f"[修复] revise_multiple 结果: success={revise_result['success']}")
        logger.info(f"[修复]   - revised_results 键: {list(revise_result.get('revised_results', {}).keys())}")
        logger.info(f"[修复]   - failed_dimensions: {revise_result.get('failed_dimensions', [])}")
        logger.info(f"[修复]   - skipped_dimensions: {revise_result.get('skipped_dimensions', [])}")

        if not revise_result["success"]:
            logger.warning("[修复] revise_multiple 失败，返回")
            return StateBuilder().set("need_revision", False).build()

        # 3. 处理下游依赖维度更新
        revised_results = revise_result["revised_results"]
        original_results = revise_result.get("original_results", {})
        
        downstream_updates = self._process_downstream_dependencies(
            revised_results=revised_results,
            original_results=original_results,
            state=state,
            tool=tool
        )
        
        # 合并修复结果和下游更新结果
        all_updates = {**revised_results, **downstream_updates}
        
        # 4. 更新状态 - 根据维度层级更新正确的数据源
        from ..config.dimension_metadata import get_dimension_layer
        
        # 分别收集各层级的更新
        analysis_updates = {}
        concept_updates = {}
        detail_updates = {}
        
        for dimension, revised_result in all_updates.items():
            layer = get_dimension_layer(dimension)
            if layer == 1:
                analysis_updates[dimension] = revised_result
            elif layer == 2:
                concept_updates[dimension] = revised_result
            else:  # layer == 3 或 None
                detail_updates[dimension] = revised_result
        
        # 更新各层级报告
        analysis_reports = state.get("analysis_reports", {})
        concept_reports = state.get("concept_reports", {})
        detail_reports = state.get("detail_reports", {})
        
        # 【新增】在覆盖前保存旧版本到修订历史
        from datetime import datetime
        revision_history = state.get("revision_history", [])
        
        for dimension, new_content in revised_results.items():
            layer = get_dimension_layer(dimension)
            # 获取旧版本内容
            if layer == 1:
                old_content = analysis_reports.get(dimension, "")
            elif layer == 2:
                old_content = concept_reports.get(dimension, "")
            else:
                old_content = detail_reports.get(dimension, "")
            
            # 保存到历史记录
            revision_entry = {
                "dimension": dimension,
                "layer": layer,
                "old_content": old_content,
                "new_content": new_content,
                "feedback": feedback,
                "timestamp": datetime.now().isoformat()
            }
            revision_history.append(revision_entry)
            logger.info(f"[修复] 已保存维度 {dimension} 的修订历史")
        
        analysis_reports.update(analysis_updates)
        concept_reports.update(concept_updates)
        detail_reports.update(detail_updates)

        # 重新组合综合报告（仅更新 detail_reports 对应的综合报告）
        updated_detailed_plan = state.get("detailed_plan", "")
        for dimension, result in detail_updates.items():
            updated_detailed_plan += f"\n\n## 修复后的{dimension}规划\n\n{result}"

        # 构建日志消息
        msg_parts = [f"已修复 {len(revised_results)} 个维度"]
        if downstream_updates:
            msg_parts.append(f"级联更新 {len(downstream_updates)} 个依赖维度")
        
        logger.info(f"[修复] 完成: {', '.join(msg_parts)}")
        if analysis_updates:
            logger.info(f"[修复] Layer 1 更新: {list(analysis_updates.keys())}")
        if concept_updates:
            logger.info(f"[修复] Layer 2 更新: {list(concept_updates.keys())}")
        if detail_updates:
            logger.info(f"[修复] Layer 3 更新: {list(detail_updates.keys())}")
        logger.info("=" * 60)
        
        # 【新增】设置 last_revised_dimensions 标志用于 SSE 事件触发
        revised_dimensions = list(revised_results.keys())
        logger.info(f"[修复] 设置 last_revised_dimensions: {revised_dimensions}")
        
        return StateBuilder()\
            .set("analysis_reports", analysis_reports)\
            .set("concept_reports", concept_reports)\
            .set("detail_reports", detail_reports)\
            .set("detailed_plan", updated_detailed_plan)\
            .set("need_revision", False)\
            .set("revision_history", revision_history)\
            .set("last_revised_dimensions", revised_dimensions)\
            .add_message("，".join(msg_parts))\
            .build()

    def _process_downstream_dependencies(
        self,
        revised_results: Dict[str, str],
        original_results: Dict[str, str],
        state: Dict[str, Any],
        tool: RevisionTool
    ) -> Dict[str, str]:
        """
        处理下游依赖维度的级联更新

        对每个修复的维度：
        1. 计算其下游依赖维度
        2. 检查下游维度是否已生成（进度检查）
        3. 生成变更摘要作为 feedback
        4. 调用修复工具更新下游维度

        Args:
            revised_results: 修复后的维度结果 {dimension: revised_content}
            original_results: 原始维度结果 {dimension: original_content}
            state: 当前状态
            tool: RevisionTool 实例

        Returns:
            更新后的下游维度结果 {dimension: revised_content}
        """
        from ..config.dimension_metadata import get_downstream_dependencies
        
        downstream_updates = {}
        processed = set(revised_results.keys())  # 避免重复处理

        for dim, new_result in revised_results.items():
            # 获取下游依赖维度
            downstream_dims = get_downstream_dependencies(dim)
            
            if not downstream_dims:
                continue
            
            logger.info(f"[修复] 维度 {dim} 的下游依赖: {downstream_dims}")

            for dep_dim in downstream_dims:
                if dep_dim in processed:
                    continue  # 避免重复处理

                # 进度检查：只更新已生成的维度
                existing = tool._get_dimension_result(dep_dim, state)
                if not existing:
                    logger.info(f"[修复] 跳过未生成的下游维度: {dep_dim}")
                    continue

                try:
                    # 生成变更摘要
                    original = original_results.get(dim, "")
                    change_summary = tool.generate_change_summary(
                        original=original,
                        revised=new_result,
                        target_dimension=dep_dim
                    )

                    # 使用变更摘要作为 feedback 更新下游维度
                    logger.info(f"[修复] 级联更新下游维度 {dep_dim}")
                    result = tool.revise_dimension(
                        dimension=dep_dim,
                        state=state,
                        feedback=f"上游维度 {dim} 更新: {change_summary}",
                        original_result=existing,
                        revision_count=0
                    )

                    if result["success"]:
                        downstream_updates[dep_dim] = result["revised_result"]
                        processed.add(dep_dim)
                        logger.info(f"[修复] 下游维度 {dep_dim} 更新完成")
                    else:
                        logger.warning(f"[修复] 下游维度 {dep_dim} 更新失败: {result.get('error')}")

                except Exception as e:
                    logger.error(f"[修复] 处理下游维度 {dep_dim} 时出错: {e}")

        return downstream_updates


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