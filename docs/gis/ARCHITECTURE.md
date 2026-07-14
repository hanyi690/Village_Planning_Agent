# GIS 模块架构与调用关系

> 生成日期: 2026-07-14

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
│ export.py    │ │ providers/ │ │                       │
│ analytics.py │ │ zone_schema│ │                       │
└──────────────┘ └────────────┘ └───────────────────────┘
```

## 目录结构

### Services 层 (`backend/app/services/modules/gis/`)

| 子目录/文件 | 职责 |
|-------------|------|
| `engine.py` | 核心引擎，编排空间布局管线 |
| `planning_intent.py` | UnifiedSpatialIntent 数据结构 |
| `data/fetcher.py` | GIS 数据获取（水系/道路/居民点/边界） |
| `data/gdb_schema.py` | GeoPackage schema 定义 |
| `kg/builder.py` | RDF 规划知识图谱构建 |
| `kg/ontology.py` | 规划领域本体定义 |
| `kg/query.py` | 知识图谱空间查询 |
| `conflict/detector.py` | 冲突检测（指标/约束/空间三类） |
| `conflict/resolver.py` | 冲突消解 |
| `layout/axis_builder.py` | 道路/基础设施轴生成（一核一带三区） |
| `layout/compare_layouts.py` | 多布局方案对比 |
| `layout/data_loader.py` | GIS 数据与村庄参数加载 |
| `layout/facility_placer.py` | 设施布局（4种策略） |
| `layout/intent_cache.py` | 规划意图缓存 |
| `layout/map_renderer.py` | 多图层渲染配置 |
| `layout/metrics_calculator.py` | 空间指标计算 |
| `layout/planning_text_loader.py` | 规划 Markdown 文档加载 |
| `layout/zone_generator.py` | DLBM 分类 → 统一分区生成 |
| `optimizer/adjacency_graph.py` | 地块邻接关系图 |
| `optimizer/ca_refiner.py` | CA 元胞自动机平滑细化 |
| `optimizer/mip_allocator.py` | PuLP MIP 整数规划分区分配 |
| `optimizer/mip_solver.py` | KKT 单目标优化求解器 |
| `optimizer/planning_zone_mapper.py` | DLBM → 规划分区映射 |
| `optimizer/procedural.py` | 过程化生成回退方案 |
| `analysis/accessibility.py` | 可达性分析 |
| `analysis/coverage.py` | 地理覆盖率计算 |
| `analysis/isochrone.py` | 等时圈生成 |
| `providers/tianditu/` | 天地图 WFS 矢量 + 瓦片 |
| `providers/amap/` | 高德 POI + 逆地理编码 |
| `providers/osm/` | OSM 村级道路补充 |
| `providers/poi.py` | POI 搜索统一接口 |
| `providers/rate_limiter.py` | 第三方 API 限流 |
| `zone_schema/` | 分区类型映射与国标色卡 |
| `validation/` | 规划验证模块 |
| `utils/` | 空间操作工具 |

### Tools 层 (`backend/app/tools/gis/`)

| 文件 | 包装的 Service | Agent 调用场景 |
|------|---------------|---------------|
| `parse.py` | `planning_intent.py` + LLM | 解析规划文本 |
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

### 前端组件 (`frontend/src/features/planning/components/gis/`)

| 组件 | 调用的 API | 展示内容 |
|------|-----------|---------|
| `MapView.tsx` | `/spatial-layout`, `/jintian/pipeline` | MapLibre GL 地图 + GeoJSON 图层 |
| `LegendPanel.tsx` | 从 MapView 图层数据生成 | 动态图例（GB/T 21010 色卡） |
| `LayerTogglePanel.tsx` | 无直接 API 调用 | 图层显隐控制 |
| `TracePanel.tsx` | `/parse-text` | 空间推理过程可视化 |
| `ValidationPanel.tsx` | `/layout-validate` | 8 项验证结果展示 |

---

## 核心调用链路

### 1. 规划文本 → 布局生成（主流程）

```
用户输入规划文本
    ↓
parse.py → _parse_reports_to_intent()  (LLM 解析)
    ↓
UnifiedSpatialIntent (zones, facilities, axes, constraints)
    ↓
kg/builder.py → 构建 RDF 知识图谱 (约束三元组)
    ↓
conflict/detector.py → 检测三类冲突
    ├─ metric_conflicts (指标冲突)
    ├─ constraint_violations (约束违反)
    └─ spatial_conflicts (空间冲突)
    ↓
optimizer/mip_allocator.py → MIP 整数规划求解
    ├─ 变量: x[i][z] = 地块i → 分区z
    ├─ 目标: 最小化面积偏差 + DLBM偏好 + 邻接奖励
    └─ 输出: GeoJSON (assigned_zone, changed, area_ha)
    ↓
