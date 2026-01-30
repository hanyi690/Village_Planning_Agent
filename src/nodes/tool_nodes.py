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
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ToolBridgeNode(BaseNode):
    """
    工具桥接节点 - 统一管理所有工具调用

    使用现有的InteractiveTool、CheckpointTool、RevisionTool。

    根据状态标志路由到相应的子工具节点：
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

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """根据状态标志路由到相应的子工具节点"""
        # 优先级：人工审查 > 暂停 > 修复
        if state.get("need_human_review", False):
            return self.human_review_node(state)
        elif state.get("pause_after_step", False):
            return self.pause_interaction_node(state)
        elif state.get("need_revision", False):
            return self.revision_node(state)
        else:
            return {}  # 无操作


class HumanReviewNode(BaseNode):
    """人工审查工具节点 - 使用现有InteractiveTool"""

    def __init__(self):
        super().__init__("人工审查")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行人工审查"""
        # 获取当前内容
        current_layer = state.get("current_layer", 1)
        content_map = {
            1: ("analysis_report", "现状分析报告"),
            2: ("planning_concept", "规划思路报告"),
            3: ("detailed_plan", "详细规划报告")
        }
        content_key, title = content_map.get(current_layer, ("analysis_report", "报告"))
        content = state.get(content_key, "")

        # 获取checkpoint列表（使用现有CheckpointTool）
        checkpoint_manager = state.get("checkpoint_manager")
        available_checkpoints = []
        if checkpoint_manager and isinstance(checkpoint_manager, CheckpointTool):
            list_result = checkpoint_manager.list()
            if list_result["success"]:
                available_checkpoints = list_result["checkpoints"]

        # 执行人工审查（使用现有InteractiveTool）
        tool = InteractiveTool()
        result = tool.review_content(
            content=content,
            title=title,
            allow_rollback=True,
            available_checkpoints=available_checkpoints
        )

        # 处理结果
        action = result.get("action", "")
        if action == "approve":
            return StateBuilder()\
                .set("need_human_review", False)\
                .set("human_feedback", "")\
                .add_message("人工审查通过")\
                .build()
        elif action == "reject":
            return StateBuilder()\
                .set("need_human_review", False)\
                .set("human_feedback", result.get("feedback", ""))\
                .set("need_revision", True)\
                .add_message(f"人工审查驳回，反馈: {result.get('feedback', '')}")\
                .build()
        elif action == "rollback":
            return StateBuilder()\
                .set("trigger_rollback", True)\
                .set("rollback_target", result.get("checkpoint_id", ""))\
                .add_message(f"回退到checkpoint: {result.get('checkpoint_id', '')}")\
                .build()
        elif action == "quit":
            return StateBuilder()\
                .set("quit_requested", True)\
                .add_message("用户退出程序")\
                .build()
        else:
            return StateBuilder()\
                .set("need_human_review", False)\
                .add_message("人工审查完成（默认通过）")\
                .build()


class RevisionNode(BaseNode):
    """修复工具节点 - 使用现有RevisionTool"""

    def __init__(self):
        super().__init__("修复")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行修复"""
        feedback = state.get("human_feedback", "")
        if not feedback:
            return StateBuilder().set("need_revision", False).build()

        # 使用现有RevisionTool
        tool = RevisionTool()

        # 1. 识别需要修复的维度
        parse_result = tool.parse_feedback(feedback)
        dimensions = parse_result["dimensions"] if parse_result["success"] else []

        if not dimensions:
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
