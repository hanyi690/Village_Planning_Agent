# 工具系统文档

> **相关文档**: [系统架构总览](architecture.md) | [智能体架构](agent.md)
>
> 本文档详细说明 Village_Planning_Agent 的工具系统架构、现有实现、扩展方式和注入流程。

---

## 一、架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ToolRegistry (工具注册中心)                         │
│                          src/tools/registry.py                               │
│                                                                              │
│   @ToolRegistry.register("tool_name")                                        │
│   def tool_function(context: Dict[str, Any]) -> str                         │
│                                                                              │
│   ToolMetadata - LLM bind_tools Schema 生成                                  │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│   内置工具           │   │   业务工具          │   │   RAG 工具          │
│   registry.py       │   │   src/tools/        │   │   rag/core/tools.py │
├─────────────────────┤   ├─────────────────────┤   ├─────────────────────┤
│ - population_model  │   │ - revision_tool     │   │ - knowledge_search  │
│ - gis_coverage      │   │ - web_review_tool   │   │ - document_overview │
│ - network_access    │   │ - file_manager      │   │ - chapter_content   │
│ - geocoding         │   │ - project_extractor │   │ - check_technical   │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      LLM bind_tools (conversation_node)                      │
│                                                                              │
│   tools = ToolRegistry.get_all_tool_schemas()                               │
│   llm_with_tools = llm.bind_tools(tools)                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、工具注册中心

### 2.1 ToolMetadata 类

**文件**: `src/tools/registry.py`

```python
@dataclass
class ToolMetadata:
    """工具元数据（用于 LLM bind_tools）"""

    name: str                           # 工具名称
    description: str                    # 工具描述
    input_schema: Optional[Type[BaseModel]] = None  # Pydantic 输入模型
    display_name: Optional[str] = None  # 显示名称
    parameters: Optional[Dict[str, Any]] = None     # JSON Schema 参数
    display_hints: Optional[Dict[str, Any]] = None  # 显示提示

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or self.input_schema.model_json_schema()
            }
        }
```

### 2.2 工具参数 Schema

```python
TOOL_PARAMETER_SCHEMAS = {
    "gis_analysis": {
        "type": "object",
        "properties": {
            "analysis_type": {
                "type": "string",
                "enum": ["land_use_analysis", "soil_analysis", "hydrology_analysis"]
            },
            "geo_data_path": {"type": "string", "description": "数据文件路径"}
        },
        "required": ["analysis_type"]
    },
    "population_prediction": {
        "type": "object",
        "properties": {
            "analysis_type": {
                "type": "string",
                "enum": ["population_forecast", "village_forecast", "population_structure"]
            },
            "baseline_population": {"type": "integer"},
            "baseline_year": {"type": "integer"}
        },
        "required": ["baseline_population", "baseline_year"]
    },
    "accessibility_analysis": {
        "type": "object",
        "properties": {
            "analysis_type": {
                "type": "string",
                "enum": ["driving_accessibility", "walking_accessibility", "service_coverage"]
            },
            "origin": {"type": "array", "items": {"type": "number"}}
        },
        "required": ["analysis_type"]
    }
}
```

### 2.3 注册装饰器

```python
class ToolRegistry:
    """工具注册中心"""

    _tools: Dict[str, Callable] = {}
    _metadata: Dict[str, ToolMetadata] = {}

    @classmethod
    def register(cls, name: str, description: str = "", **metadata_kwargs):
        """装饰器：注册工具"""
        def decorator(func: Callable) -> Callable:
            cls._tools[name] = func
            cls._metadata[name] = ToolMetadata(
                name=name,
                description=description or func.__doc__ or "",
                **metadata_kwargs
            )
            return func
        return decorator

    @classmethod
    def execute_tool(cls, name: str, context: Dict[str, Any]) -> str:
        """执行工具"""
        if name not in cls._tools:
            return f"工具 {name} 未注册"
        return cls._tools[name](context)

    @classmethod
    def get_all_tool_schemas(cls) -> List[Dict[str, Any]]:
        """获取所有工具的 OpenAI Schema"""
        return [m.to_openai_tool_schema() for m in cls._metadata.values()]
```

