# 工具系统架构

本文档详细说明 ToolRegistry 注册机制、已注册工具、参数 Schema 以及工具在维度分析中的执行流程。

> **更新日期**: 2026-05-09
> **版本**: v3.0

## 目录

- [ToolRegistry 注册机制](#toolregistry注册机制)
- [已注册工具](#已注册工具)
- [工具参数 Schema](#工具参数-schema)
- [工具元数据定义](#工具元数据定义)
- [维度分析中的工具执行](#维度分析中的工具执行)
- [文件结构](#文件结构)

---

## ToolRegistry 注册机制

```python
# backend/app/tools/registry.py

@dataclass
class ToolMetadata:
    name: str                    # 工具内部名称
    description: str             # 工具描述（供 LLM 理解）
    input_schema: Optional[Type] # Pydantic 输入 Schema
    display_name: Optional[str]  # 前端展示名
    parameters: Optional[Dict]   # JSON Schema 参数字典
    display_hints: Optional[Dict]# 前端展示提示

    def to_openai_tool_schema(self) -> Dict:
        """转换为 OpenAI function calling 格式"""
```

### 两种注册方式

```python
# 方式1: 装饰器注册
@ToolRegistry.register("my_tool")
def my_tool(context: Dict[str, Any]) -> str:
    ...

# 方式2: 直接注册（批量导入）
from .analytics import knowledge_search_tool
ToolRegistry._tools["knowledge_search"] = knowledge_search_tool
```

### ToolRegistry 核心 API

| 方法 | 说明 |
|------|------|
| `register(name)` | 装饰器：注册工具函数 |
| `get_tool(name)` | 获取工具函数 |
| `execute_tool(name, context)` | 执行工具并返回结果 |
| `list_tools()` | 列出所有已注册工具 |
| `get_tool_info(name)` | 获取 display_name + description + estimated_time |
| `get_all_metadata()` | 获取所有工具元数据 |
| `get_tools_for_context(ctx)` | 返回上下文可用工具列表 |

---

## 已注册工具

### 知识检索类工具

| 工具名 | 函数 | 功能 | 预估耗时 |
|--------|------|------|----------|
| `knowledge_search` | `knowledge_search_registry_wrapper` | 知识库向量检索，支持 context_mode 和元数据过滤 | 2.0s |
| `document_overview` | `document_overview_registry_wrapper` | 文档概览（执行摘要+章节列表） | 2.0s |
| `chapter_content` | `chapter_content_registry_wrapper` | 章节内容获取（summary/medium/full 三级详情） | 2.0s |

### 分析类工具

| 工具名 | 函数 | 功能 | 预估耗时 |
|--------|------|------|----------|
| `population_model_v1` | `calculate_population` | 人口预测（省级增长率/自回归/综合加权三种算法） | 3.0s |
| `web_search` | `web_search_tool` | 互联网实时搜索 | 4.0s |

### 工具函数详解

**knowledge_search**:

- 输入：`query`（必需）、`top_k`（默认 5）、`context_mode`（默认 "standard"）
- 上下文模式：minimal（仅片段）、standard（+300字上下文）、expanded（+500字上下文）
- 支持 ChromaDB 元数据过滤：terrain、doc_type、task_id
- 内部使用 `RagService.get_instance().vectorstore` 获取向量存储

**document_overview**:

- 输入：`source`（必需）、`include_chapters`（默认 True）
- 输出：200 字执行摘要 + 可选章节标题列表
- 数据来源：DocumentContextManager

**chapter_content**:

- 输入：`source`、`chapter_pattern`（必需）、`detail_level`（默认 "medium"）
- 三级详情：summary（摘要）、medium（摘要+关键要点）、full（完整内容）
- 数据来源：DocumentContextManager

**population_model_v1**:

- 输入：`baseline_population`、`baseline_year`（必需）
- 支持三种预测算法：省级增长率模型、自回归模型、综合加权模型
- 输出：预测人口数、增长率、置信区间

### GIS 工具

GIS 工具已迁移至 `backend/app/services/modules/gis/`，当前 `GIS_TOOL_WRAPPERS = {}`（占位），
可通过 wrapper 机制按需注册。GIS 分析通过 `GisService.run_parallel()` 直接执行，
不经过 ToolRegistry。

---

## 工具参数 Schema

所有工具的输入参数通过 `TOOL_PARAMETER_SCHEMAS` 定义（JSON Schema 格式），
用于生成 OpenAI function calling 的 `parameters` 字段。

```python
# backend/app/tools/registry.py → TOOL_PARAMETER_SCHEMAS
```

### knowledge_search 参数

```json
{
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "搜索查询"},
        "top_k": {"type": "integer", "default": 5}
    },
    "required": ["query"]
}
```

### population_prediction 参数

```json
{
    "type": "object",
    "properties": {
        "baseline_population": {"type": "integer"},
        "baseline_year": {"type": "integer"}
    },
    "required": ["baseline_population", "baseline_year"]
}
```

### 空间分析类（预留 Schema）

`TOOL_PARAMETER_SCHEMAS` 中还预定义了以下工具的 JSON Schema，对应的实现尚未完成：

| 工具名 | Schema 描述 |
|--------|------------|
| `spatial_overlay` | 空间叠加（intersect/union/difference/clip） |
| `spatial_query` | 空间查询（contains/intersects/within/nearest） |
| `isochrone_analysis` | 等时圈生成 |
| `planning_vectorizer` | 规划方案矢量化 |
| `facility_validator` | 设施选址验证 |
| `ecological_sensitivity` | 生态敏感性评估 |
| `landuse_change_analysis` | 用地变化分析 |
| `constraint_validator` | 保护约束验证 |
| `hazard_buffer_generator` | 灾害缓冲区生成 |
| `boundary_fallback` | 边界兜底生成 |
| `spatial_layout_generator` | 空间布局生成 |

---

## 工具元数据定义

每个工具在 `TOOL_METADATA_DEFINITIONS` 中有对应的展示配置：

```python
# backend/app/tools/registry.py → TOOL_METADATA_DEFINITIONS
{
    "knowledge_search": {
        "display_name": "知识检索",
        "description": "从知识库检索专业数据和法规条文。",
        "estimated_time": 2.0,
        "display_hints": {
            "primary_view": "text",
            "priority_fields": ["content", "source"]
        }
    },
    "population_prediction": {
        "display_name": "人口预测",
        "description": "基于人口模型预测未来人口变化趋势。",
        "estimated_time": 3.0,
        "display_hints": {
            "primary_view": "chart",
            "priority_fields": ["forecast_population", "growth_rate"]
        }
    }
}
```

`display_hints` 用于前端渲染：

- `primary_view`：默认展示视图类型（text / map / chart / table）
- `priority_fields`：优先展示的字段列表

---

## 维度分析中的工具执行

### analyze_dimension 中的调用路径

```python
# backend/app/agent/nodes/analysis.py → analyze_dimension()

# 步骤 2: 并行 GIS 工具
tools = getattr(cfg, 'tools', [])        # 从维度配置读取工具列表
context = {
    "session_id": session_id,
    "project_name": state.get("project_name", ""),
    "village_data": state.get("config", {}).get("village_data", ""),
    "reports": state.get("reports", {}),
}
tool_results = await GisService.run_parallel(tools, context)

# 步骤 3: RAG 查询（自动检索，不走 ToolRegistry）
rag_context = await RagService.get_instance().get_context(dim_key, state, cfg)

# 步骤 4: 组装 Prompt
prompt = _build_prompt(cfg, state, tool_results, rag_context)
```

### 工具执行流程

```
维度配置 (cfg.tools) → 工具列表
    │
    ├─ GIS 工具 → GisService.run_parallel(tools, context)
    │             并行执行所有 GIS 分析工具
    │             返回 ToolResult 列表 (含 success, data, tool_name)
    │
    ├─ RAG 检索 → RagService.get_context(dim_key, state, cfg)
    │             LLM 生成查询 → ChromaDB 搜索 → 格式化
    │             返回知识上下文字符串
    │
    └─ 结果注入 → _build_prompt()
                  GIS 结果 + RAG 上下文 → LLM Prompt
```

### Agent Tool Calling（LangChain）

Agent 在推理过程中可通过 function calling 自行调用 ToolRegistry 中的工具：

```python
# Agent 自主决定调用时机，例如：
# → knowledge_search("道路宽度标准", top_k=5, context_mode="expanded")
# → document_overview("GB50188-2007.doc", include_chapters=True)
# → chapter_content("村庄规划指南.pdf", "第三章", detail_level="full")
```

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `backend/app/tools/registry.py` | ToolRegistry 类、ToolMetadata、参数 Schema、元数据定义 |
| `backend/app/tools/analytics/knowledge_search.py` | 知识检索工具函数（7 个工具 + ToolRegistry 包装器） |
| `backend/app/tools/analytics/population.py` | 人口预测模型实现 |
| `backend/app/agent/nodes/analysis.py` | 维度分析节点（调用 GIS 工具 + RAG） |
| `backend/app/services/modules/gis/service.py` | GIS 工具并行执行（GisService.run_parallel） |
| `backend/app/services/modules/rag/service.py` | RAG 检索服务（RagService.get_context） |

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - analyze_dimension 节点
- [03-layer-dimension](./03-layer-dimension.md) - 维度工具绑定
- [08-rag-system](./08-rag-system.md) - RAG 知识检索详解
