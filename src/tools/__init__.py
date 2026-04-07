"""
工具模块 - 统一工具层

提供所有工具的统一导出。

检查点管理：统一使用 LangGraph AsyncSqliteSaver（通过 backend.api.planning 模块）
"""

# 工具注册中心
from .registry import ToolRegistry, ToolMetadata, TOOL_PARAMETER_SCHEMAS, TOOL_METADATA_DEFINITIONS

# 工具返回值类型定义
from .types import (
    ResultDataType,
    NormalizedToolResult,
    normalize_tool_result,
    safe_get_nested,
)

# 统一工具定义（LangChain @tool 装饰器）
from .tools import (
    gis_analysis,
    network_analysis,
    population_prediction,
    accessibility_analysis,
    knowledge_search,
    web_search,
    ALL_TOOLS,
    get_tools_for_llm,
)

# 核心分析逻辑
from .core import (
    run_gis_analysis,
    format_gis_result,
    run_network_analysis,
    format_network_result,
    run_population_analysis,
    format_population_result,
    run_accessibility_analysis,
    format_accessibility_result,
)

# 文件管理工具
from .file_manager import (
    VillageDataManager,
    read_village_data,
    load_data_with_metadata
)

# 知识库工具（函数）
from .knowledge_tool import knowledge_query

# 修复工具
from .revision_tool import (
    RevisionTool,
    parse_feedback,
    revise_dimension,
    revise_dimensions
)

__all__ = [
    # 工具注册中心
    "ToolRegistry",
    "ToolMetadata",
    "TOOL_PARAMETER_SCHEMAS",
    "TOOL_METADATA_DEFINITIONS",

    # 工具返回值类型定义
    "ResultDataType",
    "NormalizedToolResult",
    "normalize_tool_result",
    "safe_get_nested",

    # 统一工具定义
    "gis_analysis",
    "network_analysis",
    "population_prediction",
    "accessibility_analysis",
    "knowledge_search",
    "web_search",
    "ALL_TOOLS",
    "get_tools_for_llm",

    # 核心分析逻辑
    "run_gis_analysis",
    "format_gis_result",
    "run_network_analysis",
    "format_network_result",
    "run_population_analysis",
    "format_population_result",
    "run_accessibility_analysis",
    "format_accessibility_result",

    # 文件管理
    "VillageDataManager",
    "read_village_data",
    "load_data_with_metadata",

    # 知识库
    "knowledge_query",

    # 修复
    "RevisionTool",
    "parse_feedback",
    "revise_dimension",
    "revise_dimensions",
]