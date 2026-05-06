---
marp: false
theme: gaia
paginate: true
size: 16:9
style: |
  section { font-size: 26px; }
  h1 { font-size: 46px; }
  h2 { font-size: 36px; }
  h3 { font-size: 30px; }
  table { font-size: 22px; }
  code { font-size: 20px; }
  pre { font-size: 18px; }
---

# 村庄规划智能体
## Village Planning Agent

**基于 LangGraph 的智能村庄规划系统**

版本 2.2.0 | 2026年4月

---

# 目录

1. 项目概述
2. 前端架构
3. 后端Agent架构
4. 三层规划流程
5. GenericPlanner统一规划器
6. 波次调度机制
7. 工具系统
8. RAG 知识检索
9. 人工审查与修订
10. 实际运行数据
11. GIS 空间智能
12. 总结

---

# 项目概述

## 核心定位

将村庄规划从"人工经验驱动"升级为"AI智能辅助"

## 主要功能

- **三层递进规划**：现状分析 → 规划思路 → 详细规划
- **28维度覆盖**：全面涵盖村庄规划各专业领域（12+4+12）
- **RAG知识增强**：法规条文与技术指标智能注入
- **GIS空间智能**：空间分析、POI搜索、等时圈分析
- **实时交互**：Token级流式输出，支持人工审查与修订反馈

---

# 前端架构

## 技术栈

- **框架**: Next.js 14 + React 18
- **状态管理**: Zustand + Immer 中间件
- **样式**: Tailwind CSS
- **地图**: Leaflet + React-Leaflet

## 核心特性

- 批量SSE事件处理（50ms窗口合并）
- Signal-Fetch模式（轻量信号 + REST获取完整数据）
- 派生状态自动计算（deriveUIStateInStore）
- 指数退避重连机制

---

# 前端组件结构

```
frontend/src/components/
├── chat/                    # 聊天组件（33个）
│   ├── ChatPanel, MessageList, MessageBubble
│   ├── LayerReportCard, DimensionSection
│   ├── ReviewPanel, ProgressPanel
│   ├── GisResultCard, KnowledgeSliceCard
│   └── ToolStatusPanel
├── layout/                  # 布局组件
│   ├── UnifiedLayout, Header, HistoryPanel
│   └ KnowledgePanel, LayerSidebar
├── gis/                     # GIS组件
│   └── MapView, DataUpload
└── ui/                      # UI基础组件
```

---

# 前端消息类型系统

## 核心消息类型（7种）

| 类型 | 用途 | 特殊字段 |
|------|------|----------|
| text | 用户/助手文本 | streamingState, knowledgeReferences |
| layer_completed | 层级完成报告 | dimensionReports, actions |
| dimension_report | 维度报告 | layer, dimensionKey, gisData |
| gis_result | GIS分析结果 | layers, mapOptions, analysisData |
| tool_status | 工具执行状态 | status, progress, stage |
| file | 文件消息 | filename, imageBase64 |
| progress | 进度消息 | progress, currentLayer |

---

# 后端Agent架构

## Router Agent 设计

单一StateGraph + 单一状态定义，中央路由模式

```
[用户输入]
    │
    ▼
conversation_node (LLM: bind_tools)
    │ intent_router
    ├─► [闲聊/问答] END
    ├─► [工具调用] execute_tools
    └─► [推进规划] route_by_phase
                          │
                   [Send N 维度]
                          │
                          ▼
                  analyze_dimension
                          │
                          ▼
                  collect_results
```

---

# StateGraph节点定义

## 核心节点（8个）

| 节点 | 职责 |
|------|------|
| conversation | LLM对话 + 意图识别 |
| execute_tools | 执行LLM返回的工具调用 |
| knowledge_preload | 知识并行预加载 |
| analyze_dimension | 维度分析（Send分发） |
| emit_events | 批量发送SSE事件 |
| collect_results | 收集维度结果 |
| advance_phase | 推进阶段 |
| revision | 修订节点（级联更新） |

---

# GenericPlanner统一规划器

## 架构特点

单一类支持所有28个维度（Layer 1/2/3）

```python
class GenericPlanner:
    def __init__(self, dimension_key: str):
        # 从 DIMENSIONS_METADATA 加载配置
        self.layer = config["layer"]
        self.tool_name = config.get("tool")  # 工具钩子
        self.rag_enabled = config.get("rag_enabled")

    def execute(self, state, streaming=False) -> dict:
        # 1. validate_state()
        # 2. build_prompt()
        # 3. _execute_tool_hook()  # 自动执行绑定工具
        # 4. get_cached_knowledge()  # 从缓存读取RAG知识
        # 5. _invoke_llm()  # 调用LLM
```

