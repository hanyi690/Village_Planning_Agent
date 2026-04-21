"""
工具注册中心 - 简化版

支持装饰器注册和动态调用，移除适配器层嵌套。
"""

from typing import Any, Callable, Dict, List, Optional, Type
from dataclasses import dataclass
from pydantic import BaseModel
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolMetadata:
    """工具元数据（用于 LLM bind_tools）"""

    name: str
    description: str
    input_schema: Optional[Type[BaseModel]] = None
    display_name: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    display_hints: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.display_name is None:
            self.display_name = self.name
        if self.display_hints is None:
            self.display_hints = {"primary_view": "text", "priority_fields": []}

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 格式"""
        schema = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
            }
        }

        if self.parameters:
            schema["function"]["parameters"] = self.parameters
        elif self.input_schema:
            schema["function"]["parameters"] = self.input_schema.model_json_schema()

        return schema


# 工具参数 Schema（JSON Schema 格式）
TOOL_PARAMETER_SCHEMAS = {
    "gis_analysis": {
        "type": "object",
        "properties": {
            "analysis_type": {
                "type": "string",
                "enum": ["land_use_analysis", "soil_analysis", "hydrology_analysis"],
                "description": "分析类型"
            },
            "geo_data_path": {"type": "string", "description": "数据文件路径"},
        },
        "required": ["analysis_type"]
    },
    "network_analysis": {
        "type": "object",
        "properties": {
            "analysis_type": {
                "type": "string",
                "enum": ["connectivity_metrics", "accessibility_analysis", "centrality_analysis"],
                "description": "分析类型"
            },
            "network_data": {"type": "object", "description": "网络数据"},
        },
        "required": ["analysis_type"]
    },
    "population_prediction": {
        "type": "object",
        "properties": {
            "analysis_type": {
                "type": "string",
                "enum": ["population_forecast", "village_forecast", "population_structure", "labor_force_analysis"],
                "description": "分析类型"
            },
            "baseline_population": {"type": "integer", "description": "基期人口数"},
            "baseline_year": {"type": "integer", "description": "基期年份"},
        },
        "required": ["baseline_population", "baseline_year"]
    },
    "accessibility_analysis": {
        "type": "object",
        "properties": {
            "analysis_type": {
                "type": "string",
                "enum": ["driving_accessibility", "walking_accessibility", "service_coverage", "poi_coverage"],
                "description": "分析类型"
            },
            "origin": {"type": "array", "items": {"type": "number"}, "description": "起点坐标 [lon, lat]"},
            "center": {"type": "array", "items": {"type": "number"}, "description": "中心坐标 [lon, lat]"},
        },
        "required": ["analysis_type"]
    },
    "knowledge_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索查询"},
            "top_k": {"type": "integer", "default": 5, "description": "返回结果数量"},
        },
        "required": ["query"]
    },
    "web_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索查询"},
            "backend": {"type": "string", "default": "tavily", "description": "搜索后端"},
        },
        "required": ["query"]
    },
    # GIS Planning Integration Tools
    "isochrone_analysis": {
        "type": "object",
        "properties": {
            "center": {"type": "array", "items": {"type": "number"}, "description": "中心点坐标 [lon, lat]"},
            "time_minutes": {"type": "array", "items": {"type": "integer"}, "description": "等时圈时间(分钟)"},
            "travel_mode": {"type": "string", "enum": ["walk", "drive", "bike"], "description": "出行方式"},
        },
        "required": ["center"]
    },
    "planning_vectorizer": {
        "type": "object",
        "properties": {
            "zones": {"type": "array", "description": "功能区列表"},
            "facilities": {"type": "array", "description": "设施点列表"},
            "village_center": {"type": "array", "items": {"type": "number"}, "description": "村庄中心坐标"},
        },
        "required": ["zones"]
    },
    "facility_validator": {
        "type": "object",
        "properties": {
            "facility_type": {"type": "string", "description": "设施类型"},
            "location": {"type": "array", "items": {"type": "number"}, "description": "设施位置 [lon, lat]"},
            "analysis_params": {"type": "object", "description": "分析参数"},
        },
        "required": ["facility_type", "location"]
    },
    "ecological_sensitivity": {
        "type": "object",
        "properties": {
            "study_area": {"type": "object", "description": "研究区域 (GeoJSON)"},
            "water_features": {"type": "object", "description": "水系要素 (GeoJSON)"},
        },
        "required": ["study_area"]
    },
}

# 工具元数据定义
TOOL_METADATA_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "gis_analysis": {
        "display_name": "GIS 空间分析",
        "description": "执行空间分析，如土地利用分析、土壤分析、水文分析等。",
        "estimated_time": 8.0,
        "display_hints": {"primary_view": "map", "priority_fields": ["total_area", "land_use_types"]}
    },
    "network_analysis": {
        "display_name": "网络分析",
        "description": "分析交通网络特性，计算道路密度、连通度等指标。",
        "estimated_time": 5.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["network_density", "connectivity_index"]}
    },
    "population_prediction": {
        "display_name": "人口预测",
        "description": "基于人口模型预测未来人口变化趋势，支持村庄规划标准模型。",
        "estimated_time": 3.0,
        "display_hints": {"primary_view": "chart", "priority_fields": ["forecast_population", "growth_rate"]}
    },
    "accessibility_analysis": {
        "display_name": "可达性分析",
        "description": "分析设施可达性，计算服务覆盖范围和出行时间。",
        "estimated_time": 6.0,
        "display_hints": {"primary_view": "table", "priority_fields": ["coverage_rate", "accessibility_matrix"]}
    },
    "knowledge_search": {
        "display_name": "知识检索",
        "description": "从知识库检索专业数据和法规条文。",
        "estimated_time": 2.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["content", "source"]}
    },
    "web_search": {
        "display_name": "网络搜索",
        "description": "从互联网搜索实时信息。",
        "estimated_time": 4.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["results"]}
    },
    # GIS Planning Integration Tools
    "isochrone_analysis": {
        "display_name": "等时圈分析",
        "description": "生成基于时间可达性的等时圈，分析服务覆盖范围。",
        "estimated_time": 8.0,
        "display_hints": {"primary_view": "map", "priority_fields": ["isochrones", "coverage_rate"]}
    },
    "planning_vectorizer": {
        "display_name": "规划矢量化",
        "description": "将规划方案转换为GIS矢量数据，创建功能区和设施点。",
        "estimated_time": 4.0,
        "display_hints": {"primary_view": "map", "priority_fields": ["geojson", "feature_count"]}
    },
    "facility_validator": {
        "display_name": "设施选址验证",
        "description": "验证设施选址合理性，评估服务覆盖、人口可达性。",
        "estimated_time": 6.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["overall_score", "suitability_level"]}
    },
    "ecological_sensitivity": {
        "display_name": "生态敏感性评估",
        "description": "评估区域生态敏感性，识别生态保护区域。",
        "estimated_time": 7.0,
        "display_hints": {"primary_view": "map", "priority_fields": ["sensitivity_class", "sensitive_area_km2"]}
    },
}


class ToolRegistry:
    """
    简化的工具注册中心

    使用装饰器注册工具函数，支持 LangChain 原生 @tool 装饰器。
    """

    _tools: Dict[str, Callable] = {}
    _tool_metadata: Dict[str, ToolMetadata] = {}

    @classmethod
    def register(cls, name: str):
        """
        装饰器：注册工具函数

        Usage:
            @ToolRegistry.register("my_tool")
            def my_tool(context: dict) -> str:
                ...
        """
        def decorator(func: Callable) -> Callable:
            cls._tools[name] = func
            logger.info(f"[ToolRegistry] 工具已注册: {name}")
            return func
        return decorator

    @classmethod
    def get_tool(cls, name: str) -> Optional[Callable]:
        """获取工具函数"""
        return cls._tools.get(name)

    @classmethod
    def list_tools(cls) -> Dict[str, str]:
        """列出所有已注册工具"""
        return {name: func.__name__ for name, func in cls._tools.items()}

    @classmethod
    def execute_tool(cls, name: str, context: Dict[str, Any]) -> str:
        """
        执行工具并返回结果

        Args:
            name: 工具名称
            context: 上下文数据

        Returns:
            工具输出字符串
        """
        tool_func = cls.get_tool(name)
        if not tool_func:
            raise ValueError(f"工具不存在: {name}")

        try:
            result = tool_func(context)
            logger.info(f"[ToolRegistry] 工具执行成功: {name}")
            return result
        except Exception as e:
            logger.error(f"[ToolRegistry] 工具执行失败: {name}, 错误: {e}")
            raise

    @classmethod
    def get_tool_metadata(cls, name: str) -> Optional[ToolMetadata]:
        """获取工具元数据"""
        return cls._tool_metadata.get(name)

    @classmethod
    def get_all_metadata(cls) -> Dict[str, ToolMetadata]:
        """获取所有工具元数据"""
        return cls._tool_metadata.copy()

    @classmethod
    def get_tools_for_context(cls, context: Dict[str, Any]) -> List[ToolMetadata]:
        """根据上下文获取可用工具列表"""
        return list(cls._tool_metadata.values())

    @classmethod
    def get_tool_info(cls, tool_name: str) -> Dict[str, Any]:
        """
        获取工具完整信息（单次查找）

        Args:
            tool_name: 工具名称

        Returns:
            包含 display_name, description, estimated_time 的字典
        """
        meta_def = TOOL_METADATA_DEFINITIONS.get(tool_name, {})
        return {
            "display_name": meta_def.get("display_name", tool_name),
            "description": meta_def.get("description", ""),
            "estimated_time": meta_def.get("estimated_time")
        }

    @classmethod
    def get_display_name(cls, tool_name: str) -> str:
        """获取工具显示名称"""
        return cls.get_tool_info(tool_name)["display_name"]

    @classmethod
    def get_description(cls, tool_name: str) -> str:
        """获取工具描述"""
        return cls.get_tool_info(tool_name)["description"]

    @classmethod
    def get_estimated_time(cls, tool_name: str) -> Optional[float]:
        """获取工具预估执行时间"""
        return cls.get_tool_info(tool_name)["estimated_time"]


# from builtin module
from .builtin import knowledge_search_tool, web_search_tool
from .builtin.population import calculate_population

# Register built-in tools
ToolRegistry._tools["knowledge_search"] = knowledge_search_tool
ToolRegistry._tools["web_search"] = web_search_tool
ToolRegistry._tools["population_model_v1"] = calculate_population

# Register GIS tools
from .core.gis_tool_wrappers import GIS_TOOL_WRAPPERS
for tool_name, wrapper_func in GIS_TOOL_WRAPPERS.items():
    ToolRegistry._tools[tool_name] = wrapper_func
    logger.info(f"[ToolRegistry] GIS tool registered: {tool_name}")

# Register metadata
for name, meta_def in TOOL_METADATA_DEFINITIONS.items():
    ToolRegistry._tool_metadata[name] = ToolMetadata(
        name=name,
        description=meta_def.get("description", ""),
        display_name=meta_def.get("display_name", name),
        parameters=TOOL_PARAMETER_SCHEMAS.get(name),
        display_hints=meta_def.get("display_hints")
    )


__all__ = [
    "ToolRegistry",
    "ToolMetadata",
    "TOOL_PARAMETER_SCHEMAS",
    "TOOL_METADATA_DEFINITIONS",
]