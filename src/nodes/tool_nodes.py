"""
工具节点实现

将工具调用封装为独立的节点类，利用现有工具。
"""

from typing import Dict, Any

from .base_node import BaseNode
from ..core.state_builder import StateBuilder
from ..tools.interactive_tool import InteractiveTool
from ..tools.checkpoint_tool import CheckpointTool
from ..tools.revision_tool import RevisionTool
from ..tools.web_review_tool import WebReviewTool
from ..utils.logger import get_logger
from ..utils.checkpoint_manager import get_checkpoint_manager

logger = get_logger(__name__)


class ToolBridgeNode(BaseNode):
    """
    工具桥接节点 - 统一管理所有工具调用

    使用现有的InteractiveTool、CheckpointTool、RevisionTool。
    新增：支持适配器调用（GIS、Network、Population适配器）

    根据状态标志路由到相应的子工具节点：
    - use_gis_adapter: GIS适配器分析
    - use_network_adapter: 网络适配器分析
    - use_population_adapter: 人口预测适配器
    - need_human_review: 人工审查
    - pause_after_step: 暂停
    - need_revision: 修复
    """

    def __init__(self):
        super().__init__("工具桥接")
        # 初始化子工具节点
        self.human_review_node = HumanReviewNode()
        self.pause_interaction_node = PauseInteractionNode()
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
        # 优先级：适配器调用 > 人工审查 > 暂停 > 修复

        # 新增：检查是否需要调用适配器
        if state.get("use_gis_adapter", False):
            return self._run_gis_adapter(state)
        elif state.get("use_network_adapter", False):
            return self._run_network_adapter(state)
        elif state.get("use_population_adapter", False):
            return self._run_population_adapter(state)

        # 现有逻辑
        if state.get("need_human_review", False):
            return self.human_review_node(state)
        elif state.get("pause_after_step", False):
            # ✅ 修复：Web模式下不进入CLI交互循环
            # 返回空状态，让pause_after_step保持为True
            # streaming.py会检测到并发送pause事件
            logger.info("[ToolBridge] pause_after_step=True，不进入CLI交互，等待streaming.py处理")
            return {}
        elif state.get("need_revision", False):
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