---

# GenericPlanner核心特性

## Python模块驱动

- Prompt模板从Python模块加载（analysis_prompts.py等）
- 不依赖YAML配置文件

## 工具钩子机制

```python
def _execute_tool_hook(self, state):
    """自动执行维度配置的tool字段"""
    if self.tool_name:
        result = ToolRegistry.execute_tool(self.tool_name, context)
        return f"\n【参考数据 - {tool_name}】\n{result}"
```

## 关键维度（需RAG原文）

| 维度 | 原因 |
|------|------|
| land_use | 土地分类法规 |
| infrastructure | 技术规范标准 |
| disaster_prevention | 安全强制标准 |

---

# 三层规划流程

```
用户输入村庄数据
        ↓
┌─────────────────────────────────┐
│ Layer 1: 现状分析 (12维度并行)   │
│ 区位·社会·村民诉求·上位规划      │
│ 自然·土地·交通·公服·设施        │
│ 生态绿地·建筑·历史文化           │
└─────────────────────────────────┘
        ↓
┌─────────────────────────────────┐
│ Layer 2: 规划思路 (4维度波次)    │
│ Wave1:资源禀赋 → Wave2:规划定位  │
│ Wave3:发展目标 → Wave4:规划策略  │
└─────────────────────────────────┘
        ↓
┌─────────────────────────────────┐
│ Layer 3: 详细规划 (12维度波次)   │
│ Wave1: 11维度并行               │
│ Wave2: 项目库                   │
└─────────────────────────────────┘
```

---

# Layer 1: 现状分析

## 执行模式：Map-Reduce 并行

**核心机制**：12个维度同时执行，互不依赖

## 12个分析维度

| 维度 | 分析内容 | 绑定工具 |
|------|----------|----------|
| 区位交通 | 地理位置、交通区位 | - |
| 社会经济 | 人口结构、经济产业 | population_model_v1 |
| 自然环境 | 气候水文、生态条件 | wfs_data_fetch |
| 土地利用 | 用地结构、规模分布 | gis_coverage_calculator |
| 道路交通 | 内部道路、通达性 | accessibility_analysis |
| 公共服务 | 教育医疗、便民设施 | poi_search |

---

# Layer 1: 现状分析（续）

| 维度 | 分析内容 | 绑定工具 |
|------|----------|----------|
| 村民诉求 | 发展期望、参与意愿 | - |
| 上位规划 | 政策要求、规划约束 | - |
| 基础设施 | 供水供电、环卫设施 | - |
| 生态绿地 | 绿地公园、环境质量 | - |
| 建筑 | 建筑质量、风格分布 | - |
| 历史文化 | 文化遗产、民俗风情 | - |

---

# 知识预加载：并行机制

## asyncio.gather 并行执行

```python
async def knowledge_preload_node(state):
    dimensions = get_layer_dimensions(layer)

    # 检查已有缓存，跳过已缓存的维度
    fetch_dims = [d for d in dimensions if d not in existing_cache]

    # 并行检索（Semaphore控制并发数）
    semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENT)

    async def fetch_one(dim_key):
        async with semaphore:
            result = await asyncio.to_thread(search_knowledge, ...)
            return (dim_key, result)

    results = await asyncio.gather(*[fetch_one(d) for d in fetch_dims])
```

**优势**：总时间从串行之和降至 max(各维度时间)

---

# Layer 2: 规划思路

## 执行模式：波次执行（依赖驱动）

**核心机制**：根据维度间依赖关系，按波次顺序执行

## 4个规划思路维度

| Wave | 维度 | 同层依赖 |
|------|------|----------|
| 1 | 资源禀赋 | 无 |
| 2 | 规划定位 | resource_endowment |
| 3 | 发展目标 | resource_endowment, planning_positioning |
| 4 | 规划策略 | 前3个维度 |

---

# 波次计算：拓扑排序

## 自动波次计算

```python
def _calculate_wave(dimension_key, chain):
    """
    Wave = 1 + max(wave of dependencies within same layer)

    示例：
    - resource_endowment: 无同层依赖 → Wave 1
    - planning_positioning: 依赖 Wave 1 → Wave 2
    - development_goals: 依赖 Wave 2 → Wave 3
    """
    deps = chain[dimension_key]
    same_layer_deps = deps.get("depends_on_same_layer", [])

    if not same_layer_deps:
        return 1

    return max(_calculate_wave(d, chain) for d in same_layer_deps) + 1
```

---

# Layer 3: 详细规划

## 12个详细规划维度

