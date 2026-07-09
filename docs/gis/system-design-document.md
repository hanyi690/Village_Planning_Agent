
# GIS 系统完整设计文档与架构思路

## Context

基于当前 Village_Planning_Agent GIS 系统的完整实现分析，结合 Exa 搜索的行业参考（ChatGeoAI、GIS Copilot、Bhuvan Panchayat、NLMapper 等），生成一份完整的设计文档，明确系统定位、架构决策、数据流、技术选型依据和改进方向。

---

## 一、系统概述

### 1.1 定位

Village_Planning_Agent GIS 系统是一个**声明式意图驱动的村庄规划空间生成引擎**，采用 Trinity 三层架构（Planning KG + Agentic Pipeline + Spatial Generator），将自然语言规划报告转化为可解释、可验证的 GeoJSON 图层输出。

### 1.2 核心价值

| 维度               | 传统 GIS 问题          | 本系统解决方案                          |
| ------------------ | ---------------------- | --------------------------------------- |
| **可解释性** | "规划图=现状图换色"    | 声明式意图(ZoneIntent) + ReAct 推理轨迹 |
| **约束保证** | 规划法规仅自然语言陈述 | KG + MIP 优化，硬约束 100% 满足         |
| **空间推理** | centroid 近似定位      | KG 空间邻接图 + MIP 逆向规划            |
| **迭代优化** | 单向 pipeline，无反馈  | 验证-重优化循环                         |
| **国产化**   | ArcGIS 需要 Linux      | MapLibre GL + 天地图 + MIP 全栈国产     |

### 1.3 技术栈

```
后端:   FastAPI + LangGraph 1.2 + RDFLib (KG) + PuLP (MIP) + Shapely/GeoPandas
前端:   Next.js 14 + React 18 + TypeScript + Zustand + MapLibre GL
数据:   SQLite + 天地图 WFS + 高德 GCJ-02 + OSMnx 2.x
连接:   SSE Server-Sent Events (增量流式)
```

---

## 二、架构总览

### 2.1 Trinity 三层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                   LAYER 1: PLANNING KNOWLEDGE GRAPH             │
│                   (规划知识图谱 - 规则约束引擎)                   │
│                                                                 │
│  ontology.py  → OWL 本体定义 (entity_types + relation_types)    │
│  builder.py   → Report + GeoJSON → RDF 三元组 (660 parcels)     │
│  query.py     → 9 个 SPARQL 查询模板 (约束/面积/邻接)           │
│                                                                 │
│  输出: kg_constraints → 注入 Layer 2 + Layer 3                   │
└────────────────────────────┬────────────────────────────────────┘
                             │ Turtle 序列化 + InjectedState
┌────────────────────────────▼────────────────────────────────────┐
│                   LAYER 2: AGENTIC PIPELINE                     │
│                   (智能体管道 - 推理决策引擎)                     │
│                                                                 │
│  LLM Planner (GPT-4o/DeepSeek) → ReAct 循环编排                 │
│  6 个 LangGraph 工具:                                           │
│    1. build_knowledge_graph()  — 构建 KG                        │
│    2. query_knowledge_graph()  — SPARQL 查询                   │
│    3. detect_conflicts()       — 冲突检测                       │
│    4. allocate_zones()         — 约束分配 (MIP/Greedy)          │
│    5. generate_layout()        — 布局生成 + 渲染                │
│    6. validate_layout()        — 8项验证                        │
│  InjectedState 模式: kg_turtle/gis_data → LLM 不可见            │
└────────────────────────────┬────────────────────────────────────┘
                             │ Command(update={messages: ToolMessage})
┌────────────────────────────▼────────────────────────────────────┐
│                   LAYER 3: SPATIAL GENERATOR                    │
│                   (空间生成器 - 几何引擎)                         │
│                                                                 │
│  Phase 0: ConflictDetector + ConflictResolver                   │
│  Phase 1: ZoneGenerator + ConstraintDrivenAllocator             │
│           + FacilityPlacer + AxisBuilder + MapRenderer           │
│  Phase 2: MipSolver + CARefiner + AdjacencyGraph                │
│                                                                 │
│  输出 7 种图层: boundary, function_zone, planning_zone,          │
│    sensitivity_zone, infrastructure, facility_point,             │
│    development_axis                                             │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 数据提供者层

