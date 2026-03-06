# 工具系统文档

本文档详细说明 Village_Planning_Agent 的工具系统架构、现有实现、扩展方式和注入流程。

---

## 一、架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ToolRegistry (工具注册中心)                         │
│                          src/tools/registry.py                               │
│                                                                              │
│   @ToolRegistry.register("tool_name")                                        │
│   def tool_function(context: Dict[str, Any]) -> str                         │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│   内置工具           │   │   Adapter 工具       │   │   RAG 工具          │
│   registry.py       │   │   adapters/         │   │   rag/core/tools.py │
├─────────────────────┤   ├─────────────────────┤   ├─────────────────────┤
│ - population_model  │   │ - GISAnalysisAdapter│   │ - knowledge_search  │
│ - gis_coverage      │   │ - NetworkAdapter    │   │ - document_overview │
│ - network_access    │   │ - PopulationAdapter │   │ - chapter_content   │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘
         │                           │                           │
         └───────────────────────────┼───────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        GenericPlanner._execute_tool_hook()                  │
│                        src/planners/generic_planner.py                      │
│                                                                              │
│   1. 从 dimension_metadata.py 读取 tool 配置                                 │
│   2. 调用 ToolRegistry.execute_tool(tool_name, context)                     │
│   3. 将工具输出注入到 Prompt                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、现有工具实现

### 2.1 工具分类

| 类别 | 文件位置 | 实现状态 | 说明 |
|------|---------|---------|------|
| **内置工具** | `src/tools/registry.py` | ⚠️ 部分完成 | 人口预测已完成，GIS/网络为模拟数据 |
| **Adapter 工具** | `src/tools/adapters/` | ⚠️ 代码完整但缺数据 | 人口预测已完成，GIS/网络需要外部数据 |
| **RAG 工具** | `src/rag/core/tools.py` | ✅ 完成 | 知识检索工具集 |
| **业务工具** | `src/tools/` | ⚠️ 部分完成 | 规划、修复、文件管理等 |

---

### 2.2 内置工具（registry.py）

> ⚠️ **重要说明**: 下述内置工具的 GIS 和网络分析当前为**模拟数据**，日志中会以 `WARNING` 级别标注。人口预测工具已实现**村庄规划标准模型**。

#### 2.2.1 population_model_v1 ✅ 已实现标准模型

```python
@ToolRegistry.register("population_model_v1")
def calculate_population(context: Dict[str, Any]) -> str
```

**功能**: 人口预测模型

**预测模型**: `Pn = P0 × (1 + K)^n + M`

其中：
- Pn: 规划期末人口数
- P0: 规划基期年人口总数
- K: 规划期内人口自然增长率（‰，千分比）
- n: 预测年限
- M: 机械增长人口（迁入-迁出）

**输入参数**:
| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `socio_economic` | str | 可选 | - | 社会经济分析文本（提取人口） |
| `baseline_population` | int | 可选 | 自动提取 | 基期人口 |
| `baseline_year` | int | 可选 | 当前年份 | 基期年份 |
| `target_year` | int | 可选 | 2035 | 目标年份 |
| `natural_growth_rate` | float | 可选 | 4.0 | 自然增长率（‰） |
| `mechanical_growth` | int | 可选 | 0 | 机械增长人口 |

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
- 预测年限: 11年
- 自然增长系数: 1.045
- **2035年预测人口: 1681人**
- 2030年预测人口: 1481人

**计算过程**:
Pn = 1406 × (1 + 0.004)^11 + 200
   = 1406 × 1.045 + 200
   = 1681人
```

**关联维度**: `socio_economic` (Layer 1)

**实现文件**: 
- `src/tools/registry.py` - 工具入口
- `src/tools/adapters/population_adapter.py` - 核心算法（`village_forecast` 方法）

---

#### 2.2.2 gis_coverage_calculator ⚠️ 模拟数据

```python
@ToolRegistry.register("gis_coverage_calculator")
def calculate_gis_coverage(context: Dict[str, Any]) -> str
```

**功能**: GIS 土地利用分析

**实际实现**:
- 尝试调用 `GISAnalysisAdapter`
- 但 adapter 需要 `geo_data_path` 参数，当前调用未传递
- **实际返回固定的模拟数据**

**日志输出**: `WARNING: [gis_coverage_calculator] GIS 模块不可用，返回估算模拟数据`

**输入参数**:
- `village_data`: 村庄基础数据（但未使用）

**输出格式**（模拟数据）:
```text
## GIS 土地利用分析结果