| 维度 | 规划内容 | 绑定工具 |
|------|----------|----------|
| 产业规划 | 产业发展方向、重点项目 | - |
| 空间结构 | 功能分区、发展轴线 | planning_vectorizer |
| 土地利用 | 用地布局、指标平衡 | - |
| 居民点规划 | 宅基地布局、风貌引导 | - |
| 道路交通 | 道路系统、停车布局 | isochrone_analysis |
| 公共服务 | 设施配置、服务半径 | facility_validator |

---

# Layer 3: 详细规划（续）

| 维度 | 规划内容 | 绑定工具 |
|------|----------|----------|
| 基础设施 | 给排水、电力通信 | - |
| 生态绿地 | 绿地系统、生态修复 | ecological_sensitivity |
| 防震减灾 | 灾害评估、防灾设施 | - |
| 历史文保 | 保护对象、保护措施 | - |
| 村庄风貌 | 风貌定位、景观控制 | - |
| 项目库 | 建设项目清单、投资估算 | - |

---

# 工具系统

## 工具注册机制

```python
class ToolRegistry:
    @classmethod
    def register(cls, name: str):
        """装饰器注册工具"""
        def decorator(func):
            cls._tools[name] = func
            return func
        return decorator

    @classmethod
    def execute_tool(cls, name, context):
        """执行工具并返回结果"""
        return cls._tools[name](context)
```

## 工具元数据

```python
@dataclass
class ToolMetadata:
    name: str
    description: str
    display_name: str
    parameters: Dict
    display_hints: {"primary_view": "map", "priority_fields": []}
```

---

# GIS工具分类

## 空间分析工具

| 工具 | 功能 | 文件 |
|------|------|------|
| spatial_overlay | 空间叠加（intersect/union） | spatial_analysis.py |
| spatial_query | 空间查询（contains/nearest） | spatial_analysis.py |

## 数据获取工具

| 工具 | 功能 | 数据源 |
|------|------|------|
| wfs_data_fetch | 天地图WFS数据 | 天地图 |
| poi_search | POI搜索 | 高德优先 |
| gis_coverage_calculator | 覆盖率计算 | 本地计算 |

## 规划分析工具

| 工具 | 功能 |
|------|------|
| isochrone_analysis | 等时圈（可达范围） |
| planning_vectorizer | 规划矢量化 |
| facility_validator | 设施选址验证 |
| ecological_sensitivity | 生态敏感性分析 |

---

# 结果规范化层

## NormalizedToolResult

统一的工具结果格式，确保前端展示一致

```python
class ResultDataType(Enum):
    GEOJSON = "geojson"       # GIS数据（地图展示）
    ANALYSIS = "analysis"     # 分析结果（图表/表格）
    TEXT = "text"             # 纯文本内容
    ERROR = "error"           # 错误信息

@dataclass
class NormalizedToolResult:
    success: bool
    data_type: ResultDataType
    data: Dict[str, Any]
    summary: str
    metadata: Dict[str, Any]
```

---

# POI Provider: 高德优先策略

## 架构设计

```
src/tools/geocoding/
├── amap/provider.py      # 高德API（30 QPS）
│   ├── gcj02_to_wgs84()  # 坐标转换
│   └── search_poi_*()
├── tianditu/provider.py  # 天地图（回退）
└── poi_provider.py       # 统一接口
```

## 执行流程

```
用户请求 → 高德搜索 → 成功则返回(标记source=amap)
                   ↓ 失败
              回退天地图 → 返回(标记source=tianditu)
```

---

# ParamSource枚举

## 工具参数来源类型

```python
class ParamSource(str, Enum):
    LITERAL = "literal"       # 固定值（硬编码）
    GIS_CACHE = "gis_cache"   # 从GIS缓存取值
    CONFIG = "config"         # 从state.config取值
    CONTEXT = "context"       # 从context直接取值
```

## 配置示例

```python
"traffic": {
    "tool": "accessibility_analysis",
    "tool_params": {
        "analysis_type": {"source": "literal", "value": "service_coverage"},
        "center": {"source": "gis_cache", "path": "_auto_fetched.center"}
    }
}
```

---

# RAG 知识检索

## 功能定位

为规划生成提供法规依据和技术标准支持

## 三类文档来源

| 类别 | 用途 | 存储路径 |
|------|------|----------|
| policies | 政策法规文件 | data/policies/ |
| cases | 规划案例文件 | data/cases/ |
| textbooks | 专业知识教科书 | data/textbooks/ |

---

# RAG: 切片与向量

## 切片策略

```
RecursiveCharacterTextSplitter
├── chunk_size: 2500 字符
├── chunk_overlap: 500 字符
└── 分隔符优先级: 段落 → 句子 → 词
```