```
天地图 (tianditu/): WFS 矢量 + 组合瓦片 (矢量/影像/地形)
高德   (amap/):     GCJ-02 → WGS-84 转换, POI 搜索 + 逆地理编码
OSM    (osm/):      村级道路补充, OSMnx 2.x (bbox: west,south,east,north)
```

### 2.3 前端架构

```
SSE → useSSE (30ms批量) → planningStore.gisLayers → useGisLayers() → MapView
                                                    → useGisLayersByType() → LegendPanel
                                                    → ValidationPanel
```

---

## 三、核心设计思路

### 3.1 声明式意图驱动 vs 命令式几何生成

**关键决策**: 采用 `UnifiedSpatialIntent` 作为规划文本与几何生成之间的语义桥梁。

| 维度     | 命令式 (传统 GIS) | 声明式意图 (本系统)                                         |
| -------- | ----------------- | ----------------------------------------------------------- |
| 输入     | CAD 坐标/参数     | 自然语言规划报告                                            |
| 中间层   | 无                | UnifiedSpatialIntent (ZoneIntent/FacilityIntent/AxisIntent) |
| 可解释性 | 黑盒              | LLM 可追溯每步决策                                          |
| 约束保证 | 后处理验证        | MIP 前置保证硬约束                                          |
| 扩展性   | 功能叠加难        | Tool Chain 扁平扩展                                         |

**现有实现** (`layout/planning_intent.py`):

- `ZoneIntent`: land_use, dlbm, area_ratio, direction, adjacent_to, density
- `FacilityIntent`: 设施点选址意图
- `AxisIntent`: 发展轴线意图
- `ConstraintIntent`: 约束意图
- `Direction` 枚举: CENTER/NORTH/SOUTH/EAST/WEST/PERIPHERY
- `Density` 枚举: HIGH/MEDIUM/LOW

**参考**: ChatGeoAI (西班牙) 采用 NER → GeoKG 语义映射 → LLM 规划 → Code 执行 → 可视化，与本系统的 Report → Intent → KG → MIP → GeoJSON 路径一致。

### 3.2 知识图谱约束注入

**关键决策**: 使用 RDF/SPARQL 知询而非向量数据库做结构化约束存储。

| 需求         | KG (RDF/SPARQL)            | 向量DB (Chroma)        |
| ------------ | -------------------------- | ---------------------- |
| 精确约束查询 | SPARQL FILTER → 100% 精确 | 语义相似 → 可能误命中 |
| 空间拓扑推理 | 显式边关系                 | 无图结构               |
| 法规追溯     | source_report 边           | 无元数据               |
| LLM 工具调用 | query_kg(sparql)           | semantic_search(query) |

**结论**: KG 做结构化规则存储和精确推理，向量DB 做报告文本语义搜索 → **互补而非替代**。

**现有实现** (`layout/kg/`):

- `ontology.py`: OWL 本体定义 (7 种实体类型 + 9 种关系类型)
- `builder.py`: Report + GeoJSON → RDF 三元组
- `query.py`: 9 个 SPARQL 查询模板

**参考**: GIS Copilot 多智能体架构（意图理解→数据消化→工具选择→代码生成→执行反馈），与本系统 KG + ReAct Pipeline 架构一致。

### 3.3 MIP 优化 + CA 冲突消解双层策略

**关键决策**: MIP 求解器保证硬约束，CA 做几何精细化。

| 问题     | LLM 直接生成               | MIP 优化求解器                        |
| -------- | -------------------------- | ------------------------------------- |
| 幻觉风险 | 可能违规将耕地划为建设用地 | 100% 遵守 DLBM 分配约束               |
| 面积偏差 | 无法保证精确               | 硬约束保证 motive_area ≈ target_area |
| 可重现性 | 每次随机波动               | 相同输入 → 相同输出                  |

**现有实现** (`layout/optimizer/`):

- `mip_allocator.py`: PuLP CBC 求解器，目标 = 面积偏差最小化 + 保持现状偏好 + 空间紧凑性
- `mip_solver.py`: 优化目标函数封装
- `ca_refiner.py`: CA 合并/拆分图斑
- `adjacency_graph.py`: 8 邻域图 + 拓扑验证
- `procedural.py`: 规则化几何工具