---

## 三、现有工具实现

### 3.1 工具分类

| 类别 | 文件位置 | 实现状态 | 说明 |
|------|---------|---------|------|
| **内置工具** | `src/tools/registry.py` | ⚠️ 部分完成 | 人口预测已完成，GIS/网络为模拟数据 |
| **业务工具** | `src/tools/` | ✅ 完成 | 修复、文件管理、项目提取等 |
| **RAG 工具** | `src/rag/core/tools.py` | ✅ 完成 | 知识检索工具集 |
| **地理编码** | `src/tools/geocoding/` | ✅ 完成 | 天地图 API 封装 |

### 3.2 内置工具详解

#### 3.2.1 population_model_v1 ✅ 已实现

```python
@ToolRegistry.register("population_model_v1")
def calculate_population(context: Dict[str, Any]) -> str
```

**预测模型**: `Pn = P0 × (1 + K)^n + M`

**输出格式**:
```text
## 人口预测结果

**预测模型**: Pn = P0 × (1 + K)^n + M（村庄规划标准模型）

**基础参数**:
- 基期年份: 2024年
- 基期人口: 1406人
- 自然增长率: 4‰
- 机械增长人口: 200人

**预测结果**:
- **2035年预测人口: 1681人**
```

**关联维度**: `socio_economic` (Layer 1)

---

#### 3.2.2 gis_coverage_calculator ⚠️ 模拟数据

**日志输出**: `WARNING: GIS 模块不可用，返回估算模拟数据`

**关联维度**: `land_use` (Layer 1)

---

#### 3.2.3 network_accessibility ⚠️ 定性分析

**日志输出**: `WARNING: 网络分析模块不可用，返回定性分析`

**关联维度**: `traffic` (Layer 1)

---

### 3.3 业务工具

| 工具 | 文件 | 功能 |
|------|------|------|
| `VillageDataManager` | `file_manager.py` | 文件和数据处理入口 |
| `RevisionTool` | `revision_tool.py` | 基于反馈的规划修复 |
| `WebReviewTool` | `web_review_tool.py` | Web 环境审查工具 |
| `ProjectExtractor` | `project_extractor.py` | 项目提取（正则+LLM混合） |

---

### 3.4 RAG 知识检索工具集

**文件**: `src/rag/core/tools.py`

| 工具名称 | 功能 | 状态 |
|---------|------|------|
| `list_available_documents` | 列出知识库文档 | ✅ |
| `document_overview_tool` | 获取文档概览 | ✅ |
| `chapter_content_tool` | 获取章节内容 | ✅ |
| `knowledge_search_tool` | 知识检索 | ✅ |
| `key_points_search_tool` | 搜索关键要点 | ✅ |
| `check_technical_indicators` | 技术指标检索（支持元数据过滤） | ✅ |

**元数据过滤功能**:

```python
result = check_technical_indicators.invoke({
    "query": "道路宽度标准",
    "dimension": "traffic",
    "terrain": "mountain",
    "doc_type": "standard"
})
```

---

### 3.5 地理编码工具

**目录**: `src/tools/geocoding/`

| 文件 | 功能 |
|------|------|
| `tianditu_provider.py` | 天地图 API 封装 |
| `base_provider.py` | 地理编码基类 |
| `models.py` | 数据模型 |

**主要功能**:
- 地址解析（地址 → 坐标）
- 逆地址解析（坐标 → 地址）
- POI 搜索

---

## 四、维度与工具的关联配置

### 4.1 配置位置

**文件**: `src/config/dimension_metadata.py`

### 4.2 已配置的工具