class HumanReviewNode(BaseNode):
    """Web环境人工审查节点 - 非阻塞，基于SSE事件"""

    def __init__(self):
        super().__init__("人工审查")
        self.web_review_tool = WebReviewTool()

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Web环境审查 - 触发图执行中断

        流程:
        1. 创建审查请求
        2. 设置 waiting_for_review 标志
        3. 设置 __interrupt__ 标志以终止图执行
        4. 前端通过SSE事件接收通知
        5. 前端调用 /api/planning/review/{session_id}
        6. 后端恢复执行
        """
        current_layer = state.get("current_layer", 1)
        session_id = state.get("session_id", "")

        # 获取当前内容
        content_map = {
            1: ("analysis_report", "现状分析报告"),
            2: ("planning_concept", "规划思路报告"),
            3: ("detailed_plan", "详细规划报告")
        }
        content_key, title = content_map.get(current_layer, ("analysis_report", "报告"))
        content = state.get(content_key, "")

        # 获取检查点列表
        checkpoint_manager = get_checkpoint_manager(
            project_name=state["project_name"],
            timestamp=state.get("session_id")
        )
        available_checkpoints = []
        if checkpoint_manager:
            list_result = checkpoint_manager.list()
            if list_result.get("success"):
                available_checkpoints = list_result.get("checkpoints", [])

        # 获取可用维度（Layer 3）
        available_dimensions = None
        if current_layer == 3:
            available_dimensions = [
                "产业规划", "村域总体规划", "综合交通规划",
                "公共服务设施规划", "基础设施规划", "生态绿地系统规划",
                "防灾减灾规划", "历史文化保护规划", "村庄风貌规划", "项目库"
            ]

        # 创建审查请求（不阻塞）
        result = self.web_review_tool.request_review(
            content=content,
            title=title,
            session_id=session_id,
            current_layer=current_layer,
            available_checkpoints=available_checkpoints,
            available_dimensions=available_dimensions
        )

        review_id = result.get("review_id", "")

        logger.info(f"[HumanReviewNode] Triggering graph interruption for review: {review_id}")

        return {
            "review_id": review_id,
            "waiting_for_review": True,
            "review_content": content,
            "review_title": title,
            "current_layer": current_layer,
            "need_human_review": False,  # 清除，避免重复触发
            "__interrupt__": True  # NEW: Signal to interrupt graph execution
        }


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
        # 【新增】支持用户精确指定维度
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


class PauseInteractionNode(BaseNode):
    """暂停交互节点 - 使用现有InteractiveTool"""

    def __init__(self):
        super().__init__("暂停交互")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行暂停交互"""
        tool = InteractiveTool()

        # 显示进度
        tool.show_progress(state)

        # 交互循环
        while True:
            # 获取用户命令
            menu_result = tool.show_menu()
            if not menu_result["success"]:
                continue

            command = menu_result["command"]
            exec_result = tool.execute_command(command, state)

            action = exec_result.get("action", "")
            modified_state = exec_result.get("modified_state", {})

            # Preserve layer completion state
            preserved_state = {
                "layer_1_completed": state.get("layer_1_completed", False),
                "layer_2_completed": state.get("layer_2_completed", False),
                "layer_3_completed": state.get("layer_3_completed", False),
                "current_layer": state.get("current_layer", 1),
            }

            if action == "continue":
                logger.info("[暂停交互] 继续执行")
                return StateBuilder()\
                    .set("pause_after_step", False)\
                    .add_message("继续执行")\
                    .build()
            elif action == "rollback":
                checkpoint_id = exec_result.get("checkpoint_id", "")
                logger.info(f"[暂停交互] 回退到: {checkpoint_id}")
                return StateBuilder()\
                    .set("trigger_rollback", True)\
                    .set("rollback_target", checkpoint_id)\
                    .add_message(f"回退到checkpoint: {checkpoint_id}")\
                    .build()
            elif action == "quit":
                logger.info("[暂停交互] 用户退出")
                return StateBuilder()\
                    .set("quit_requested", True)\
                    .add_message("用户退出程序")\
                    .build()
            # 其他action保持暂停状态


class PauseManagerNode(BaseNode):
    """暂停管理节点"""

    def __init__(self):
        super().__init__("暂停管理")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        暂停管理节点：统一管理各种暂停场景

        支持的暂停场景：
        - step_mode: 逐步执行模式
        - 人工审核: need_human_review (未来扩展)
        - 其他暂停场景: 易于扩展
        """
        # Step模式：设置暂停
        if state.get("step_mode", False):
            logger.info("[暂停管理] Step模式已启用，设置pause_after_step=True")
            return {"pause_after_step": True}

        # 未来扩展：其他暂停场景
        # if state.get("need_human_review", False):
        #     logger.info("[暂停管理] 人工审核模式，设置pause_after_step=True")
        #     return {"pause_after_step": True}

        return {}


# ==========================================
# 辅助函数（用于向后兼容main_graph.py中的引用）
# ==========================================

def _run_human_review(state: Dict[str, Any]) -> Dict[str, Any]:
    """执行人工审查（向后兼容函数）"""
    node = HumanReviewNode()
    return node.execute(state)


def _run_pause_interaction(state: Dict[str, Any]) -> Dict[str, Any]:
    """执行暂停交互（向后兼容函数）"""
    node = PauseInteractionNode()
    return node.execute(state)


def _run_revision(state: Dict[str, Any]) -> Dict[str, Any]:
    """执行修复（向后兼容函数）"""
    node = RevisionNode()
    return node.execute(state)


__all__ = [
    "ToolBridgeNode",
    "HumanReviewNode",
    "RevisionNode",
    "PauseInteractionNode",
    "PauseManagerNode",
    # 辅助函数（用于向后兼容）
    "_run_human_review",
    "_run_pause_interaction",
    "_run_revision",
]