**三阶段生成流程**:

1. **Stage A (约束分配)**: MIP 求解 → 每个地块的规划用途
2. **Stage B (空间细化)**: CA 合并/拆分 → 规划图斑几何
3. **Stage C (设施轴线)**: 规则化选址 + 最短路径轴线

**参考**: Exa 搜索中 Monchique (葡萄牙) 生态系统知识图谱系统采用类似的细粒度地块级建模 + 微气候约束集成方案。

### 3.4 SSE 增量流式架构

**关键决策**: 30ms 批量窗口 + 关键事件立即处理 + 增量图层更新。

**SSE 事件类型**:

| 事件                   | 处理方式    | 说明                               |
| ---------------------- | ----------- | ---------------------------------- |
| `gis_result`         | 立即        | 完整图层加载，双态同步 (消息+图层) |
| `gis_layer_update`   | 增量        | 单图层更新，MapView 实时反映       |
| `dimension_delta`    | 批量 (30ms) | 维度增量聚合                       |
| `dimension_complete` | 立即        | 完成事件清空 pending deltas        |
| `tool_start/result`  | 立即        | 工具状态更新                       |

**现有实现**:

- `useSSE.ts` (311行): SSE 连接生命周期 + 批量处理
- `planningStore.ts` (2070行): gisLayers 状态 + 事件处理器
- `MapView.tsx` (607行): MapLibre GL 增量渲染

**参考**: Bhuvan Panchayat (印度) 采用分层架构 + 缓存 + 并行处理，本系统的 SSE 批量窗口是其前端性能优化的轻量级实现。

---

## 四、详细模块设计

### 4.1 后端模块

#### 4.1.1 SpatialLayoutEngine (`layout/engine.py`)

**职责**: 编排完整管线，协调所有子模块

**核心方法**:

- `build_kg(reports, landuse_geojson)` → 构建 PlanningKG
- `detect_and_resolve(summaries)` → Phase 0: 冲突检测+消解
- `generate_layout(intent, gis_context, ...)` → Phase 1-2: 生成 7 种图层
- `_generate_planning_zones(intent, landuse, protection)` → KG 驱动规划分区
- `_refine_planning_zones(planning_zone_geojson)` → MIP + CA 精细化

**数据流**: Intent → ZoneGenerator → ConstraintDrivenAllocator → FacilityPlacer → AxisBuilder → MapRenderer → GISLayerConfig[]

#### 4.1.2 PlanningKG (`layout/kg/`)

**职责**: 从报告+用地数据构建 RDF 知识图谱

**核心方法**:

- `build_from_reports(reports, landuse_geojson)` → 添加地块实体 + 提取约束 + 邻接关系
- `get_constraints()` → 返回约束列表供 MIP 使用
- `query(sparql_str)` → SPARQL 查询
- `to_turtle()` / `from_turtle()` → 序列化/反序列化

#### 4.1.3 Layout Tools (`tools/gis/layout_tools.py`)

**职责**: LangGraph 工具定义，InjectedState + Command 模式

**6 个工具**:

1. `build_knowledge_graph` — 构建 KG
2. `query_knowledge_graph` — SPARQL 查询
3. `detect_conflicts` — 跨维度冲突检测
4. `allocate_zones` — MIP/Greedy 约束分配
5. `generate_layout` — SpatialLayoutEngine 编排
6. `validate_layout` — 8 项验证检查

**13 个空间维度**: spatial_structure, land_use_planning, settlement_planning, public_service, ecological, traffic_planning, infrastructure_planning, industry, heritage, disaster_prevention, landscape, population, natural_environment

#### 4.1.4 Zone Schema (`layout/zone_schema.py`)

**职责**: DLBM/规划分区映射的国标唯一真相源

**核心映射**:

- `DLBM_TO_DLMC`: 地类编码 → 地类名称 (GB/T 21010)
- `DLBM_TO_ZONE_TYPE`: 地类编码 → 渲染分区类型
- `ZONE_TYPE_COLORS`: 分区类型 → GB/T 21010 国标色卡
- `FACILITY_STATUS_COLORS`: 设施状态 → 颜色
- `PLANNING_ZONE_COLORS`: 规划分区 → 颜色

