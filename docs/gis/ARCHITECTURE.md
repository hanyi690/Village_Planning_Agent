# GIS 模块架构与调用关系

> 更新日期: 2026-07-15

## 模块架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    前端 (Next.js)                        │
│  MapView.tsx  LegendPanel  TracePanel  ValidationPanel   │
│           ↕ TypeScript API Client (gis-test-api.ts)      │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP REST
┌────────────────────────▼────────────────────────────────┐
│              API 层 (FastAPI)                            │
│  gis_test_routes.py → 19 个 /api/dev/gis/* 端点         │
│  routes.py → 统一路由挂载                                │
└───────┬──────────────┬──────────────┬───────────────────┘
        │              │              │
┌───────▼──────┐ ┌─────▼──────┐ ┌────▼─────────────────┐
│  Tools 层    │ │ Services 层│ │  Providers 层         │
│ (Agent 工具) │ │ (核心逻辑) │ │  (外部数据源)         │
│ tools/gis/   │ │ services/  │ │  providers/           │
│              │ │ modules/gis│ │  ├─ tianditu/ 天地图  │
│ parse.py     │ │            │ │  ├─ amap/ 高德        │
│ data.py      │ │ engine.py  │ │  ├─ osm/ OSM          │
│ kg.py        │ │ layout/    │ │  └─ poi.py            │
│ generate.py  │ │ optimizer/ │ │                       │
│ allocate.py  │ │ conflict/  │ │                       │
│ conflict.py  │ │ analysis/  │ │                       │
│ validate.py  │ │ kg/        │ │                       │
│ render.py    │ │ data/      │ │                       │
│ export.py    │ │ validation/│ │                       │
│ analytics.py │ │ zone_schema│ │                       │
│ _helpers.py  │ │   schema.py│ ← 统一分类真相源        │
└──────────────┘ └────────────┘ └───────────────────────┘
```

## 目录结构

### Services 层 (`backend/app/services/modules/gis/`)

| 子目录/文件 | 职责 |
|-------------|------|
| `engine.py` | 核心引擎，编排 KG→CONFLICT→ALLOCATE→GENERATE 管线 |
| `planning_intent.py` | UnifiedSpatialIntent 数据结构 |
| `zone_schema/schema.py` | ★ 统一分类 Schema — 全部 DLBM 分类的单一真相源 |
| `zone_schema/encodings.py` | 编码映射（从 schema 派生） |
| `zone_schema/code_sets.py` | 编码集合（从 schema 派生） |
| `zone_schema/colors.py` | GB/T 21010 国标色卡 |
| `data/fetcher.py` | GIS 数据获取（水系/道路/居民点/边界） |
| `data/gdb_schema.py` | GDB 12 层字段标准定义 |
| `kg/builder.py` | RDF 规划知识图谱构建 |
| `kg/ontology.py` | 规划领域本体定义 |
| `kg/query.py` | 知识图谱 SPARQL 查询 |
| `conflict/detector.py` | 冲突检测（指标/约束/空间三类） |
| `conflict/resolver.py` | 冲突消解 |
| `layout/data_loader.py` | 数据加载 + intent 解析编排（委派到 tool 层 LLM） |
| `layout/intent_cache.py` | 解析因子感知缓存（PARSE_VERSION + LLM_MODEL + 内容hash） |
| `layout/metrics_calculator.py` | GIS 实测面积约束计算 |
| `layout/compare_layouts.py` | 三路对比引擎 |
| `layout/zone_generator.py` | 功能分区生成（DLBM→合并→面积约束→CA精化） |
| `layout/facility_placer.py` | 设施布局（4种策略） |
| `layout/axis_builder.py` | 发展轴生成（一核一带三区） |
| `layout/map_renderer.py` | 多图层渲染配置 |
| `layout/planning_text_loader.py` | 规划 Markdown 文档加载 |
| `optimizer/mip_allocator.py` | PuLP MIP 整数规划分区分配 |
| `optimizer/mip_solver.py` | KKT 单目标优化求解器 |
| `optimizer/ca_refiner.py` | CA 元胞自动机平滑细化 |
| `optimizer/adjacency_graph.py` | 地块邻接关系图 |
| `optimizer/planning_zone_mapper.py` | DLBM → 规划分区映射（从 schema 查表） |
| `analysis/accessibility.py` | 可达性分析 |
| `analysis/coverage.py` | 地理覆盖率计算 |
| `providers/tianditu/` | 天地图 WFS 矢量 + 瓦片 |
| `providers/amap/` | 高德 POI + 逆地理编码 |
| `providers/osm/` | OSM 村级道路补充 |
| `providers/poi.py` | POI 搜索统一接口 |
| `validation/` | 规划验证模块 |
| `utils/` | 空间操作工具 |

### Tools 层 (`backend/app/tools/gis/`)

| 文件 | 业务逻辑归属 | Agent 调用场景 |
|------|-------------|---------------|
| `parse.py` | LLM 解析（gen+plan 双路径） | 解析规划文本为 intent |
| `data.py` | `data/fetcher.py` + `providers/` | 获取 GIS 数据 |
| `kg.py` | `kg/builder.py` + `kg/query.py` | 构建/查询知识图谱 |
| `generate.py` | `layout/` 全部子模块 | 生成空间布局 |
| `allocate.py` | `optimizer/mip_allocator.py` | MIP 分区分配 |
| `conflict.py` | `conflict/detector.py` + `resolver.py` | 冲突检测 |
| `validate.py` | `validation/` | 布局验证 |
| `render.py` | `layout/map_renderer.py` | 地图渲染 |
| `export.py` | `data/gdb_schema.py` | GeoPackage 导出 |
| `analytics.py` | `analysis/` | 可达性/覆盖分析 |
| `_helpers.py` | — | 工具响应辅助函数 |

---

## 核心数据流：规划文本 → GIS 图层

系统核心目标是 DESIGN_GOALS.md 中定义的端到端转换：

```
输入                             管线                              输出
──────────────────────────────────────────────────────────────────────────
规划报告文本 (Markdown)    →   PARSE (LLM)   →   UnifiedSpatialIntent
  ├─ 人工规划文本 (gen)           ↓                    ├─ zones[]      (功能分区 + 面积比例)
  └─ L3 系统报告 (plan)     + GIS 实测约束注入          ├─ facilities[] (设施类型 + 选址提示)
                             + schema.to_prompt_table()  ├─ axes[]       (发展轴线)
                                                        └─ constraints[](保护地块/面积约束)
                                    ↓
                             KG 构建 (RDF 三元组)
                             PlanningKG.build_from_intent()
                             8462 triples, 4 constraints
                                    ↓
                             CONFLICT 检测 & 消解
                             三类冲突: metric/constraint/spatial
                                    ↓
                             MIP 分配 (PuLP MILP)
                             目标: min(面积偏差 + DLBM 变更惩罚)
                             约束: 保护地块不划入建设区
                                    ↓
                             GENERATE 图层 (4 层)
                             ├─ function_zone   ZoneGenerator   DLBM → 6 类 → CA 精化
                             ├─ planning_zone    per-parcel       DLBM → 4 区 → dissolve
                             ├─ facility_point   FacilityPlacer   4 策略选址
                             └─ infrastructure   AxisBuilder      一核一带三区
                                    ↓
输出                              VALIDATE (8 项空间检查)
  ├─ GeoJSON 12 层                 ↓
  ├─ 用地平衡表 JSON          RENDER (matplotlib PNG)
  └─ 三路对比报告              EXPORT (GeoPackage)
```

> **关键原则**: 主路径始终依赖 LLM 解析规划文本产出高质量 intent。降级/兜底仅用于开发测试场景，
> 不应成为优化重心。优化方向是提升 LLM 解析的准确性和完整性，而非绕过 LLM。

## 调用链路

### 1. 双路径 pipeline —— 三路对比（主流程）

```
┌─ 规划 markdown (人工文本) ──→ parse_text_via_llm() ──→ gen intent ──┐
│      data/gis/jintian/planning_text/金田村委会.md                    │
└─────────────────────────────────────────────────────────────────────┤
                                                                      │
┌─ L3 reports (系统报告)      ──→ _parse_reports_to_intent() ──→ plan intent ──┐
│      output/experiments/rag/g1/iter0/layer3_reports.json                      │
└───────────────────────────────────────────────────────────────────────────────┤
                                                                                │
                           ┌────────────────────────────────────────────────────┘
                           ▼
                    KG 构建 ──→ CONFLICT 检测 ──→ MIP 分配 ──→ GENERATE 图层
                     ↓                                        ↓
              GIS 约束注入                           gen layers + plan layers
              (schema.to_prompt_table())                    │
                                                            ▼
                                                  三路对比 compare_layouts
                                                  ├─ gen vs planned/
                                                  ├─ plan vs planned/
                                                  └─ gen vs plan
```

### 2. LLM Prompt 分类注入

```
schema.py (83条 LandUseClass)
    → SCHEMA.to_prompt_table()
    → | DLBM | 名称 | 功能分区(L1) | 规划分区(L2) | 三区(L3) | GB/T |
      | 1340 | 商品林 | 农业用地 | 林业发展区 | 农业空间 | 0301 |
    → 注入 PARSE_AGENT_SYSTEM_PROMPT + SPATIAL_LAYOUT_PARSE_PROMPT
    → LLM 看到结构化分类表格，不再依赖手写文本补丁
```

### 3. 数据获取链路

```
API: /data-fetch
    ↓
data/fetcher.py → fetch_all_gis_data()
    ├─ tianditu/ → WFS 矢量数据 (水系/道路/居民点/边界)
    ├─ osm/ → OSMnx 补充村级道路
    └─ amap/ → POI搜索 + 逆地理编码
    ↓
GeoJSON 数据集 (water, road, residential, boundary)
```

---

## API 端点完整映射

### 状态与数据访问

| 方法 | 路径 | 调用目标 | 返回 |
|------|------|---------|------|
| GET | `/status` | 服务可用性检查 | `GisServiceStatus` |
| GET | `/jintian/files` | 列出 GeoJSON 文件 | 文件列表 |
| GET | `/jintian/data/{path}` | 加载 GeoJSON 文件 | 原始 GeoJSON |

### 数据获取

| 方法 | 路径 | 调用目标 Service | 返回 |
|------|------|-------------|------|
| POST | `/data-fetch` | `fetcher.fetch_all_gis_data()` | `DataFetchResult` |
| POST | `/center` | `fetcher.get_village_center()` | `CenterResult` |
| POST | `/bbox` | `fetcher.get_boundary_bbox()` | `BBoxResult` |

### 空间分析

| 方法 | 路径 | 目标 Service | 返回 |
|------|------|-------------|------|
| POST | `/accessibility` | `accessibility.py` | `AccessibilityResult` |
| POST | `/poi-search` | `poi.py` → Amap/Tianditu | `POISearchResult` |
| POST | `/coverage` | `coverage.py` | `CoverageResult` |

### 验证与评估

| 方法 | 路径 | 目标 Service | 返回 |
|------|------|-------------|------|
| POST | `/facility-validation` | `validate_facility_location()` | `FacilityValidationResult` |
| POST | `/ecological` | 生态敏感性评估 | `EcologicalResult` |
| POST | `/hazard-buffer` | 地质灾害缓冲区 | `HazardBufferResult` |
| POST | `/constraint-validator` | `conflict/detector.py` | `ConstraintValidatorResult` |
| POST | `/layout-validate` | `validation/` (8项检查) | `LayoutValidationResult` |

### 规划管线

| 方法 | 路径 | 目标 Service | 返回 |
|------|------|-------------|------|
| POST | `/spatial-layout` | `engine.full_pipeline()` | `SpatialLayoutResult` |
| POST | `/landuse-change` | 用地对比 | `LanduseChangeResult` |
| POST | `/parse-text` | 双路径 intent 解析 | `ParseResult` |
| POST | `/jintian/pipeline` | 双路径 + 三路对比 | `PipelineResult {gen, plan, comparison}` |

---

## 图层类型与国标色卡

系统使用 GB/T 21010-2017 标准，所有分区颜色由 `zone_schema/colors.py` 统一管理，不允许在各处重复定义：

| 图层类型 | 关键属性 | 颜色来源 | 数据来源 |
|----------|---------|---------|---------|
| `function_zone` | DLBM → zone_type (8类) | `ZONE_TYPE_COLORS` | DLBM 分类 |
| `planning_zone` | DLBM → planning_zone (6类) | `PLANNING_ZONE_COLORS` | MIP 分配 |
| `facility_point` | facility_type, status | `FACILITY_STATUS_COLORS` | 类型映射 |
| `infrastructure` | infrastructure_type | 分级着色 | `INFRA_COLORS` |

## 关键设计特点

1. **统一分类 Schema**: `zone_schema/schema.py` 为全部 DLBM 分类的单一真相源，`encodings.py`/`code_sets.py`/`prompts.py` 均从中派生
2. **双路径 + 三路对比**: gen(人工规划文本) vs plan(L3报告) vs planned/ (人工绘制GIS) 三条线独立运行后对比
3. **LLM prompt 结构化注入**: `SCHEMA.to_prompt_table()` 自动生成分类表格注入 prompt，不再手写 DLBM 示例
4. **GIS 约束注入**: GISMetricsCalculator 计算实测面积约束，同时注入 LLM prompt 和 KG 三元组
5. **Intent 解析因子感知缓存**: PARSE_VERSION + LLM_MODEL + 内容hash 联合作为缓存键
6. **GB/T 21010 国标色卡**: 所有分区颜色遵循国标，单一来源管理
7. **三层数据源互补**: 天地图（县级以上）→ OSM（村级道路）→ 高德（POI/逆地理编码）
8. **MIP+CA 双优化**: MIP 整数规划做分区分配，CA 元胞自动机做平滑细化
