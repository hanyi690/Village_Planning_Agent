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


# GIS Analysis Tool
# Used in: main_graph.py, execute_tools_node for GIS visualization after review
GIS_ANALYSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "GISAnalysis",
        "description": "将规划方案转换为 GIS 可视化图层。在规划审查后，根据用户请求（如'分析用地布局'、'生成交通规划图'）执行对应维度的 GIS 工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "dimension_key": {
                    "type": "string",
                    "description": "维度标识（如 traffic, land_use, natural_environment, public_services 等）"
                },
                "village_name": {
                    "type": "string",
                    "description": "村庄名称（可选，默认使用当前规划项目的村庄名）"
                },
                "analysis_type": {
                    "type": "string",
                    "description": "分析类型（可选，如 'service_coverage', 'isochrone', 'sensitivity' 等）"
                }
            },
            "required": ["dimension_key"]
        }
    }
}


__all__ = ["ADVANCE_PLANNING_TOOL", "GIS_ANALYSIS_TOOL"]