#### 4.1.5 ConflictDetector + ConflictResolver (`layout/`)

**职责**: Phase 0 冲突检测与消解

**检测维度**: 高程/坡度/风险三维冲突
**消解策略**: 优先级消解 (生态 > 农业 > 建设)

#### 4.1.6 验证系统 (`layout/validator.py`)

**职责**: 8 项布局完整性检查

**检查项**: 面积约束满足率、完整性、面积偏差、最小块面积、紧凑度等

### 4.2 前端模块

#### 4.2.1 MapView.tsx (607行)

**Props**: layers: GISLayerConfig[], center, zoom, baseMapType, showLegend

**核心功能**:

- MapLibre GL 渲染 8 种图层类型
- 数据驱动样式: `['get', 'color']` 每要素颜色注入
- 动态底图: 天地图矢量/影像/地形、GeoQ、OSM
- 自适应边界框 + 图层优先级控制

#### 4.2.2 planningStore.ts (2070行)

**GIS 状态**: `gisLayers: Record<string, GISLayerConfig[]>`

**SSE 事件处理**:

- `gis_result` → 双态同步 (GisResultMessage + gisLayers)
- `gis_layer_update` → 增量图层更新
- 30ms 批量窗口聚合 dimension_delta

#### 4.2.3 useSSE.ts (311行)

**职责**: SSE 连接生命周期 + 批量处理

**机制**:

- 关键事件 (gis_result/dimension_complete) 立即处理
- dimension_delta 30ms 窗口批量聚合
- dimension_complete 覆盖清空 pending deltas
- 重连时 syncEvents 拉取遗漏事件

#### 4.2.4 GIS Selectors (`hooks/useSelectors.ts`)

- `useGisLayers()`: 扁平化读取所有图层
- `useGisLayersByType(layerType)`: 按类型过滤
- `useHasGisLayers()`: 存在性检查

#### 4.2.5 LegendPanel.tsx + ValidationPanel.tsx

- LegendPanel: 动态图例，根据活动图层类型生成
- ValidationPanel: 验证结果展示，概览+详情标签页

---

## 五、完整数据流

