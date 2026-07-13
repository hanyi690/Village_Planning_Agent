# GIS 系统架构

> **更新日期**: 2026-07-08
> **版本**: v4.0 (Trinity 架构 + ReAct Agent)

本文档详细说明 GIS 数据获取、空间布局引擎、GIS Agent 子图和前端可视化的完整链路。

## 目录

- [系统概览](#系统概览)
- [数据来源与优先级](#数据来源与优先级)
- [用户上传系统](#用户上传系统)
- [边界兜底机制](#边界兜底机制)
- [坐标系统](#坐标系统)
- [维度与 GIS 工具绑定](#维度与-gis-工具绑定)
- [GIS Agent ReAct 子图](#gis-agent-react-子图)
- [布局规划工具详解](#布局规划工具详解)
- [规划知识图谱](#规划知识图谱)
- [分区分配器](#分区分配器)
- [验证与精炼](#验证与精炼)
- [SSE 数据流转](#sse-数据流转)
- [前端可视化](#前端可视化)
- [诊断与调试](#诊断与调试)

---

## 系统概览

### Trinity 三层架构

GIS 系统采用 Trinity 三层架构，从数据获取到空间布局生成形成完整闭环：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Layer 1 — Planning KG (规划知识图谱)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                      │
│  │  RDF 三元组   │  │ SPARQL 查询  │  │ Turtle 序列化 │                      │
│  │ 16 实体类型   │  │  12 模板     │  │  跨工具持久化  │                      │
│  │ 11 关系类型   │  │  约束提取    │  │  kg_turtle    │                      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                      │
└─────────┼─────────────────┼─────────────────┼──────────────────────────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  Layer 2 — Agentic Pipeline (ReAct 推理管线)                 │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  GIS Agent: create_react_agent(llm, 10 tools, GISAgentState)        │   │
│  │  6 步 ReAct: parse → build KG → query → detect → allocate → gen    │   │
│  │  验证: validate_layout (最多 3 次重试)                                │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│               Layer 3 — Spatial Generator (空间生成器)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ 冲突检测/消解 │  │  MIP 分配器   │  │   CA 精炼    │  │  验证循环    │   │
│  │ ConflictDet  │  │ PuLP 二值变量 │  │ buffer→union │  │ 3轮+0.2阻尼  │   │
│  │ ConflictRes  │  │ DLBM 约束裁剪│  │ →debuffer    │  │ 8项空间检查  │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         数据源层                                            │
├────────────────┬────────────────┬────────────────┬──────────────────────────┤
│   用户上传     │   天地图 API    │    高德 API     │     其他数据源           │
│  - GeoJSON     │   - WFS 服务    │   - POI 搜索    │    - 路径规划           │
│  - Shapefile   │   - 地理编码    │   - 地理编码    │    - 等时圈分析         │
│  - KML/GDB     │   - POI 搜索    │   - 路径规划    │                          │
└────────┬───────┴────────┬───────┴────────┬───────┴──────────┬───────────────┘
         │                │                │                  │
         ▼                ▼                ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         数据解析与管理层                                       │
├────────────────┬────────────────┬────────────────┬──────────────────────────┤
│ GISDataParser  │ GISDataManager │SharedGISContext│   GISDataFetcher        │
│ - 格式解析     │ - 内存缓存     │ - 上下文管理    │    - WFS 数据           │
│ - CRS 转换     │ - 状态追踪     │ - 数据注入     │    - 村级定位           │
│ - 类型推断     │ - 按村庄组织   │ - 边界生成     │                          │
└────────────────┴────────────────┴────────────────┴──────────────────────────┘
```

### SpatialLayoutEngine 4 阶段 Pipeline

```python
# backend/app/services/modules/gis/layout/engine.py
class SpatialLayoutEngine:
    """KG-driven spatial layout engine."""

    def build_kg(reports, landuse_geojson) -> self
        """构建规划知识图谱（lazy init）"""

    def detect_and_resolve(summaries) -> (ConflictReport, ResolutionReport)
        """Phase 0: 冲突检测 + 消解"""

    def generate_layout(intent, gis_context, ...) -> List[Dict]
        """Phase 1: 生成多图层布局（6 层 GeoJSON 增量推送）"""

    def full_pipeline(summaries, intent, ...) -> (ConflictReport, ResolutionReport, List, PipelineTrace)
        """完整 Phase 0 + Phase 1 + 验证循环（最多 3 轮）"""
```

### 6 层 GeoJSON 输出

| 层类型 | 说明 | 渲染方式 |
|--------|------|----------|
| `boundary` | 行政边界 | 线 |
| `function_zone` | 7 类功能区（GB/T 21010） | 面 |
| `planning_zone` | 4 类规划分区（三区三线） | 面 |
| `sensitivity_zone` | 敏感区 | 面 |
| `facility_point` | 设施点位 | 点 |
| `development_axis` | 发展轴线 | 线 |

---

## 数据来源与优先级

### 数据获取优先级

系统采用三级优先级策略获取 GIS 数据：

| 优先级 | 来源 | 说明 | 适用场景 |
|--------|------|------|----------|
| 1 (最高) | 用户上传 | 用户通过 `/api/gis/upload` 上传的 GIS 文件 | 精确边界、自定义数据 |
| 2 | 会话缓存 | GISDataManager 内存缓存 | 同一村庄重复操作 |
| 3 (最低) | API 自动获取 | 天地图 WFS / 高德 POI API | 数据缺失时兜底 |

### 数据类型

| 数据类型 | 标识符 | 典型来源 | 用途 |
|----------|--------|----------|------|
| 行政边界 | `boundary` | 用户上传 / 兜底生成 | 规划范围界定 |
| 水系 | `water` | 天地图 WFS (HYDA/HYDL) | 生态敏感区分析 |
| 道路 | `road` | 天地图 WFS (LRDL) / 高德 | 交通可达性分析 |
| 居民地 | `residential` | 天地图 WFS (RESA/RESP) | 人口分布分析 |
| POI 设施 | `poi` | 高德 POI API | 公共服务覆盖分析 |
| 土地利用 | `landuse` | 用户上传 | 用地结构分析 |
| 保护红线 | `protection_zone` | 用户上传 | 生态农田保护 |
| 地质灾害 | `geological_hazard` | 用户上传 | 安全风险评估 |

---

## 用户上传系统

### 支持的 GIS 格式

| 格式 | 扩展名 | 解析库 | 说明 |
|------|--------|--------|------|
| GeoJSON | `.geojson`, `.json` | JSON 内置 | 前端可直接渲染 |
| Shapefile | `.zip` (含 `.shp`) | geopandas | 需完整文件集打包 |
| GDB | `.zip` (含 `.gdb`) | geopandas | ArcGIS File Geodatabase |
| KML | `.kml` | fastkml | Google Earth 格式 |
| KMZ | `.kmz` | fastkml + zipfile | KML 压缩格式 |
| GeoTIFF | `.tif`, `.tiff` | rasterio | 栅格数据矢量化 |

**不支持格式：**
- `.mpk` (ArcGIS Map Package) - 请导出为 Shapefile
- `.mxd` (ArcGIS Map Document) - 请导出为 Shapefile

### 上传解析流程

```
用户上传文件
    │
    ▼
GISDataParser.parse_from_bytes()
    ├── GeoJSON → JSON.loads() → 直接返回
    ├── Shapefile ZIP → 解压 → geopandas.read_file() → CRS 转换
    ├── GDB ZIP → 解压 → geopandas.list_layers() → 合并图层
    ├── KML → fastkml 解析 → Placemark 提取
    └── GeoTIFF → rasterio 矢量化 → CRS 转换
    │
    ▼
infer_data_type() → 智能类型推断
    │
    ▼
GISDataManager.set_user_data() → 内存缓存存储
```

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/gis/upload` | POST | 上传 GIS 文件 |
| `/api/gis/status/{village_name}` | GET | 查询数据状态 |
| `/api/gis/clear/{village_name}/{data_type}` | DELETE | 清除指定数据 |
| `/api/gis/supported-formats` | GET | 获取支持格式列表 |

### 智能类型推断

`GISDataParser.infer_data_type()` 根据属性字段关键词推断数据类型：

```python
LAYER_TYPE_KEYWORDS = {
    'boundary': ['边界', '行政区划', '行政村', '村界', 'boundary', 'XZDM', 'XZMC'],
    'landuse': ['土地利用', '用地', '图斑', '地类', 'DLBM', 'DLMC', '耕地', '林地'],
    'road': ['道路', '路网', '交通', 'road', '公路', '村道', '省道', '国道'],
    'water': ['水系', '河流', '水域', 'water', 'HYD', '河流名称', '湖泊'],
    'residential': ['居民点', '居住', '村庄', 'residential', '人口', '户数'],
    'poi': ['设施', 'POI', '公共', '服务', '学校', '医院', 'facility_type'],
    'protection_zone': ['红线', '保护', '农田', '生态', '基本农田', '生态红线'],
    'geological_hazard': ['地质', '灾害', '隐患', '滑坡', '崩塌', '泥石流'],
}
```

---

## 边界兜底机制

当用户未上传边界数据时，系统采用多级兜底策略生成代理边界。

### 5 级兜底策略

| 优先级 | 策略名称 | 数据依赖 | 精度 | 说明 |
|--------|----------|----------|------|------|
| 1 | `user_uploaded` | GISDataManager 缓存 | 最高 | 用户上传的精确边界 |
| 2 | `isochrone` | 村庄中心点 | 中高 | 15 分钟步行等时圈 |
| 3 | `polygonize_fusion` | 道路+水系线要素 | 中 | 自然边界融合 |
| 4 | `morphological_convex` | 居民地 RESA 特征 | 中低 | 凸包/凹包形态 |
| 5 | `bbox_buffer` | 仅中心点 | 低 | 2km 矩形缓冲（保底） |

### 边界生成 API

```python
# SharedGISContext.get_or_generate_boundary()
boundary = gis_context.get_or_generate_boundary(
    force_generate=False,
    config=BoundaryFallbackConfig(
        isochrone_time_minutes=15,
        polygonize_min_lines=3,
        morphological_min_features=5,
        bbox_buffer_km=2.0,
    )
)
```

---

## 坐标系统

### 坐标系说明

| 坐标系 | 使用方 | 特点 |
|--------|--------|------|
| WGS84 | 国际通用、MapLibre 默认 | GPS 原始坐标 |
| GCJ-02 | 高德地图 | 中国加密坐标系，偏移 50-500m |
| CGCS2000 | 天地图 | 中国大地坐标系，与 WGS84 兼容 |

### 坐标转换流程

```
高德 POI 数据 (GCJ-02)
    │
    ▼
gcj02_to_wgs84() 坐标转换
    │
    ▼
GeoJSON (WGS84)
    │
    ▼
前端 MapLibre 渲染
```

### 数据源坐标系统

| 数据源 | 原始坐标系 | 转换后 | 说明 |
|--------|-----------|--------|------|
| 天地图 WFS | CGCS2000 | 无需转换 | 与 WGS84 兼容 |
| 天地图 POI | CGCS2000 | 无需转换 | 与 WGS84 兼容 |
| 天地图瓦片 | 经纬度投影 | 无需转换 | 与 WGS84 兼容 |
| 高德 POI | GCJ-02 | WGS84 | 自动转换 |
| 用户上传 | 可能非 WGS84 | WGS84 | geopandas 自动转换 |

---

## 维度与 GIS 工具绑定

### Layer 1: 现状分析（12 个维度）

| 维度 | 维度名称 | GIS 工具 | 数据来源 | 分析结果 |
|------|----------|----------|----------|----------|
| `natural_environment` | 自然环境分析 | `calculate_gis_coverage` | 用户上传 + WFS | 水系/道路/居民地 GeoJSON + 村庄中心坐标 |
| `land_use` | 土地利用分析 | `calculate_gis_coverage` | 用户上传 | 用地结构统计 + GeoJSON 图层 |
| `traffic` | 道路交通分析 | `analyze_accessibility` | 用户上传 + WFS + 高德 | 服务覆盖分析 + 可达性矩阵 |
| `public_services` | 公共服务设施分析 | `search_poi` | 高德 POI API | POI 列表 + GeoJSON 点图层 |
| `socio_economic` | 社会经济分析 | `population_model_v1` | 无 GIS | 人口预测数据 |

### Layer 3: 详细规划（12 个维度）

| 维度 | 维度名称 | GIS 工具 | 数据来源 | 分析结果 |
|------|----------|----------|----------|----------|
| `spatial_structure` | 空间结构规划 | GIS Agent 全链路 | 边界 + 规划方案 + 用地数据 | 6 层 GeoJSON + PipelineTrace |
| `traffic_planning` | 道路交通规划 | `analyze_accessibility` | 村庄中心 | 5/10/15 分钟等时圈 GeoJSON |
| `public_service` | 公共服务设施规划 | `search_poi` | 规划设施位置 | 设施覆盖评估 + 建议优化点 |
| `ecological` | 生态绿地规划 | `calculate_gis_coverage` | 水系 + 规划边界 | 敏感区分布 GeoJSON + 分级评估 |

### spatial_structure 全链路

`spatial_structure` 维度由 GIS Agent 执行完整的 6 步 ReAct 工作流：

```
parse_planning_text → build_knowledge_graph → query_knowledge_graph(×3)
    → detect_conflicts → allocate_zones → generate_layout → validate_layout
```

---

## GIS Agent ReAct 子图

### 架构

GIS Agent 使用 LangGraph `create_react_agent` 构建 ReAct 子图，包含 10 个工具：

```python
# backend/app/agent/gis/graph.py
def create_gis_agent_graph():
    """Create GIS ReAct Agent subgraph (cached singleton)."""
    llm = ChatOpenAI(model=LLM_MODEL, temperature=0)
    graph = create_react_agent(
        llm,
        GIS_TOOLS,          # 10 tools: 4 data + 6 layout
        state_schema=GISAgentState,
        prompt=GIS_AGENT_SYSTEM_PROMPT,
    )
    return graph
```

### GISAgentState

```python
# backend/app/agent/gis/state.py
class GISAgentState(TypedDict, total=False):
    # Input (from main graph)
    session_id: str
    village_name: str
    reports: Dict[str, Dict[str, Any]]       # L1/L2/L3 reports
    summaries: Dict[str, Dict[str, Any]]     # Dimension summaries

    # GIS data (keyed by type)
    gis_data: Dict[str, Optional[Dict[str, Any]]]

    # KG persistence across tool calls
    kg_turtle: str                           # RDFlib Turtle serialization
    kg_constraints: List[Dict[str, Any]]     # Extracted constraints

    # Agent shared state (tools read/write)
    layout_configs: List[Dict[str, Any]]     # Generated layer configs
    allocated_geojson: Dict[str, Any]        # Zone allocation result
    allocation_summary: Dict[str, Any]       # Summary stats

    # ReAct loop state
    messages: Annotated[List[BaseMessage], add_messages]
    remaining_steps: NotRequired[Annotated[int, RemainingStepsManager]]
```

### 6 步 ReAct 工作流

```
Step 0: parse_planning_text()
    │  从规划报告解析空间布局意图 → UnifiedSpatialIntent
    ▼
Step 1: build_knowledge_graph()
    │  构建规划知识图谱（调用一次）→ kg_turtle + kg_constraints
    ▼
Step 2: query_knowledge_graph(template_name, ...)  [×3 必须查询]
    │  查询关键约束：
    │  - get_constraint_by_field("construction") → 建设用地上限
    │  - get_constraint_by_field("farmland")     → 耕地保有量下限
    │  - get_constraint_by_field("ecological")   → 生态红线约束
    ▼
Step 3: detect_conflicts()
    │  检测维度间指标冲突 + 约束违反 → ConflictReport
    ▼
Step 4: allocate_zones(targets, constraints, mode)
    │  分配功能分区（greedy 或 MIP 模式）→ allocated_geojson
    ▼
Step 5: generate_layout(intent)
    │  生成多图层布局（6 层 GeoJSON 增量推送）→ layout_configs
    ▼
validate_layout(layout_configs, constraints)
    │  验证结果（不满足则回到 Step 4 调整，最多 3 次）
    ▼
  输出: layout_configs + pipeline_trace
```

### 主图集成

GIS Agent 作为主图 `gis_agent` 节点集成，由 `after_conversation` 路由触发：

```python
# backend/app/agent/graph.py
builder.add_node("gis_agent", gis_agent_node, error_handler=_gis_error_handler)

def _gis_error_handler(state, error: Exception) -> Command:
    """GIS Agent 错误处理 — 返回错误消息到 conversation"""
    return Command(
        update={"messages": [AIMessage(content=f"GIS 分析出错: {error}")]},
        goto="conversation",
    )
```

路由规则：`conversation` 节点检测到 `GISAnalysis` 工具调用时，路由到 `gis_agent` → 完成后返回 `conversation`。

### 约束优先级

```
农田保护 > 生态保护 > 建设发展
```

---

## 布局规划工具详解

### 数据获取工具（4 个）

#### 1. fetch_gis_data

```python
@tool
def fetch_gis_data(location: str, buffer_km: float = 5.0, max_features: int = 500)
```

获取基础 GIS 数据（水系、道路、居民地），来源：天地图 WFS + OSM。

#### 2. calculate_gis_coverage

```python
@tool
def calculate_gis_coverage(location: str, buffer_km: float = 5.0, max_features: int = 100)
```

计算数据覆盖率和完整性，用户上传与 API 获取结果合并评分。

#### 3. analyze_accessibility

```python
@tool
def analyze_accessibility(
    analysis_type: str = "driving_accessibility",  # driving/walking/service_coverage/poi_coverage/isochrone
    origin: Optional[list] = None,
    destinations: Optional[list] = None,
    center: Optional[list] = None,
)
```

可达性分析，基于天地图真实路网。

#### 4. search_poi

```python
@tool
def search_poi(keyword: str, center: list, radius: int = 1000, page_size: int = 20)
```

POI 搜索（高德优先），返回 POI 列表 + GeoJSON 点图层。

### 布局规划工具（8 个）

#### 5. parse_planning_text

```python
@tool
def parse_planning_text(
    reports: Annotated[Dict, InjectedState("reports")],
    village_name: Annotated[str, InjectedState("village_name")],
    gis_data: Annotated[Optional[Dict], InjectedState("gis_data")] = None,
)
```

从规划报告解析空间布局意图。两层架构：指标锚点（metric anchors）+ Instructor 结构化输出。

**输出**: `UnifiedSpatialIntent`（zones、facilities、axes、constraints）

#### 6. build_knowledge_graph

```python
@tool
def build_knowledge_graph(
    reports: Annotated[Dict, InjectedState("reports")],
    gis_data: Annotated[Dict, InjectedState("gis_data")],
    village_name: Annotated[str, InjectedState("village_name")],
)
```

构建规划知识图谱（调用一次）。后续工具通过 `kg_turtle` 持久化状态复用 KG。

**输出**: `kg_turtle`（Turtle 序列化）+ `kg_constraints`（提取的约束列表）

#### 7. query_knowledge_graph

```python
@tool
def query_knowledge_graph(
    template_name: str,   # 查询模板名
    field_name: str = "", dlbm: str = "", zone_type: str = "",
    kg_turtle: Annotated[str, InjectedState("kg_turtle")] = "",
)
```

查询约束/指标/地块。12 个查询模板：

| 模板 | 说明 |
|------|------|
| `get_constraints` | 所有约束 |
| `get_constraint_by_field` | 按字段查约束（construction/farmland/ecological） |
| `get_parcels_by_dlbm` | 按 DLBM 查地块 |
| `get_parcels_by_zone_type` | 按分区类型查地块 |
| `count_by_zone_type` | 各分区地块统计 |
| `get_zone_restrictions` | 分区限制规则 |
| `get_indicators` | 规划指标 |
| `check_protected_parcels` | 受保护地块 |
| `get_adjacent_parcels` | 相邻地块 |

#### 8. detect_conflicts

```python
@tool
def detect_conflicts(
    summaries: Annotated[Dict, InjectedState("summaries")],
)
```

检测维度间指标冲突 + 约束违反。输出冲突计数和消解结果。

#### 9. allocate_zones

```python
@tool
def allocate_zones(
    targets: dict,
    constraints: list,
    mode: str = "greedy",  # "greedy" | "mip"
    gis_data: Annotated[Dict, InjectedState("gis_data")] = None,
    kg_constraints: Annotated[List[Dict], InjectedState("kg_constraints")] = None,
    kg_turtle: Annotated[str, InjectedState("kg_turtle")] = "",
)
```

分配功能分区。`greedy` 模式使用 ConstraintDrivenAllocator，`mip` 模式使用 MIPZoneAllocator。

**输出**: `allocated_geojson` + 变更地块数

#### 10. generate_layout

```python
@tool
def generate_layout(
    intent: dict,   # parse_planning_text 的输出
    gis_data: Annotated[Dict, InjectedState("gis_data")] = None,
    kg_constraints: Annotated[List[Dict], InjectedState("kg_constraints")] = None,
)
```

生成多图层空间布局，6 层 GeoJSON 通过 `_emit_layer_update()` 增量推送。

**输出**: `layout_configs` 列表

#### 11. validate_layout

```python
@tool
def validate_layout(
    layout_configs: list,
    constraints: list,
    auto_retry: bool = True,   # 自动重试（最多 3 次）
)
```

验证面积约束 + 完整性 + 几何有效性。失败时生成调整建议。

**输出**: ValidationReport 或重试建议

#### 12. measure_divergence

```python
@tool
def measure_divergence(
    current_geojson: str,    # 现状用地
    planned_geojson: str,    # 规划用地
)
```

量化现状与规划布局的偏差：面积差异、变化率、紧凑度指数（等周商）。

---

## 规划知识图谱

### 本体定义

```python
# backend/app/services/modules/gis/layout/kg/ontology.py
```

**16 实体类型**：

| 阶段 | 实体 | 说明 |
|------|------|------|
| Phase 0 | `Parcel` | 地块（DLBM 编码） |
| Phase 0 | `Zone` | 分区 |
| Phase 0 | `Constraint` | 约束条件 |
| Phase 0 | `Indicator` | 规划指标 |
| Phase 1 | `Project` | 建设项目 |
| Phase 1 | `Village` | 村庄 |
| Phase 1 | `Regulation` | 法规（由 Constraint 转化） |
| Phase 1 | `LandUsePlan` | 用地规划 |
| Phase 1 | `Facility` | 设施 |
| Phase 1 | `Axis` | 发展轴 |
| Phase 1 | `Road` | 道路 |
| Phase 1 | `WaterBody` | 水体 |
| Phase 1 | `BuildingGroup` | 建筑群 |
| Phase 2 | `LandConservationPlan` | 土地整治规划 |
| Phase 2 | `ReforestationPlan` | 退耕还林规划 |
| Phase 2 | `GridRegulation` | 网格管控 |

**11 关系类型**：

| 关系 | 说明 |
|------|------|
| `adjacent_to` | 空间邻接 |
| `within_zone` | 属于分区 |
| `constrained_by` | 受约束 |
| `designated_as` | 规划用途指定 |
| `protects` | 保护关系 |
| `located_in` | 位于 |
| `achieves` | 达成指标 |
| `conflicts_with` | 冲突 |
| `derived_from` | 派生自 |
| `serves` | 服务 |
| `connects` | 连接 |

### 10 阶段构建流程

```python
# backend/app/services/modules/gis/layout/kg/builder.py
class PlanningKG:
    def build_from_reports(self, reports, landuse_geojson=None, ...) -> PlanningKG:
        """One-click KG build: 10-stage pipeline"""
```

| 阶段 | 方法 | 说明 |
|------|------|------|
| 1 | `_compute_zone_areas_from_gis` | 从 GIS 数据计算分区面积（dissolve by zone_type → 投影到 metric CRS） |
| 2 | `_add_parcels` | 添加地块实体（composite key: BSM_DLBM_Area） |
| 3 | `_add_constraints` | 提取约束（construction_cap、farmland_min、ecological_min 等） |
| 4 | `_add_indicators` | 添加规划指标（人口、人均建设用地、村民收入等） |
| 5 | `_add_zones` | 添加分区定义 |
| 6 | `_add_spatial_relations` | 构建邻接图（spatial join，10m 阈值） |
| 7 | `_add_projects` | 提取项目实体（正则匹配报告文本） |
| 8 | `_add_regulations` | Constraint → Regulation 转化（农田保护、生态红线、村庄边界） |
| 9 | `_add_designated_as_relations` | 添加 designated_as: parcel → planning zone 映射 |
| 10 | `_add_spatial_infrastructure` | 添加设施/道路/水体实体（DLBM 分类） |

### 约束提取模式

```python
CONSTRAINT_PATTERNS = [
    {"metric_key": "建设用地规模_公顷",     "constraint_id": "construction_cap",       "operator": "<="},
    {"metric_key": "耕地保有量_公顷",       "constraint_id": "farmland_min",           "operator": ">="},
    {"metric_key": "永久基本农田_公顷",     "constraint_id": "permanent_farmland_min", "operator": ">="},
    {"metric_key": "生态保护红线面积",      "constraint_id": "ecological_redline_min", "operator": ">="},
    {"metric_key": "森林覆盖率_百分比",     "constraint_id": "forest_coverage_min",    "operator": ">="},
]
```

### Turtle 序列化

KG 通过 `kg_turtle` 字段在 ReAct 工具调用间持久化：

```
build_knowledge_graph() → 生成 kg_turtle
    │
    ▼  写入 GISAgentState.kg_turtle
query_knowledge_graph() → 读取 kg_turtle → 反序列化 → SPARQL 查询
    │
    ▼  复用同一 KG 实例
allocate_zones() → 读取 kg_constraints → 约束注入 MIP
```

---

## 分区分配器

### 双分类体系

系统使用两套正交的分类体系，**不可混用**：

| 体系 | 映射 | 类别数 | 用途 |
|------|------|--------|------|
| 功能区 | `DLBM_TO_ZONE_TYPE` | 7 类 | `function_zone` 图层渲染 |
| 规划分区 | `DLBM_TO_PLANNING_ZONE` | 4 区 | `planning_zone` 图层 + MIP 约束 |

**7 类功能区**：农业用地、生态绿地、居住用地、产业用地、公共服务用地、商业用地、交通用地、水域

**4 类规划分区**：农田保护区、生态保护区、村庄建设区、一般农业区

**7→4 映射**（多对一）：

```python
# backend/app/services/modules/gis/layout/planning_zone_mapper.py
ZONE_TYPE_TO_PLANNING_ZONE = {
    "居住用地": "村庄建设区",
    "产业用地": "村庄建设区",
    "公共服务用地": "村庄建设区",
    "交通用地": "村庄建设区",
    "商业用地": "村庄建设区",
    "生态绿地": "生态保护区",
    "水域": "生态保护区",
    # 农业用地 → 农田保护区 或 一般农业区（取决于 DLBM）
}
```

### GB/T 21010 国标

```python
# backend/app/services/modules/gis/layout/zone_schema.py
```

**DLBM 代码集**：

| 代码集 | 代码 | 说明 |
|--------|------|------|
| `BASIC_FARMLAND_CODES` | 0101, 0102, 0103, 0110, 0120, 0130, 1100 | 永久基本农田 |
| `GENERAL_AGRICULTURE_CODES` | 0100, 0200, 1200, 1510, 3200 | 一般农地 |
| `PROTECTED_DLBM_CODES` | 以上两集 + 生态代码 | 所有保护性地块 |

### 国标色卡

```python
# 功能区配色（与前端 PLANNING_COLORS.function_zone 同步）
ZONE_TYPE_COLORS = {
    "农业用地":     {"fill": "#F5F8DC", "stroke": "#8B7355"},
    "生态绿地":     {"fill": "#68B167", "stroke": "#2E8B57"},
    "居住用地":     {"fill": "#FFD380", "stroke": "#B8860B"},
    "商业用地":     {"fill": "#FF0000", "stroke": "#CC0000"},
    "产业用地":     {"fill": "#BB9674", "stroke": "#8B6914"},
    "公共服务用地": {"fill": "#4A90D9", "stroke": "#1E3A5F"},
    "交通用地":     {"fill": "#0000FF", "stroke": "#0066CC"},
    "水域":         {"fill": "#87CEEB", "stroke": "#4169E1"},
}

# 规划分区配色（与前端 PLANNING_COLORS.planning_zone 同步）
PLANNING_ZONE_COLORS = {
    "农田保护区": "#FFE4B5",
    "村庄建设区": "#FF6347",
    "生态保护区": "#2E8B57",
    "一般农业区": "#98FB98",
}
```

### ConstraintDrivenAllocator（贪心模式）

```python
# backend/app/services/modules/gis/layout/optimizer/mip_solver.py
class ConstraintDrivenAllocator:
    def solve(self, landuse_geojson, targets, constraints, kg, mode="greedy", ...) -> Tuple[GeoJSON, Dict]:
        """3 步贪心分配"""
```

**3 步流程**：

1. `_greedy_alloc(parcel_db, targets)` — 按 DLBM 偏好分配，保护区优先，允许 5% 超额
2. `_enforce_constraint(parcel_db, targets)` — 重新分配违反约束的地块
3. `_fill_unassigned(parcel_db, targets)` — 填充剩余未分配地块

**偏好成本矩阵**：

```python
def _preference_cost(self, dlbm: str, zone_type: str) -> float:
    """0=首选, 5=同类, 10-15=跨类, 1000=禁止"""
```

### MIPZoneAllocator（MIP 模式）

```python
# backend/app/services/modules/gis/layout/optimizer/mip_allocator.py
class MIPZoneAllocator:
    def solve(self, landuse_geojson, targets, constraints, kg=None, ...) -> Tuple[GeoJSON, MIPTrace]:
        """PuLP 二值变量求解"""
```

**MIP 模型**：

```
变量: x[i][z] ∈ {0,1}  (地块 i → 分区 z)
      dev_pos[z] ≥ 0, dev_neg[z] ≥ 0  (偏差松弛)

硬约束:
  C1: Σ_z x[i][z] = 1                    (每地块恰好分配一次)
  C2: Σ_i area[i]·x[i][z] - target[z] = dev_pos[z] - dev_neg[z]

软约束 (KG-driven, 带松弛变量):
  - 建设用地上限: Σ 村庄建设区 ≤ limit + slack
  - 耕地保有量下限: Σ 农田+一般农业 ≥ limit - slack
  - 生态保护区下限: Σ 生态保护区 ≥ limit - slack

目标函数:
  min AREA_WEIGHT·Σ(dev_pos + dev_neg)
    + Σ_kg SLACK_kg
    + Σ_x PREFERENCE_COST(i,z)
    + CHANGE_PENALTY·#changed_parcels
```

**跨分区成本**：

```python
CROSS_ZONE_COST = {
    ("农田保护区", "一般农业区"): 3,   # 同属农业空间
    ("生态保护区", "一般农业区"): 5,   # 生态-农业过渡
    ("农田保护区", "生态保护区"): 10,  # 农业-生态跨类
    ("村庄建设区", "一般农业区"): 30,  # 建设-农业跨类
    ("村庄建设区", "农田保护区"): 40,  # 建设-农田严重跨类
    ("村庄建设区", "生态保护区"): 50,  # 建设-生态最严重
}
```

### AdjacencyGraph

```python
# backend/app/services/modules/gis/layout/optimizer/adjacency_graph.py
class AdjacencyGraph:
    def __init__(self, parcel_db, max_distance_m=30.0):
        """Shapely STRtree 构建 O(1) 邻居查询"""

    def get_neighbors(self, parcel_key) -> Set[str]
    def get_adjacent_pairs(self) -> List[Tuple[str, str]]
    def to_index_pairs(self) -> List[Tuple[int, int]]  # MIP 辅助变量
```

### ZoneCARefiner

```python
# backend/app/services/modules/gis/layout/optimizer/ca_refiner.py
class ZoneCARefiner:
    def __init__(self, merge_distance_m=30.0, simplify_tolerance_m=10.0,
                 iterations=3, min_area_ha=0.5):
        """Cellular Automata 风格空间精炼"""

    def refine(self, features) -> List[Dict]:
        """buffer → union → debuffer，重复 iterations 轮消除碎片"""
```

---

## 验证与精炼

### LayoutValidator

```python
# backend/app/services/modules/gis/layout/validator.py
class LayoutValidator:
    def validate(self, layout_configs, constraints=None, adjacency_graph=None) -> ValidationReport:
        """8 项空间有效性检查"""

    def validate_with_retry(self, layout_configs, constraints=None, max_retries=3) -> RetryValidationReport:
        """验证 + 失败时生成调整建议"""
```

### 8 项空间检查

| # | 检查项 | 方法 | 规则 |
|---|--------|------|------|
| 1 | 面积约束 | `_check_area_constraints` | 建设用地 ≤ 上限，农田 ≥ 下限，生态 ≥ 下限 |
| 2 | 分区完整性 | `_check_zone_completeness` | 必须包含村庄建设区、生态保护区、一般农业区 |
| 3 | 几何重叠 | `_check_overlap` | Shapely STRtree 检测同层重叠 |
| 4 | 保护性地块 | `_check_protected_parcels` | DLBM 0110/0120/0130/1340/1350 不在建设区 |
| 5 | 最小分区面积 | `_check_min_zone_area` | 农田保护区 ≥ 1.0ha，村庄建设区 ≥ 0.5ha，生态保护区 ≥ 1.0ha，一般农业区 ≥ 5.0ha |
| 6 | GeoJSON 结构 | `_check_geojson_structural` | RFC 7946：type、features 数组、geometry type、坐标范围 |
| 7 | 邻接兼容性 | `_check_adjacency_compatibility` | 同类邻居率 ≥ 30%（村庄尺度允许碎片化） |
| 8 | 空间紧凑度 | `_check_spatial_compactness` | Compactness = 1/(1+CV) ≥ 0.5，CV = std/mean of parcel areas |

### 验证循环

```
validate_layout(layout_configs, constraints)
    │
    ├── pass → 返回 ValidationReport(status="pass")
    │
    └── fail → 生成调整建议（damping=0.2）
        │
        ├── 调整 targets → allocate_zones → generate_layout → validate_layout
        │   (最多 3 轮)
        │
        └── 3 轮后仍失败 → 返回最佳结果 + 标注未满足约束
```

### PipelineTrace

```python
# backend/app/services/modules/gis/layout/trace.py
class PipelineTrace(BaseModel):
    parse: Optional[ParseTrace] = None          # LLM 解析
    kg: Optional[KGTrace] = None                # 知识图谱构建
    conflicts: Optional[ConflictTrace] = None   # 冲突检测/消解
    mip: Optional[MIPTrace] = None              # MIP 求解器
    validation: Optional[ValidationLoopTrace] = None  # 验证循环
    total_timing_ms: int = 0
```

| 子追踪 | 关键字段 |
|--------|---------|
| `ParseTrace` | source, llm_model, anchor_confidence, semantic_validation_passed |
| `KGTrace` | parcel_count, triple_count, constraint_count, adjacency_edge_count |
| `ConflictTrace` | metric_conflicts, constraint_violations, resolution_applied |
| `MIPTrace` | mode, solver_status, variable_count, zone_targets, zone_actual, zone_deviations, kg_slack_values, changed_pct |
| `ValidationLoopTrace` | rounds[], final_status |

---

## SSE 数据流转

### 维度分析 SSE 事件

#### dimension_complete

维度分析完成时推送 GIS 数据：

```json
{
  "type": "dimension_complete",
  "dimension_key": "natural_environment",
  "gis_data": {
    "layers": [
      {
        "geojson": {"type": "FeatureCollection", "features": [...]},
        "layerType": "water",
        "layerName": "水系",
        "source": "user_upload"
      }
    ],
    "mapOptions": {
      "center": [116.04, 24.82],
      "zoom": 14
    }
  }
}
```

### GIS 布局 SSE 事件

#### gis_result

布局生成完成时推送完整结果：

```json
{
  "type": "gis_result",
  "dimensionKey": "spatial_structure",
  "dimensionName": "空间结构规划",
  "summary": "生成 6 层布局，4 个规划分区...",
  "layers": [
    {
      "geojson": {"type": "FeatureCollection", "features": [...]},
      "layerType": "planning_zone",
      "layerName": "规划分区"
    }
  ],
  "mapOptions": {
    "center": [116.04, 24.82],
    "zoom": 14
  },
  "analysisData": {
    "overallScore": 85,
    "suitabilityLevel": "适宜",
    "sensitivityClass": "低敏感",
    "recommendations": ["建议增加公共服务设施覆盖"]
  },
  "pipeline_trace": {
    "kg": {"parcel_count": 660, "triple_count": 3200, "constraint_count": 5},
    "mip": {"mode": "KG-driven", "solver_status": "Optimal", "changed_pct": 12.3},
    "validation": {"rounds": [{"round_number": 1, "total_violations": 0}], "final_status": "pass"}
  }
}
```

#### gis_layer_update

增量图层推送（逐层推送，避免单次 6.5MB 大包）：

```json
{
  "type": "gis_layer_update",
  "layer": 3,
  "dimensionKey": "spatial_structure",
  "layers": [
    {
      "geojson": {"type": "FeatureCollection", "features": [...]},
      "layerType": "planning_zone",
      "layerName": "规划分区"
    }
  ]
}
```

**增量推送机制**：`SpatialLayoutEngine._emit_layer_update()` 每生成一层即推送，将 6.5MB 单包拆分为 0.5-1.5MB 增量包。

#### tool_progress

工具执行进度：

```json
{
  "type": "tool_progress",
  "tool_name": "allocate_zones",
  "stage": "processing",
  "progress": 0.6,
  "message": "MIP 求解中..."
}
```

**stage 类型**：`initializing`、`processing`、`finalizing`

### SSE 发布方法

```python
# backend/app/utils/sse_publisher.py
class SSEPublisher:
    @staticmethod
    def send_gis_result(session_id, dimension_key, dimension_name, summary,
                        layers, map_options=None, analysis_data=None,
                        pipeline_trace=None)

    @staticmethod
    def send_gis_layer_update(session_id, layer, dimension_key, dimension_name,
                              layers, map_options=None, analysis_data=None)

    @staticmethod
    def send_tool_progress(session_id, tool_name, stage, progress, message)
```

---

## 前端可视化

### MapView 组件

```typescript
// frontend/src/features/planning/components/gis/MapView.tsx
interface MapViewProps {
  layers: GISLayerConfig[];
  center?: [number, number];        // [longitude, latitude] GeoJSON 标准
  zoom?: number;
  height?: string;
  title?: string;
  baseMapType?: BaseMapType;        // 'vector' | 'image' | 'terrain'
  showLegend?: boolean;
  legendPosition?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
  visibleLayerTypes?: Set<LayerType>;
}
```

**图层渲染优先级**：

```typescript
const LAYER_PRIORITY: Record<string, number> = {
  'boundary': 0,          // 最底层
  'infrastructure': 1,
  'sensitivity_zone': 2,
  'function_zone': 3,
  'planning_zone': 4,
  'isochrone': 5,
  'development_axis': 6,
  'facility_point': 7,    // 最顶层
};
```

**瓦片源**：天地图矢量/影像/地形、GeoQ、OpenStreetMap

**交互功能**：要素点击 popup（显示属性，排除 `_` 前缀内部字段）、自动 fitBounds（优先村庄边界）

### PLANNING_COLORS

```typescript
// frontend/src/features/planning/constants/gis.ts
// 与后端 zone_schema.py 同步
export const PLANNING_COLORS = {
  boundary: { '行政边界': { stroke: '#333333', width: 2 } },
  function_zone: {
    '农业用地': { fill: '#F5F8DC', stroke: '#8B7355' },
    '生态绿地': { fill: '#68B167', stroke: '#2E8B57' },
    '居住用地': { fill: '#FFD380', stroke: '#B8860B' },
    // ... 9 类功能区
  },
  planning_zone: {
    '农田保护区': { fill: '#FFE4B5', stroke: '#DAA520' },
    '村庄建设区': { fill: '#FF6347', stroke: '#CC4F39' },
    '生态保护区': { fill: '#2E8B57', stroke: '#1B5E20' },
    '一般农业区': { fill: '#98FB98', stroke: '#66CD66' },
  },
  facility_point: { ... },    // 设施点（按状态着色）
  development_axis: { ... },  // 发展轴
  sensitivity_zone: { ... },  // 敏感区
  isochrone: { ... },         // 等时圈
  settlement_zone: { ... },   // 居民点分类
  infrastructure: { ... },    // 基础设施
};
```

### LAYER_TYPE_LABELS

```typescript
export const LAYER_TYPE_LABELS: Record<LayerType, string> = {
  boundary: '行政边界',
  function_zone: '功能区',
  facility_point: '设施点',
  sensitivity_zone: '敏感区',
  infrastructure: '基础设施',
  isochrone: '等时圈',
  planning_zone: '规划分区',
  development_axis: '发展轴',
  settlement_zone: '居民点分类',
};
```

### GisUploadButton

```typescript
// frontend/src/features/planning/components/layout/ProcessPanel.tsx
function GisUploadButton({ uploading, onClick, size = 'sm' })
```

上传流程：选择文件 → `planningApi.uploadGisData(sessionId, file)` → 获取状态 → `store.addGisLayersFromUpload(configs)`

### GIS 状态字段

```typescript
// frontend/src/features/planning/store/planningStore.ts
interface PlanningState {
  // GIS 图层（SSE 驱动）
  gisLayers: Record<string, GISLayerConfig[]>;  // { layerKey: [layerConfig] }

  // 管线追踪
  pipelineTrace: PipelineTrace | null;

  // 生成状态
  gisGenerating: boolean;       // GIS 正在生成
  isFullMapOpen: boolean;       // 全屏地图
  gisTriggerPending: boolean;   // GIS 触发待执行
  villageCenter?: [number, number];  // 村庄中心坐标
}
```

**SSE 事件处理**：

| 事件 | Store 动作 |
|------|-----------|
| `gis_result` | 填充 `gisLayers[layerKey]` + 创建 GisResultMessage |
| `gis_layer_update` | 增量更新 `gisLayers` + 自动激活地图标签页 |

---

## 诊断与调试

### 测试端点（开发环境）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dev/gis/test/spatial-layout` | POST | 测试空间布局生成 |
| `/api/dev/gis/test/boundary-fallback` | POST | 测试边界兜底机制 |

### 常见问题排查

#### 用户上传数据不生效

1. 检查 `GISDataManager.get_data_status(village_name)` 返回值
2. 确认 `user_uploaded` 列表包含预期数据类型
3. 检查上传时 `infer_data_type()` 推断结果

#### 边界生成失败

1. 查看边界生成结果的 `fallback_history` 字段
2. 检查各策略失败原因（`reason` 字段）
3. 确认村庄中心点已正确计算

#### 布局生成失败

1. 检查 `pipelineTrace.parse` — LLM 解析是否成功
2. 检查 `pipelineTrace.kg` — KG 构建 triple_count > 0
3. 检查 `pipelineTrace.mip` — solver_status 是否 "Optimal"
4. 检查 `pipelineTrace.validation` — 哪轮失败、哪些 violations

#### 地图显示灰色

1. 检查瓦片服务配置（`NEXT_PUBLIC_TILE_SOURCE`）
2. 检查天地图密钥域名白名单
3. 检查浏览器网络请求

---

## 关键文件路径

| 功能 | 后端路径 | 前端路径 |
|------|----------|----------|
| **布局引擎** | | |
| SpatialLayoutEngine | `backend/app/services/modules/gis/layout/engine.py` | - |
| 规划知识图谱 | `backend/app/services/modules/gis/layout/kg/builder.py` | - |
| KG 本体定义 | `backend/app/services/modules/gis/layout/kg/ontology.py` | - |
| MIP 分配器 | `backend/app/services/modules/gis/layout/optimizer/mip_allocator.py` | - |
| 贪心分配器 | `backend/app/services/modules/gis/layout/optimizer/mip_solver.py` | - |
| 邻接图 | `backend/app/services/modules/gis/layout/optimizer/adjacency_graph.py` | - |
| CA 精炼 | `backend/app/services/modules/gis/layout/optimizer/ca_refiner.py` | - |
| GB/T 21010 常量 | `backend/app/services/modules/gis/layout/zone_schema.py` | - |
| 7→4 映射 | `backend/app/services/modules/gis/layout/planning_zone_mapper.py` | - |
| 验证器 | `backend/app/services/modules/gis/layout/validator.py` | - |
| 管线追踪 | `backend/app/services/modules/gis/layout/trace.py` | - |
| 意图模型 | `backend/app/services/modules/gis/layout/planning_intent.py` | - |
| 冲突检测 | `backend/app/services/modules/gis/layout/conflict_detector.py` | - |
| 冲突消解 | `backend/app/services/modules/gis/layout/conflict_resolver.py` | - |
| 分区生成 | `backend/app/services/modules/gis/layout/zone_generator.py` | - |
| GeoJSON 渲染 | `backend/app/services/modules/gis/layout/map_renderer.py` | - |
| 设施放置 | `backend/app/services/modules/gis/layout/facility_placer.py` | - |
| 轴线构建 | `backend/app/services/modules/gis/layout/axis_builder.py` | - |
| **GIS Agent** | | |
| Agent 图 | `backend/app/agent/gis/graph.py` | - |
| Agent 状态 | `backend/app/agent/gis/state.py` | - |
| Agent 提示 | `backend/app/agent/gis/prompts.py` | - |
| 布局工具 | `backend/app/tools/gis/layout_tools.py` | - |
| 数据工具 | `backend/app/tools/gis/data_tools.py` | - |
| **数据服务** | | |
| GIS 服务门面 | `backend/app/services/modules/gis/service.py` | - |
| GIS 数据获取 | `backend/app/services/modules/gis/fetcher.py` | - |
| 覆盖率计算 | `backend/app/services/modules/gis/coverage.py` | - |
| 可达性分析 | `backend/app/services/modules/gis/accessibility.py` | - |
| 高德 API | `backend/app/services/modules/gis/providers/amap/provider.py` | - |
| 天地图 API | `backend/app/services/modules/gis/providers/tianditu/provider.py` | - |
| 天地图 WFS | `backend/app/services/modules/gis/providers/tianditu/wfs.py` | - |
| OSM 道路 | `backend/app/services/modules/gis/providers/osm/provider.py` | - |
| 坐标转换 | `backend/app/services/modules/gis/utils/coord_utils.py` | - |
| SSE 发布 | `backend/app/utils/sse_publisher.py` | - |
| **前端** | | |
| 地图渲染 | - | `frontend/src/features/planning/components/gis/MapView.tsx` |
| GIS 上传 | - | `frontend/src/features/planning/components/layout/ProcessPanel.tsx` |
| 前端状态 | - | `frontend/src/features/planning/store/planningStore.ts` |
| GIS 常量 | - | `frontend/src/features/planning/constants/gis.ts` |
| API 客户端 | - | `frontend/src/features/planning/api/data-api.ts` |

---

## 相关文档

- [02-agent-core](./02-agent-core.md) - gis_agent 节点与主图集成
- [06-tool-system](./06-tool-system.md) - 工具注册与执行
- [04-backend-api](./04-backend-api.md) - SSE 事件类型
- [05-frontend-state](./05-frontend-state.md) - 前端状态管理
- [terminology](./terminology.md) - 术语定义
- [file-index](./file-index.md) - 文件路径索引
