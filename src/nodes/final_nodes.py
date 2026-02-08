"""
最终成果节点

生成最终规划成果的节点实现。
"""

from typing import Dict, Any

from .base_node import BaseNode
from ..utils.logger import get_logger

logger = get_logger(__name__)


class GenerateFinalOutputNode(BaseNode):
    """最终成果生成节点"""

    def __init__(self):
        super().__init__("最终成果生成")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成最终规划成果

        整合三层输出，生成完整的规划文档。
        """
        logger.info(f"[{self.node_name}] 开始生成最终成果，项目: {state['project_name']}")

        final_output = f"""
# {state['project_name']} 村庄规划成果

---

## 一、现状分析报告

{state['analysis_report']}

---

## 二、规划思路

{state['planning_concept']}

---

## 三、详细规划方案

{state['detailed_plan']}

---

**生成时间**: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**说明**: 本成果由 AI 村庄规划系统生成，仅供参考。实际规划需结合专业评估和审批流程。
"""

        logger.info(f"[{self.node_name}] 最终成果生成完成，总长度: {len(final_output)} 字符")

        # 保存最终综合报告（使用 OutputManager）- 从registry获取
        from ..utils.output_manager_registry import get_output_manager_registry
        registry = get_output_manager_registry()
        output_manager = registry.get(state.get("session_id"))
        final_output_path = None
        if output_manager:
            try:
                final_output_path = output_manager.save_final_combined(final_output)
            except Exception as save_error:
                logger.warning(f"[{self.node_name}] 保存最终报告时出错: {save_error}")

        return {
            "final_output": final_output,
            "final_output_path": final_output_path
        }


__all__ = ["GenerateFinalOutputNode"]
