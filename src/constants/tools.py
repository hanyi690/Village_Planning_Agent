"""
Tool Definitions - Shared Tool Constants

Tool definitions used across the application.
"""

# Advance Planning Intent Tool
# Used in: main_graph.py, intent_router.py
ADVANCE_PLANNING_TOOL = {
    "type": "function",
    "function": {
        "name": "AdvancePlanningIntent",
        "description": "推进规划流程到下一阶段。当用户表示要继续规划、开始分析、下一步时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "推进规划的原因"
                }
            },
            "required": []
        }
    }
}


__all__ = ["ADVANCE_PLANNING_TOOL"]