基于现状调研数据估算：
- 建设用地：15%
- 耕地：60%
- 林地：15%
- 水域：5%
- 其他用地：5%

**注意**：GIS 模块未安装，以上为估算数据
```

**关联维度**: `land_use` (Layer 1)

---

#### 2.2.3 network_accessibility ⚠️ 定性分析（模拟）

```python
@ToolRegistry.register("network_accessibility")
def calculate_network_accessibility(context: Dict[str, Any]) -> str
```

**功能**: 交通网络可达性分析

**实际实现**:
- 尝试调用 `NetworkAnalysisAdapter`
- 但 adapter 需要 `network_data`（节点和边），当前调用未传递
- **实际返回固定的定性分析文本**

**日志输出**: `WARNING: [network_accessibility] 网络分析模块不可用，返回定性分析（模拟数据）`

**输入参数**:
- `traffic`: 道路交通分析数据（但未使用）

**输出格式**（定性分析）:
```text
## 交通可达性分析结果

基于现状路网结构分析：
- 对外交通可达性：良好
- 内部道路连通度：中等
- 公共交通覆盖：需提升

**注意**：网络分析模块未安装，以上为定性分析
```

**关联维度**: `traffic` (Layer 1)

---

#### 2.2.4 knowledge_search ✅ 完成

```python
@ToolRegistry.register("knowledge_search")
def knowledge_search_tool(context: Dict[str, Any]) -> str
```

**功能**: RAG 知识检索

**输入参数**:
- `query`: 查询字符串（必需）
- `top_k`: 返回结果数量（可选，默认 5）
- `context_mode`: 上下文模式（可选，默认 "standard"）

**输出格式**: 检索到的知识片段文本

**关联维度**: 所有启用 `rag_enabled: true` 的维度

---

### 2.3 Adapter 适配器工具

> ⚠️ **重要说明**: Adapter 有真实实现代码，但需要**特定数据参数**才能工作。当前 `registry.py` 调用时未传递这些参数，导致实际运行时降级到模拟数据。

#### 2.3.1 GISAnalysisAdapter ⚠️ 需要数据文件

**文件**: `src/tools/adapters/gis_adapter.py`

**功能**: GIS 空间分析

**真实实现要求**:
- `geo_data_path`: GIS 数据文件路径（如 `.shp`, `.geojson`）
- 依赖 `geopandas` 库

**当前问题**: `registry.py` 调用 `adapter.analyze_land_use(context)` 时，`context` 中没有 `geo_data_path`，所以总是失败降级。

**支持的分析类型**:
| 分析类型 | 方法 | 状态 |
|---------|------|------|
| `land_use_analysis` | 土地利用分析 | ✅ 代码完整，需数据 |
| `soil_analysis` | 土壤分析 | ⚠️ 需 `soil_data_path` |
| `hydrology_analysis` | 水文分析 | ⚠️ 需 `hydrology_data_path` |

---

#### 2.3.2 NetworkAnalysisAdapter ⚠️ 需要网络数据

**文件**: `src/tools/adapters/network_adapter.py`

**功能**: 交通网络分析

**真实实现要求**:
- `network_data`: 包含 `nodes` 和 `edges` 的网络结构数据
- 依赖 `networkx` 库

**当前问题**: `registry.py` 调用 `adapter.analyze_accessibility(context)` 时，`context` 中没有 `network_data`，所以总是失败降级。

**支持的分析类型**:
| 分析类型 | 方法 | 状态 |
|---------|------|------|
| `connectivity_metrics` | 连通度分析 | ✅ 代码完整，需数据 |
| `accessibility_analysis` | 可达性分析 | ✅ 代码完整，需数据 |
| `centrality_analysis` | 网络中心性分析 | ✅ 代码完整，需数据 |

---

#### 2.3.3 PopulationPredictionAdapter ✅ 完成

**文件**: `src/tools/adapters/population_adapter.py`

**功能**: 人口预测分析（使用内置算法，无外部依赖）

**支持的分析类型**:
| 分析类型 | 方法 | 状态 | 说明 |
|---------|------|------|------|
| `village_forecast` | 村庄规划标准模型 | ✅ 完成 | Pn=P0×(1+K)^n+M |
| `population_forecast` | 通用人口预测 | ✅ 完成 | 指数/线性/Logistic模型 |
| `population_structure` | 人口结构模型 | ✅ 完成 | 年龄结构、抚养比等 |
| `labor_force_analysis` | 劳动力供给分析 | ✅ 完成 | 劳动力规模、剩余等 |

**village_forecast 参数**:
```python
adapter.execute(
    analysis_type="village_forecast",
    baseline_population=1406,      # 基期人口
    baseline_year=2024,            # 基期年份
    target_year=2035,              # 目标年份
    natural_growth_rate=4.0,       # 自然增长率（‰）
    mechanical_growth=200,         # 机械增长人口
    intermediate_years=[2030]      # 中间年份
)
```

---

### 2.4 业务工具

#### 2.4.1 VillageDataManager ✅ 完成

**文件**: `src/tools/file_manager.py`

**功能**: 村庄数据管理器，统一文件和数据处理入口

**支持的文件格式**:
- `.txt`, `.md` - 文本文件
- `.pdf` - PDF 文档
- `.docx`, `.doc` - Word 文档
- `.pptx`, `.ppt` - PowerPoint 演示文稿

**主要方法**:
```python
class VillageDataManager:
    def load_data(source, source_type=None, validate=True) -> Dict[str, Any]
    def load_from_file(file_path) -> Dict[str, Any]
    def load_from_text(text) -> Dict[str, Any]