```
用户输入: "生成金田村规划布局"
        │
        ▼
┌─ INPUT: gis_agent_node ─────────────────────────────────────┐
│  L3 Reports (土地规划章节)                                   │
│  landuse_current.geojson (660 parcels)                      │
│  protection_zones.geojson + traffic.geojson + hazard.geojson│
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─ LAYER 1: build_knowledge_graph() ──────────────────────────┐
│  Report + GeoJSON → RDF 三元组 (660 parcels + 约束 + 邻接)  │
│  → kg_constraints: [{field, operator, value, source}, ...]  │
│  → kg_turtle: 序列化字符串 (InjectedState)                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─ LAYER 2: detect_conflicts() ───────────────────────────────┐
│  跨维度冲突检测 → ConflictReport                             │
│  → ConflictResolver → ResolutionReport                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─ LAYER 2: allocate_zones() ─────────────────────────────────┐
│  mode="mip": PuLP CBC 求解 (~5s), 硬约束保证               │
│  mode="greedy": 快速求解 (~2s)                              │
│  → planning_zone GeoJSON                                    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─ LAYER 3: generate_layout() ────────────────────────────────┐
│  Phase 1:                                                   │
│    ZoneGenerator → function_zone                            │
│    ConstraintDrivenAllocator → planning_zone (MIP 优化)      │
│    FacilityPlacer → facility_point (4种选址策略)            │
│    AxisBuilder → development_axis (一核一带三区)            │
│  Phase 2:                                                   │
│    MipSolver → 面积偏差 < 5%                                │
│    CARefiner → 合并/拆分图斑                                │
│    AdjacencyGraph → 8邻域拓扑验证                           │
│  → GISLayerConfig[] (7 种图层, SSE 增量推送)               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─ LAYER 2: validate_layout() ────────────────────────────────┐
│  8 项检查: 面积约束/完整性/偏差/最小块/紧凑度...            │
│  → LayoutValidationResult (pass/warning/error)              │
└────────────────────────┬────────────────────────────────────┘
                         │ SSE Stream
                         ▼
┌─ FRONTEND: 状态同步 ────────────────────────────────────────┐
│  useSSE → gis_result → planningStore.gisLayers              │
│  gis_layer_update → 增量图层渲染 (30ms 批量)               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─ MapView.tsx ───────────────────────────────────────────────┐
│  GISLayerConfig[] → MapLibre GL Source/Layer                │
│  数据驱动样式 + 动态图例 + 验证面板                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 六、关键技术决策及参考来源

| # | 决策       | 选择                                     | 参考来源                                      |
| - | ---------- | ---------------------------------------- | --------------------------------------------- |
| 1 | 意图模型   | 声明式 UnifiedSpatialIntent              | ChatGeoAI: NER → GeoKG → LLM 规划 → 可视化 |
| 2 | 约束存储   | RDF/SPARQL 知识图谱                      | GIS Copilot: 多智能体 + 工具文档匹配          |
| 3 | 空间优化   | PuLP MIP + CA 双层                       | Monchique: 细粒度地块级建模 + 微气候约束      |
| 4 | 文本→图层 | Report → Intent → KG → MIP → GeoJSON | NLMapper: 结构化提示 + OverpassQL 生成        |
| 5 | 前端渲染   | MapLibre GL + SSE 增量                   | Bhuvan Panchayat: 分层架构 + 缓存 + 并行      |
| 6 | 国标色卡   | GB/T 21010 + 市级制图规范                | GB 50188-2007 镇规划标准                      |
| 7 | 坐标系     | GCJ-02 → WGS-84 (残余<5m)               | 天地图 WFS + 高德 API 实践                    |
| 8 | 批量处理   | 30ms 窗口 + 关键事件立即                 | Web GIS 前端架构: Zustand + 流式更新          |

---

## 七、与行业参考对比

| 维度               | 本系统                        | ChatGeoAI (西班牙)         | GIS Copilot                    | Bhuvan Panchayat (印度)     |
| ------------------ | ----------------------------- | -------------------------- | ------------------------------ | --------------------------- |
| **架构**     | Trinity (KG+Agent+Generator)  | NER→GeoKG→LLM→Code→Viz | 界面识别→工具匹配→代码→调试 | 三级规划层级 (县→联邦→村) |
| **意图模型** | UnifiedSpatialIntent (声明式) | NER 实体提取               | 工具文档匹配                   | MCDM 多因素决策             |
| **约束引擎** | RDF/SPARQL + MIP              | LLM 约束注入               | 代码验证                       | 规则引擎                    |
| **优化方法** | PuLP MIP + CA                 | 无 (LLM 直接生成)          | 无                             | MCDM 评分                   |
| **前端**     | MapLibre GL + SSE             | OpenLayers                 | QGIS 集成                      | Bhuvan 门户                 |
| **可解释性** | ReAct 轨迹 + KG 查询          | LLM 推理链                 | 代码执行日志                   | 决策报告                    |
| **国产化**   | 天地图 + 高德 + GB/T 21010    | OSM + Overpass             | QGIS                           | Bhuvan (ISRO)               |
| **验证**     | 8项自动检查 + 重优化          | 语义验证                   | 单步调试                       | 人工审核                    |

**本系统优势**:

- MIP 硬约束保证 > LLM 直接生成 (ChatGeoAI)
- 声明式意图 > 命令式代码 (GIS Copilot)
- 国产化全栈 > 依赖 QGIS (GIS Copilot)

**本系统差距**:

- 缺少 NER 实体提取 (ChatGeoAI 有 SpaCy NER)
- 缺少 OverpassQL 语义查询 (NLMapper 有)
- 缺少多级规划层级 (Bhuvan 有县→村三级)
- 缺少 MCDM 多因素决策评分 (Bhuvan 有)

---

## 八、改进方向

### 8.1 高优先级

1. **NER 实体提取层**: 在 Report → Intent 之间增加 SpaCy/HuggingFace NER 管线，提取空间实体和关系，减少 LLM 幻觉风险

   - 参考: ChatGeoAI 的 NER → GeoKG 语义映射
2. **OverpassQL 语义查询**: 增加从自然语言生成 OverpassQL 的能力，补充 OSM 数据获取

   - 参考: NLMapper 的结构化提示 + OverpassQL 生成
3. **MCDM 多因素决策评分**: 在设施选址中增加地形/坡度/可达性/服务半径多因素评分

   - 参考: Bhuvan Panchayat 的 MCDM 辅助选址

### 8.2 中优先级

4. **多级规划层级**: 支持县级→乡镇级→村级三级规划上下文传递

   - 参考: Bhuvan Panchayat 三级规划层级
5. **增量 KG 更新**: 支持运行时动态添加约束/地块到 KG，无需重建

   - 参考: GIS Copilot 的元令牌驱动工具一致性检查
6. **PostGIS 迁移**: 从 SQLite 迁移到 PostgreSQL + PostGIS，支持空间索引和并行查询

   - 参考: Web GIS 前端架构参考中的 PostGIS 最佳实践

### 8.3 低优先级

7. **GeoPackage 离线支持**: 移动端离线数据包
8. **WMTS 瓦片缓存**: 前端 PWA 缓存天地图瓦片
9. **多语言规划文本**: 支持英文/少数民族语言规划报告解析

---

## 九、关键文件索引

| 模块        | 文件路径                                                                 | 行数 |
| ----------- | ------------------------------------------------------------------------ | ---- |
| 布局引擎    | `backend/app/services/modules/gis/layout/engine.py`                    | ~350 |
| 意图模型    | `backend/app/services/modules/gis/layout/planning_intent.py`           | ~200 |
| Zone Schema | `backend/app/services/modules/gis/layout/zone_schema.py`               | ~150 |
| KG 本体     | `backend/app/services/modules/gis/layout/kg/ontology.py`               | ~100 |
| KG 构建器   | `backend/app/services/modules/gis/layout/kg/builder.py`                | ~200 |
| KG 查询     | `backend/app/services/modules/gis/layout/kg/query.py`                  | ~150 |
| MIP 分配器  | `backend/app/services/modules/gis/layout/optimizer/mip_allocator.py`   | ~300 |
| CA 精细化   | `backend/app/services/modules/gis/layout/optimizer/ca_refiner.py`      | ~150 |
| 邻接图      | `backend/app/services/modules/gis/layout/optimizer/adjacency_graph.py` | ~100 |
| 冲突检测    | `backend/app/services/modules/gis/layout/conflict_detector.py`         | ~200 |
| 冲突消解    | `backend/app/services/modules/gis/layout/conflict_resolver.py`         | ~150 |
| 验证器      | `backend/app/services/modules/gis/layout/validator.py`                 | ~200 |
| GIS 工具    | `backend/app/tools/gis/layout_tools.py`                                | ~500 |
| GIS 服务    | `backend/app/services/modules/gis/service.py`                          | ~53  |
| 地图组件    | `frontend/src/features/planning/components/gis/MapView.tsx`            | 607  |
| 图例面板    | `frontend/src/features/planning/components/gis/LegendPanel.tsx`        | 234  |
| 验证面板    | `frontend/src/features/planning/components/gis/ValidationPanel.tsx`    | 301  |
| SSE Hook    | `frontend/src/features/planning/hooks/useSSE.ts`                       | 311  |
| Store       | `frontend/src/features/planning/store/planningStore.ts`                | 2070 |
| Selectors   | `frontend/src/features/planning/hooks/useSelectors.ts`                 | 457  |

---

## 十、验证方案

1. **后端单元测试**: `pytest backend/tests/ -k gis` (86 通过)
2. **前端 E2E 测试**: `npx playwright test frontend/e2e/gis_*.spec.ts` (3 spec, 39 tests)
3. **端到端验证**: 启动后端 + 前端，输入"生成金田村规划布局"，验证:
   - SSE 事件流完整 (gis_result + gis_layer_update)
   - 7 种图层全部生成
   - MapView 渲染正确 (图例+图层+底图)
   - 验证面板显示通过结果
4. **MIP 约束验证**: 检查规划分区面积偏差 < 5%，永久基本农田面积满足约束
