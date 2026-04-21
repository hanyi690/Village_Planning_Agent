# GIS 数据系统架构

本文档说明 GIS 数据获取、坐标系统、空间布局生成和前端可视化的核心链路。

## 目录

- [系统概览](#系统概览)
- [空间布局生成架构](#空间布局生成架构)
- [维度与 GIS 工具绑定](#维度与-gis-工具绑定)
- [数据源与坐标系统](#数据源与坐标系统)
- [GIS 工具速查](#gis-工具速查)
- [前端可视化](#前端可视化)
- [关键文件路径](#关键文件路径)

---

## 系统概览

```
数据源层（天地图/高德 API）
    ↓
数据获取层（GISDataFetcher / POIProvider）
    ↓
工具封装层（gis_tool_wrappers / ToolRegistry）
    ↓
空间布局层（spatial_layout_generator）
    ↓
SSE 事件层（dimension_complete → gis_data）
    ↓
前端可视化层（MapView.tsx）
```

---

## 空间布局生成架构

### 新架构流程

采用 **"LLM 结构化约束输出 → 程序化几何生成 → GeoJSON 渲染"** 的现代化链路。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    空间布局生成流程                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. LLM 结构化输出                                                            │
│     dimension_node.py (spatial_structure)                                    │
│         └── 输出 Markdown 规划文本                                            │
│                                                                              │
│  2. 独立节点解析                                                              │
│     spatial_layout_node.py (新增)                                            │
│         └── Flash LLM + JSON Mode                                            │
│         └── 解析为 VillagePlanningScheme                                     │
│                                                                              │
│  3. 程序化几何生成                                                            │
│     spatial_layout_generator.py                                              │
│         ├── 道路切割边界 → 生成地块                                           │
│         ├── 根据 area_ratio/location_bias 分配用地类型                       │
│         ├── 合并相邻同类型地块                                                │
│         └── 生成设施点位                                                      │
│         └── 输出 GeoJSON FeatureCollection                                   │
│                                                                              │
│  4. GeoJSON 渲染                                                             │
│     SSE → gis_data → 前端 MapView.tsx                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 核心模块

| 模块 | 职责 |
|------|------|
| `planning_schema.py` | Pydantic 模型定义（VillagePlanningScheme、PlanningZone 等） |
| `spatial_layout_generator.py` | 道路切割、方位筛选、面积匹配、地块合并算法 |
| `spatial_layout_node.py` | 独立节点：解析文本 → 生成 GeoJSON → SSE 发送 |
| `spatial_layout_prompts.py` | Flash LLM 解析 Prompt 模板 |

### 触发机制

```
dimension_node (spatial_structure)
    ↓ 输出 Markdown 规划文本
collect_results → check_completion
    ↓ 检测 spatial_structure 完成
spatial_layout_node (触发)
    ↓ Flash LLM 解析 → VillagePlanningScheme
    ↓ spatial_layout_generator → GeoJSON
    ↓ SSE 发送 gis_data
前端 MapView.tsx
```

### Pydantic 数据模型

```python
class PlanningZone(BaseModel):
    zone_id: str                          # 地块编号 Z01
    land_use: str                         # 用地类型（居住用地、产业用地等）
    area_ratio: float                     # 面积占比 (0.0-1.0)
    location_bias: LocationBias           # 位置偏向（center/north/south等）
    adjacency: AdjacencyRule              # 相邻关系约束
    density: Literal["high","medium","low"]

class VillagePlanningScheme(BaseModel):
    zones: List[PlanningZone]             # 规划地块
    facilities: List[FacilityPoint]       # 公共设施
    axes: List[DevelopmentAxis]           # 发展轴线
    rationale: str                        # 规划说明
```

---

## 维度与 GIS 工具绑定

### Layer 1: 现状分析

| 维度 | 工具 | 输出 |
|------|------|------|
| `natural_environment` | `wfs_data_fetch` | 水系/道路/居民地 GeoJSON + 中心坐标 |
| `land_use` | `gis_coverage_calculator` | 用地结构统计 + GIS 图层数据 |
| `traffic` | `accessibility_analysis` | 可达性矩阵 |
| `public_services` | `poi_search` | POI 列表 + GeoJSON |

### Layer 3: 详细规划

| 维度 | 工具 | 输入类型 | 输出 |
|------|------|----------|------|
| `spatial_structure` | `planning_vectorizer` | `zones/facilities` JSON | 空间结构 GeoJSON |
| `traffic_planning` | `isochrone_analysis` | center + time_minutes | 等时圈 GeoJSON |
| `public_service` | `facility_validator` | facility_type + location | 设施选址评分 |
| `ecological` | `ecological_sensitivity` | study_area | 敏感区分布 |

**独立节点触发**：`spatial_structure` 完成后触发 `spatial_layout_node`，生成完整的规划布局 GeoJSON。

---

## 数据源与坐标系统

### API 配置

| 服务 | 环境变量 | 获取地址 |
|------|----------|----------|
| 天地图 | `TIANDITU_API_KEY` | console.tianditu.gov.cn |
| 高德 | `AMAP_API_KEY` | lbs.amap.com |
| DashScope（Flash LLM） | `DASHSCOPE_API_KEY` | dashscope.console.aliyun.com |

### 坐标转换

| 数据源 | 原始坐标系 | 转换 |
|--------|-----------|------|
| 天地图 | CGCS2000 | 无需转换（兼容 WGS84） |
| 高德 | GCJ-02 | 自动转 WGS84（偏移 50-500m） |

转换函数：`src/tools/geocoding/amap/provider.py` → `gcj02_to_wgs84()`

---

## GIS 工具速查

### 维度绑定工具

| 工具 | 用途 | 数据源 | 关键参数 |
|------|------|--------|----------|
| `wfs_data_fetch` | 获取空间数据 | 天地图 WFS | location, buffer_km |
| `gis_coverage_calculator` | 用地统计+图层 | 天地图 WFS + 高德 | location, buffer_km |
| `poi_search` | POI 搜索 | 高德（优先） | keyword, center, radius |
| `accessibility_analysis` | 可达性分析 | 天地图路径规划 | analysis_type, center |
| `isochrone_analysis` | 等时圈生成 | 天地图 | center, time_minutes, travel_mode |
| `planning_vectorizer` | 规划矢量化 | 内部处理 | zones, facilities |
| `facility_validator` | 设施选址评分 | 内部算法 | facility_type, location |
| `ecological_sensitivity` | 敏感区评估 | 内部算法 | study_area |
| `spatial_layout_generator` | 空间布局生成 | 道路+边界 | planning_scheme |

### 核心函数（直接调用）

| 函数 | 模块 | 用途 |
|------|------|------|
| `run_spatial_overlay()` | `spatial_analysis.py` | 空间叠加（intersect/union/difference） |
| `run_spatial_query()` | `spatial_analysis.py` | 空间查询（contains/intersects/nearest） |
| `render_planning_map()` | `map_renderer.py` | HTML 地图渲染 |

**WFS 可用图层**：HYDA（水系面）、HYDL（水系线）、LRDL（公路）、RESA（居民地面）

---

## 前端可视化

### MapView 组件

```typescript
interface GISLayerConfig {
  geojson: GeoJSON;
  layerType: string;  // boundary/water/road/residential/facility_point/isochrone/function_zone/development_axis
  layerName: string;
  color?: string;
}
```

### 图层类型与样式

| layerType | 说明 | 默认样式 |
|-----------|------|----------|
| `boundary` | 行政边界 | 线状 #333333，无填充 |
| `water` | 水系 | 填充 #87CEEB |
| `road` | 道路 | 线状 #FF6B6B |
| `residential` | 居民地 | 填充 #FFD700 |
| `function_zone` | 规划用地 | 按类型配色 |
| `facility_point` | 公共设施 | 按状态配色 |
| `development_axis` | 发展轴线 | 按类型配色 |
| `isochrone` | 等时圈 | 按时间配色 |
| `sensitivity_zone` | 敏感区 | 按敏感等级配色 |

### 用地类型配色

```typescript
function_zone: {
  '居住用地': { fill: '#FFD700', stroke: '#B8860B' },
  '产业用地': { fill: '#FF6B6B', stroke: '#CC0000' },
  '公共服务用地': { fill: '#4A90D9', stroke: '#1E3A5F' },
  '生态绿地': { fill: '#90EE90', stroke: '#228B22' },
  '交通用地': { fill: '#808080', stroke: '#404040' },
  '水域': { fill: '#87CEEB', stroke: '#4169E1' },
  '农业用地': { fill: '#8B4513', stroke: '#654321' },
  '商业用地': { fill: '#FFA500', stroke: '#CC8400' },
}
```

### 瓦片源

| 瓦片源 | 国内可用 | 需密钥 | 推荐 |
|--------|---------|--------|------|
| geoq | ✅ | ❌ | 开发测试 |
| tianditu | ✅ | ✅ | 生产环境 |

### SSE 数据流

```
gis_data_fetcher → wrap_gis_tool → dimension_node → SSE → MapView
spatial_layout_node → generate_spatial_layout → SSE → MapView
```

事件格式：`dimension_complete` 含 `gis_data.layers` 和 `mapOptions`

---

## 关键文件路径

### 数据获取层

| 功能 | 路径 |
|------|------|
| WFS 数据获取 | `src/tools/core/gis_data_fetcher.py` |
| GIS 工具包装 | `src/tools/core/gis_tool_wrappers.py` |
| 高德 API（含坐标转换） | `src/tools/geocoding/amap/provider.py` |
| 天地图 API | `src/tools/geocoding/tianditu/provider.py` |

### 空间布局生成层

| 功能 | 路径 |
|------|------|
| Pydantic 模型定义 | `src/tools/core/planning_schema.py` |
| 空间布局生成算法 | `src/tools/core/spatial_layout_generator.py` |
| 独立节点实现 | `src/orchestration/nodes/spatial_layout_node.py` |
| 解析 Prompt 模板 | `src/subgraphs/spatial_layout_prompts.py` |

### 核心分析层

| 功能 | 路径 |
|------|------|
| 空间分析核心 | `src/tools/core/spatial_analysis.py` |
| 等时圈分析 | `src/tools/core/isochrone_analysis.py` |
| 可达性分析 | `src/tools/core/accessibility_core.py` |
| 规划矢量化 | `src/tools/core/vector_editor.py` |
| 地图渲染 | `src/tools/core/map_renderer.py` |

### 配置与编排

| 功能 | 路径 |
|------|------|
| 维度元数据 | `src/config/dimension_metadata.py` |
| 主图路由 | `src/orchestration/main_graph.py` |
| 状态定义 | `src/orchestration/state.py` |
| 前端地图 | `frontend/src/components/gis/MapView.tsx` |
| 前端常量 | `frontend/src/lib/constants/gis.ts` |

---

## 历史演进

### 已废弃的模块

| 模块 | 原路径 | 处理 |
|------|------|------|
| `PlanningTextConverter` | `src/tools/gis/planning_converter.py` | 已删除 |
| `create_planning_layers_from_text()` | `src/tools/core/vector_editor.py` | 占位符已删除 |

### 架构演进

| 版本 | 方案 | 说明 |
|------|------|------|
| v1 | 文字解析 → 扇形几何 | 方位词解析生硬，视觉效果不佳 |
| v2 | **LLM 结构化 → 程序化生成** | Flash LLM 解析 + 道路切割 + 面积匹配 |