```

---

#### 2.4.2 RevisionTool ✅ 完成

**文件**: `src/tools/revision_tool.py`

**功能**: 基于反馈的规划修复工具

**主要方法**:
```python
class RevisionTool:
    def parse_feedback(feedback: str) -> Dict[str, Any]  # 解析人工反馈
    def revise_dimension(dimension_key: str, state: Dict) -> str  # 修复单个维度
    def revise_dimensions(dimensions: List[str], state: Dict) -> Dict  # 批量修复
```

**维度关键词映射**: 内置 28 个维度的关键词识别规则

---

#### 2.4.3 WebReviewTool ✅ 完成

**文件**: `src/tools/web_review_tool.py`

**功能**: Web 环境审查工具（非阻塞，基于事件）

**主要方法**:
```python
class WebReviewTool:
    def request_review(content, title, session_id) -> Dict  # 请求审查
    def submit_review_decision(review_id, action, feedback) -> Dict  # 提交审查决定
```

---

#### 2.4.4 planner_tool ⚠️ 简化实现

**文件**: `src/tools/planner_tool.py`

**功能**: 生成分阶段村庄规划大纲

**状态**: 当前为简化示例实现，仅输出固定的三阶段模板

**预留**: 可接入规则引擎或 GIS 服务

---

---

### 2.5 RAG 知识检索工具集

**文件**: `src/rag/core/tools.py`

| 工具名称 | 功能 | 状态 |
|---------|------|------|
| `list_available_documents` | 列出知识库文档 | ✅ 完成 |
| `document_overview_tool` | 获取文档概览 | ✅ 完成 |
| `chapter_content_tool` | 获取章节内容（三级详情） | ✅ 完成 |
| `knowledge_search_tool` | 知识检索（三种上下文模式） | ✅ 完成 |
| `key_points_search_tool` | 搜索关键要点 | ✅ 完成 |
| `full_document_tool` | 获取完整文档内容 | ✅ 完成 |
| `check_technical_indicators` | 检索技术指标 | ⚠️ 预留元数据过滤接口 |

---

## 三、维度与工具的关联配置

### 3.1 当前已配置的工具

在 `src/config/dimension_metadata.py` 中：

| 维度 | 工具 | 说明 |
|------|------|------|
| `socio_economic` | `population_model_v1` | 人口预测 |
| `land_use` | `gis_coverage_calculator` | GIS 覆盖率计算 |
| `traffic` | `network_accessibility` | 网络可达性分析 |

### 3.2 预留但未配置工具的维度

以下维度已预留 `tool` 字段，当前值为 `None`：

| 维度 | 建议工具 | 说明 |
|------|---------|------|
| `natural_environment` | `gis_analysis` | 水文/土壤分析 |
| `public_services` | `service_coverage` | 服务覆盖率分析（待开发） |
| `infrastructure` | `infrastructure_capacity` | 设施容量分析（待开发） |
| `ecological` | `ecological_assessment` | 生态评估工具（待开发） |
| `disaster_prevention` | `risk_assessment` | 风险评估工具（待开发） |

---

## 四、工具扩展与开发指南

### 4.1 添加新工具的完整流程

#### 步骤 1: 创建工具函数

在 `src/tools/registry.py` 或新建模块中定义：

```python
from typing import Dict, Any
from .registry import ToolRegistry