layout/zone_generator.py → DLBM分类 → 统一分区
    ↓
layout/facility_placer.py → 4种设施布局策略
    ├─ existing_keep (保留现有)
    ├─ planned_new (规划新增)
    ├─ expand (扩建)
    └─ relocate (迁建)
    ↓
layout/axis_builder.py → 一核一带三区 道路/基础设施轴
    ↓
layout/map_renderer.py → 多图层渲染配置
    ↓
GeoJSON → 前端 MapView 展示
```

### 2. 数据获取链路

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

### 3. 空间分析链路

```
API: /accessibility
    ↓
analysis/accessibility.py → run_accessibility_analysis()
    ├─ analysis/isochrone.py → 等时圈生成 (5/10/15分钟)
    └─ analysis/coverage.py → 服务覆盖率计算
```

### 4. 冲突检测链路

```
API: /constraint-validator
    ↓
conflict/detector.py → detect_all()
    ├─ 指标冲突: 跨维度数值不一致
    ├─ 约束违反: 超出 GIS 现实约束
    └─ 空间冲突: 空间定义矛盾
    ↓
conflict/resolver.py → 自动/人工消解
```

---

## API 端点完整映射

### 状态与数据访问

| 方法 | 路径 | 调用目标 | 返回 |
|------|------|---------|------|
| GET | `/status` | 服务可用性检查 | `GisServiceStatus` |
| GET | `/jintian/files` | 列出 GeoJSON 文件 | 文件列表 + 元数据 |
| GET | `/jintian/data/{path}` | 加载 GeoJSON 文件 | 原始 GeoJSON |

### 数据获取

| 方法 | 路径 | 调用目标 Service | 返回 |
|------|------|-------------|------|
| POST | `/data-fetch` | `fetcher.fetch_all_gis_data()` | `DataFetchResult` |
| POST | `/center` | `fetcher.get_village_center()` | `CenterResult` [lon, lat] |
| POST | `/bbox` | `fetcher.get_boundary_bbox()` | `BBoxResult` |

### 空间分析

| 方法 | 路径 | 目标 Service | 返回 |
|------|------|-------------|------|
| POST | `/isochrone` | `isochrone.py` | `IsochroneResult` (5/10/15min) |
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
| POST | `/parse-text` | `_parse_reports_to_intent()` | `ParseResult` |
| POST | `/jintian/pipeline` | 双路径对比 (gen vs plan) | `PipelineResult` |

---

## 图层类型与国标色卡

系统使用 GB/T 21010-2017 标准，所有分区颜色由 `zone_schema/` 统一管理：

| 图层类型 | 关键属性 | 颜色规则 | 数据来源 |
|----------|---------|---------|---------|
| `function_zone` | DLBM, DLMC, land_use, color | 农业=橙, 居住=绿 等 | DLBM 分类 |
| `planning_zone` | assigned_zone | 4分区标准色 | MIP 分配 |
| `sensitivity_zone` | sensitivity_level, protection_type | 高=红, 中=黄, 低=绿 | 标准映射 |
| `facility_point` | facility_type, status | 村委会=棕, 学校=蓝 等 | 类型映射 |
| `infrastructure` | infrastructure_type, RN, name | 道路/水系分级色 | 分级着色 |
| `isochrone` | time_minutes | 5min=绿, 10min=黄, 15min=橙 | 距离映射 |

---

## 关键设计特点

1. **双入口架构**: 同一 Service 既被 API 直接调用，也被 Tool 封装后供 Agent 调用
2. **4 级回退策略**: 村中心定位 → 高德 POI → 天地图居民点 → 几何质心 → 默认坐标
3. **三数据源互补**: 天地图（县级以上）→ OSM（村级道路）→ 高德（POI/逆地理编码）
4. **MIP+CA 双优化**: MIP 整数规划做分区分配，CA 元胞自动机做平滑细化
5. **GB/T 21010 国标色卡**: 所有分区颜色遵循国标，`zone_schema/` 统一管理
6. **坐标系**: 高德 GCJ-02 → WGS-84 转换（残余偏移 <5m）
7. **OSMnx 2.x**: bbox 格式 `(west, south, east, north)`

---

## 前端 API 客户端

`frontend/src/features/gis-test/api/gis-test-api.ts` 提供 18 个类型安全的端点调用：

- 所有请求使用 POST（带可选参数）
- 统一错误处理（`apiRequest` 包装）
- 分析类端点均返回 `timing_ms`
- TypeScript 类型与后端响应结构一一对应