## 向量化引擎

| 方案 | 模型 | 维度 |
|------|------|------|
| 本地 | BAAI/bge-small-zh-v1.5 | 512 |
| 云端 | 阿里云 text-embedding-v4 | 1024 |

---

# RAG: 上下文模式

| 模式 | 返回内容 | 适用场景 |
|------|----------|----------|
| minimal | 仅匹配片段 | 快速查找 |
| standard | 片段+300字上下文 | 常规检索（默认） |
| expanded | 片段+500字上下文 | 需更多上下文 |

---

# 人工审查与修订

## 步进模式

每层完成后暂停，等待人工审查

## 审查操作

| 操作 | 说明 |
|------|------|
| 通过 | 确认当前层级，继续执行 |
| 驳回 | 提供反馈意见，指定维度修复 |
| 回退 | 回到指定Checkpoint重新执行 |

---

# 修订节点：级联更新

## 影响树计算

当修改某维度时，自动计算需要级联更新的下游维度

```python
def get_revision_wave_dimensions(targets, completed):
    """
    合并多个目标维度的影响树，按波次分组

    示例：
    >>> get_revision_wave_dimensions(["natural_environment"], completed)
    {
        0: ["natural_environment"],       # 目标维度
        1: ["resource_endowment", "ecological"],  # 直接依赖
        2: ["planning_positioning"],      # 二级依赖
        3: ["project_bank"]               # 三级依赖
    }
    """
```

---

# 级联更新流程

```
用户反馈: "自然环境分析需要补充地质灾害"
        ↓
系统识别维度: natural_environment
        ↓
计算影响树: {Wave1: [resource_endowment, ecological],
            Wave2: [planning_positioning],
            Wave3: [project_bank]}
        ↓
按波次执行: Wave0修复 → Wave1并行 → Wave2 → Wave3
        ↓
完成级联更新
```

---

# 实际运行数据

## 金田村规划案例

| 指标 | 数值 |
|------|------|
| 项目名称 | 金田村 |
| 模型 | deepseek-chat |
| Layer 1 维度数 | 12个并行 |
| LLM Chunk 数 | 190-260/维度 |
| 输出长度 | 327-420字符/维度 |
| 知识缓存命中 | 5个维度 |

---

# GIS 空间智能

## 两大数据流

```
┌─────────────────────────────────────────────────────────┐
│                      GIS 空间智能                        │
├───────────────────────┬─────────────────────────────────┤
│     空间数据集成        │       规划图件生成              │
│   GIS → 规划分析输入    │    规划文本 → 图件输出          │
└───────────────────────┴─────────────────────────────────┘
```

## 坐标转换

高德GCJ-02 → 天地图WGS-84

```python
def gcj02_to_wgs84(lon, lat):
    """近似转换，残余偏移 < 5米"""
    # 算法实现...
```

---

# 关键文件路径

## 前端核心

| 类别 | 路径 |
|------|------|
| 状态管理 | frontend/src/stores/planningStore.ts |
| SSE连接 | frontend/src/hooks/planning/useSSEConnection.ts |
| 消息类型 | frontend/src/types/message/message-types.ts |

## 后端核心

| 类别 | 路径 |
|------|------|
| 主入口 | src/agent.py |
| 状态图 | src/orchestration/main_graph.py |
| 统一规划器 | src/planners/generic_planner.py |
| 维度元数据 | src/config/dimension_metadata.py |
| 工具注册 | src/tools/registry.py |

---

# 总结：核心功能特性

| 功能 | 实现方式 | 价值 |
|------|----------|------|
| 三层递进规划 | LangGraph子图编排 | 层层深入 |
| 28维度覆盖 | Python配置驱动 | 专业全面 |
| GenericPlanner | 统一类+工具钩子 | 架构简洁 |
| Map-Reduce并行 | Send机制分发 | 高效执行 |
| 波次智能调度 | 拓扑排序计算 | 顺序正确 |
| 知识并行预加载 | asyncio.gather | 时间优化 |
| GIS空间智能 | 高德优先策略 | 数据丰富 |
| Token级流式 | SSE+批量处理 | 实时交互 |
| 级联修订 | 影响树计算 | 质量可控 |

---

# 谢谢！

## 项目地址

- GitHub: `hanyi690/Village_Planning_Agent`
- 文档: `docs/architecture/` 目录

---

<!--
导出说明：
1. 在 VS Code 中安装 Marp for VS Code 插件
2. 打开此 Markdown 文件
3. 点击右上角预览按钮查看效果
4. 右键选择 "Export slide deck..." 导出为 PPTX/PDF/HTML
-->