@ToolRegistry.register("my_custom_tool")
def my_custom_tool(context: Dict[str, Any]) -> str:
    """
    自定义工具描述
    
    Args:
        context: 上下文字典，包含：
            - raw_data: 原始村庄数据
            - analysis_reports: 现状分析报告
            - concept_reports: 规划思路报告
            - completed_plans: 已完成的详细规划
    
    Returns:
        格式化的输出字符串（Markdown 格式）
    """
    # 1. 从 context 提取所需数据
    village_data = context.get("raw_data", "")
    
    # 2. 执行计算逻辑
    result = process(village_data)
    
    # 3. 格式化输出
    return f"""## 工具输出标题

**分析结果**:
- 指标1: {result['metric1']}
- 指标2: {result['metric2']}

**建议**: ...
"""
```

#### 步骤 2: 在维度配置中关联

编辑 `src/config/dimension_metadata.py`：

```python
"my_dimension": {
    "key": "my_dimension",
    "name": "维度名称",
    "layer": 3,
    "dependencies": {...},
    "rag_enabled": True,
    "tool": "my_custom_tool",  # 添加此行
    ...
}
```

#### 步骤 3: 验证工具调用

工具会在 `GenericPlanner.build_prompt()` 中自动调用：

```python
# src/planners/generic_planner.py
def build_prompt(self, state: Dict[str, Any]) -> str:
    # ...
    tool_output = self._execute_tool_hook(state)  # 自动执行工具
    params["tool_output"] = tool_output
    # ...
```

---

### 4.2 创建 Adapter 适配器

#### 步骤 1: 创建适配器类

在 `src/tools/adapters/` 下创建新文件 `my_adapter.py`：

```python
from typing import Dict, Any, Optional
from .base_adapter import BaseAdapter, AdapterResult, AdapterStatus
from ...utils.logger import get_logger

logger = get_logger(__name__)