| 维度 | 工具 | 说明 |
|------|------|------|
| `socio_economic` | `population_model_v1` | 人口预测 |
| `land_use` | `gis_coverage_calculator` | GIS 覆盖率计算 |
| `traffic` | `network_accessibility` | 网络可达性分析 |

### 4.3 预留但未配置的维度

| 维度 | 建议工具 |
|------|---------|
| `natural_environment` | `gis_analysis` |
| `public_services` | `service_coverage` |
| `infrastructure` | `infrastructure_capacity` |
| `ecological` | `ecological_assessment` |
| `disaster_prevention` | `risk_assessment` |

---

## 五、工具扩展指南

### 5.1 添加新工具

```python
from src.tools.registry import ToolRegistry

@ToolRegistry.register(
    "my_custom_tool",
    description="自定义工具描述",
    parameters={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "参数1"}
        },
        "required": ["param1"]
    }
)
def my_custom_tool(context: Dict[str, Any]) -> str:
    """
    自定义工具实现

    Args:
        context: 上下文字典，包含 raw_data, analysis_reports 等

    Returns:
        格式化的输出字符串（Markdown 格式）
    """
    param1 = context.get("param1", "")
    result = process(param1)

    return f"""## 工具输出

**结果**: {result}
"""
```

### 5.2 关联到维度

编辑 `src/config/dimension_metadata.py`:

```python
"my_dimension": {
    "key": "my_dimension",
    "name": "维度名称",
    "layer": 3,
    "tool": "my_custom_tool",  # 添加此行
    ...
}
```

---

## 六、工具上下文数据

`_prepare_tool_context()` 为工具准备的上下文：

```python
{
    # 基础数据（所有层级可用）
    "raw_data": "...",           # 原始村庄数据
    "project_name": "村庄名称",

    # Layer 2/3 可用
    "analysis_report": "...",    # 合并的现状分析
    "analysis_reports": {...},   # 各维度分析报告字典

    # Layer 3 可用
    "planning_concept": "...",   # 规划思路
    "concept_reports": {...},    # 各维度规划思路字典
    "completed_plans": {...}     # 已完成的详细规划
}
```

---

## 七、目录结构

```
src/tools/
├── __init__.py                 # 工具模块导出
├── registry.py                 # 工具注册中心（ToolRegistry + ToolMetadata）
├── file_manager.py             # 文件管理器
├── knowledge_tool.py           # 知识检索工具接口
├── revision_tool.py            # 修复工具
├── web_review_tool.py          # Web 审查工具
├── project_extractor.py        # 项目提取工具
├── search_tool.py              # 搜索工具
├── builtin/                    # 内置工具
│   └── ...
├── core/                       # 核心工具
│   └── ...
├── geocoding/                  # 地理编码模块
│   ├── tianditu_provider.py    # 天地图 API
│   ├── base_provider.py        # 基类
│   └── models.py               # 数据模型
└── adapters/                   # 适配器（可选扩展）
    ├── base_adapter.py         # Adapter 基类
    ├── gis_adapter.py          # GIS 分析适配器
    ├── network_adapter.py      # 网络分析适配器
    └── population_adapter.py   # 人口预测适配器
```

---

## 八、关键文件索引

| 文件路径 | 功能描述 |
|---------|---------|
| `src/tools/registry.py` | 工具注册中心（ToolRegistry + ToolMetadata） |
| `src/tools/file_manager.py` | 文件管理器（VillageDataManager） |
| `src/tools/revision_tool.py` | 修复工具（维度识别、批量修复） |
| `src/tools/web_review_tool.py` | Web 审查工具 |
| `src/tools/project_extractor.py` | 项目提取工具 |
| `src/tools/geocoding/tianditu_provider.py` | 天地图地理编码 |
| `src/tools/adapters/population_adapter.py` | 人口预测适配器 |
| `src/config/dimension_metadata.py` | 维度配置（含 tool 字段） |
| `src/rag/core/tools.py` | RAG 知识检索工具集 |