class MyAnalysisAdapter(BaseAdapter):
    """
    自定义分析适配器
    
    支持的分析类型：
    1. analysis_type_1 - 分析类型1
    2. analysis_type_2 - 分析类型2
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._external_lib_available = False
    
    def validate_dependencies(self) -> bool:
        """验证外部依赖"""
        try:
            import external_library
            self._external_lib_available = True
            return True
        except ImportError:
            logger.warning("[MyAdapter] external_library 不可用")
            return False
    
    def initialize(self) -> bool:
        """初始化适配器"""
        try:
            if self._external_lib_available:
                # 初始化外部库
                pass
            self._status = AdapterStatus.READY
            return True
        except Exception as e:
            self._error_message = str(e)
            return False
    
    def execute(self, analysis_type: str = "default", **kwargs) -> AdapterResult:
        """执行分析"""
        if not self._external_lib_available:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="需要安装 external_library"
            )
        
        if analysis_type == "analysis_type_1":
            return self._do_analysis_1(**kwargs)
        elif analysis_type == "analysis_type_2":
            return self._do_analysis_2(**kwargs)
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"不支持的分析类型: {analysis_type}"
            )
    
    def get_schema(self) -> Dict[str, Any]:
        """获取输出 Schema"""
        return {
            "type": "object",
            "properties": {
                "result_field": {"type": "string", "description": "结果描述"}
            }
        }
    
    def _do_analysis_1(self, **kwargs) -> AdapterResult:
        """分析类型1实现"""
        try:
            # 执行分析逻辑
            result_data = {...}
            
            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data=result_data,
                metadata={"analysis_type": "analysis_type_1"}
            )
        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=str(e)
            )
```

#### 步骤 2: 注册到工厂

编辑 `src/tools/adapters/__init__.py`：

```python
def _initialize_builtin_adapters(factory: AdapterFactory):
    # ... 现有代码 ...
    
    # 添加新适配器
    try:
        from .my_adapter import MyAnalysisAdapter
        factory.register_adapter_class("my_analysis", MyAnalysisAdapter)
    except ImportError:
        logger.warning("[AdapterFactory] MyAnalysisAdapter 未找到")
```

#### 步骤 3: 注册为 ToolRegistry 工具

编辑 `src/tools/registry.py`：

```python
def _initialize_adapter_tools():
    # ... 现有代码 ...
    
    # 注册新适配器
    try:
        from .adapters.my_adapter import MyAnalysisAdapter
        from .adapters.wrappers import register_adapter_as_tool
        
        register_adapter_as_tool(
            MyAnalysisAdapter,
            "my_analysis_tool",
            adapter_name="自定义分析工具",
            default_analysis_type="analysis_type_1"
        )
    except ImportError:
        logger.debug("[ToolRegistry] MyAdapter 未安装")
```

#### 步骤 4: 定义 Schema（可选但推荐）

编辑 `src/tools/adapters/schema_registry.py`：

```python
def _load_builtin_schemas(self):
    # ... 现有代码 ...
    
    self.register(
        SchemaDefinition(
            name="my_analysis_result",
            version="1.0.0",
            adapter_class="MyAnalysisAdapter",
            description="自定义分析结果",
            schema={
                "type": "object",
                "properties": {
                    "result_field": {"type": "string"}
                },
                "required": ["result_field"]
            },
            required_fields=["result_field"],
            optional_fields=[]
        )
    )
```

---

### 4.3 工具上下文数据说明

`GenericPlanner._prepare_tool_context()` 为工具准备的上下文：

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

## 五、数据注入流程

### 5.1 工具调用注入流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        1. GenericPlanner.build_prompt()                     │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     2. _execute_tool_hook(state)                            │
│                                                                              │
│   tool_name = self.config.get("tool")  # 从 dimension_metadata 读取         │
│   if not tool_name: return ""                                               │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    3. _prepare_tool_context(state)                          │
│                                                                              │
│   准备上下文字典：raw_data, analysis_reports, concept_reports, etc.         │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                4. ToolRegistry.execute_tool(tool_name, context)             │
│                                                                              │
│   tool_func = cls._tools.get(tool_name)                                     │
│   result = tool_func(context)                                               │
│   return result                                                             │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        5. 注入到 Prompt                                      │
│                                                                              │
│   params["tool_output"] = f"\\n【参考数据 - {tool_name}】\\n{result}\\n"     │
│   prompt = prompt_template.format(**params)                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 RAG 知识注入流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     1. 子图初始化 - knowledge_preload_node                   │
│                                                                              │
│   for dimension in critical_dimensions:                                     │
│       result = knowledge_search_tool.invoke({...})                          │
│       knowledge_cache[dimension] = result                                   │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     2. 状态传递 - state["knowledge_cache"]                   │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              3. GenericPlanner.get_cached_knowledge(state)                  │
│                                                                              │
│   if self.rag_enabled:                                                      │
│       knowledge_context = state.get("knowledge_cache", {}).get(dimension)   │
│   params["knowledge_context"] = knowledge_context                           │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        4. 注入到 Prompt                                      │
│                                                                              │
│   Prompt 中使用 {knowledge_context} 占位符                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 六、待开发与预留接口

### 6.1 待开发工具

| 工具名称 | 功能 | 优先级 | 预留位置 |
|---------|------|--------|---------|
| `service_coverage` | 公共服务覆盖率分析 | 中 | `adapters/service_adapter.py` |
| `infrastructure_capacity` | 基础设施容量分析 | 中 | `adapters/infrastructure_adapter.py` |
| `ecological_assessment` | 生态评估工具 | 高 | `adapters/ecological_adapter.py` |
| `risk_assessment` | 防灾风险评估 | 高 | `adapters/risk_adapter.py` |
| `economic_projection` | 经济预测模型 | 中 | `registry.py` |

### 6.2 预留接口

#### 6.2.1 check_technical_indicators

**文件**: `src/rag/core/tools.py`

**状态**: 框架已建，预留元数据过滤接口

**待实现**:
- 按维度过滤技术指标
- 按地形类型过滤
- 结构化指标输出

#### 6.2.2 planner_tool 增强

**文件**: `src/tools/planner_tool.py`

**状态**: 简化实现

**待实现**:
- 接入规则引擎
- GIS 服务集成
- 多方案比选生成

---

## 八、使用真实数据的改造方案

> 人口预测工具已完成真实模型实现。GIS 和网络分析工具需要以下改造：

### 8.1 人口预测 ✅ 已完成

已实现村庄规划标准模型：`Pn = P0 × (1 + K)^n + M`

调用示例：
```python
from src.tools.adapters.population_adapter import PopulationPredictionAdapter

adapter = PopulationPredictionAdapter()
result = adapter.execute(
    analysis_type="village_forecast",
    baseline_population=1406,
    baseline_year=2024,
    target_year=2035,
    natural_growth_rate=4.0,  # ‰
    mechanical_growth=200
)
# result.data["forecast_population"] = 1681
```

---

### 8.2 GIS 工具改造 ⚠️ 待完成

**问题**: `gis_coverage_calculator` 未传递 `geo_data_path`

**方案**: 修改 `_prepare_tool_context()` 或工具调用逻辑

```python
# 在 GenericPlanner._prepare_tool_context() 中添加
context["geo_data_path"] = state.get("geo_data_path")  # 或从配置读取
```

**数据准备**: 需要村庄的 GIS 空间数据文件（`.shp` / `.geojson`）

---

### 8.3 网络分析改造 ⚠️ 待完成

**问题**: `network_accessibility` 未传递 `network_data`

**方案**: 从村庄数据中提取路网结构

```python
# 在 GenericPlanner._prepare_tool_context() 中添加
context["network_data"] = {
    "nodes": extract_nodes_from_village_data(state),
    "edges": extract_edges_from_village_data(state)
}
```

**数据准备**: 需要路网节点和边的结构化数据

---

## 九、常见问题

### Q1: 如何调试工具调用？

```python
# 在 GenericPlanner._execute_tool_hook() 中添加日志
logger.info(f"[{self.dimension_name}] 调用工具: {tool_name}")
logger.debug(f"[{self.dimension_name}] 工具上下文: {tool_context}")
```

### Q2: 工具执行失败会怎样？

工具执行失败不会中断流程，错误信息会被注入到 Prompt：

```python
except Exception as e:
    return f"\n【工具执行失败】\n{str(e)}\n"
```

### Q3: 如何添加新的数据源到工具上下文？

编辑 `GenericPlanner._prepare_tool_context()`：

```python
def _prepare_tool_context(self, state: Dict[str, Any]) -> Dict[str, Any]:
    context = {}
    # ... 现有代码 ...
    
    # 添加新数据源
    context["my_data"] = state.get("my_data", "")
    
    return context
```

### Q4: Adapter 和 ToolRegistry 工具有什么区别？

| 对比项 | ToolRegistry 工具 | Adapter 工具 |
|-------|------------------|--------------|
| 复杂度 | 简单函数 | 完整类 |
| Schema | 无 | 有完整 Schema |
| 状态管理 | 无 | 有状态机 |
| 依赖检查 | 无 | 自动检查 |
| 适用场景 | 简单计算 | 专业计算库封装 |

---

## 十、文件索引

| 文件路径 | 功能描述 |
|---------|---------|
| `src/tools/__init__.py` | 工具模块导出 |
| `src/tools/registry.py` | 工具注册中心 |
| `src/tools/file_manager.py` | 文件管理器 |
| `src/tools/knowledge_tool.py` | 知识检索工具接口 |
| `src/tools/planner_tool.py` | 规划工具 |
| `src/tools/revision_tool.py` | 修复工具 |
| `src/tools/web_review_tool.py` | Web 审查工具 |
| `src/tools/adapters/__init__.py` | Adapter 工厂 |
| `src/tools/adapters/base_adapter.py` | Adapter 基类 |
| `src/tools/adapters/gis_adapter.py` | GIS 分析适配器 |
| `src/tools/adapters/network_adapter.py` | 网络分析适配器 |
| `src/tools/adapters/population_adapter.py` | 人口预测适配器 |
| `src/tools/adapters/schema_registry.py` | Schema 注册表 |
| `src/tools/adapters/wrappers.py` | Adapter 包装器 |
| `src/config/dimension_metadata.py` | 维度配置（含 tool 字段） |
| `src/config/dimension_keys.py` | 维度键名枚举 |
| `src/planners/generic_planner.py` | 规划器（工具调用入口） |
| `src/rag/core/tools.py` | RAG 知识检索工具集 |
