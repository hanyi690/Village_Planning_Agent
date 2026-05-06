# GIS 数据系统架构

本文档详细说明 GIS 数据获取、上传解析、坐标系统、瓦片服务和前端可视化的完整链路。

## 目录

- [系统概览](#系统概览)
- [数据来源与优先级](#数据来源与优先级)
- [用户上传系统](#用户上传系统)
- [边界兜底机制](#边界兜底机制)
- [维度与 GIS 工具绑定](#维度与-gis-工具绑定)
- [数据源配置](#数据源配置)
- [坐标系统](#坐标系统)
- [GIS 分析工具详解](#gis-分析工具详解)
- [瓦片服务](#瓦片服务)
- [前端可视化](#前端可视化)
- [SSE 数据流转](#sse-数据流转)
- [诊断与调试](#诊断与调试)

---

## 系统概览

### 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           数据源层                                            │
├────────────────┬────────────────┬────────────────┬──────────────────────────┤
│   用户上传     │   天地图 API    │    高德 API     │     其他数据源           │
│  - GeoJSON     │   - WFS 服务    │   - POI 搜索    │    - 路径规划           │
│  - Shapefile   │   - 地理编码    │   - 地理编码    │    - 等时圈分析         │
│  - KML/GDB     │   - POI 搜索    │   - 路径规划    │                          │
└────────┬───────┴────────┬───────┴────────┬───────┴──────────┬───────────────┤
         │                │                │                  │
         ▼                ▼                ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         数据解析与管理层                                       │
├────────────────┬────────────────┬────────────────┬──────────────────────────┤
│ GISDataParser  │ GISDataManager │SharedGISContext│   GISDataFetcher        │
│ - 格式解析     │ - 内存缓存     │ - 上下文管理    │    - WFS 数据           │
│ - CRS 转换     │ - 状态追踪     │ - 数据注入     │    - 村级定位           │
│ - 类型推断     │ - 按村庄组织   │ - 边界生成     │                          │
└────────┬───────┴────────┬───────┴────────┬───────┴──────────┬───────────────┘
         │                │                │                  │
         ▼                ▼                ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         工具封装层                                            │
├────────────────┬────────────────┬────────────────┬──────────────────────────┤
│gis_tool_wrappers│ BoundaryFallback│ToolRegistry  │   dimension_node        │
│- wrap_*_tools   │ - 5级兜底策略   │   - 工具注册   │    - SSE 数据提取       │
│- 数据优先级融合 │ - 代理边界生成 │   - 统一接口   │    - 维度工具绑定       │
└────────┬───────┴────────┬───────┴────────┬───────┴──────────┬───────────────┘
         │                │                │                  │
         ▼                ▼                ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SSE 事件层                                            │
│   dimension_complete → gis_data → Frontend                                   │
└─────────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         前端可视化层                                          │
├────────────────┬────────────────┬────────────────┬──────────────────────────┤
│   MapView.tsx  │ DataUpload.tsx │DimensionSection│   LayerReportCard        │
│   - 瓦片渲染   │   - 文件上传   │   - 地图组件   │    - 图层展示            │
│- GeoJSON 图层  │   - 类型推断   │   - 交互控制   │    - 数据可视化          │
└────────────────┴────────────────┴────────────────┴──────────────────────────┘
```

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
# 关键词映射（与前端 DataUpload.tsx 保持同步）
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

### 策略详细说明

#### 1. user_uploaded（用户上传）

```python
# 检查 GISDataManager 缓存
cached = GISDataManager.get_user_data(village_name, "boundary")
if cached and cached.geojson:
    return cached.geojson  # 返回用户上传边界
```

#### 2. isochrone（等时圈）

```python
# 生成 15 分钟步行等时圈（圆形近似）
result = generate_isochrones(
    center=center,
    time_minutes=[15],
    travel_mode="walk",
    use_route_api=False  # 使用圆形近似，提高可靠性
)
# 返回半径约 1.25 km 的圆形边界
```

#### 3. polygonize_fusion（自然边界融合）

```python
# 使用道路和水系线要素裁剪等时圈
trim_result = trim_polygon_with_lines(
    base_polygon=isochrone_polygon,
    natural_lines=[road_features + water_features],
    core_point=center,
)
# 生成更贴合自然地理的边界
```

#### 4. morphological_convex（形态包络）

```python
# 从居民地特征计算凸包或凹包
if use_concave:
    result = compute_concave_hull(
        geometries=residential_features,
        alpha=0.5,  # 凹包参数
    )
else:
    result = compute_convex_hull(geometries=residential_features)
```

#### 5. bbox_buffer（矩形缓冲）

```python
# 保底策略：生成 2km × 2km 矩形
buffer_km = 2.0
coords = [
    [center_lon - buffer_deg, center_lat - buffer_deg],
    [center_lon + buffer_deg, center_lat - buffer_deg],
    [center_lon + buffer_deg, center_lat + buffer_deg],
    [center_lon - buffer_deg, center_lat + buffer_deg],
]
# 始终成功返回
```

### 边界生成 API

```python
# SharedGISContext.get_or_generate_boundary()
boundary = gis_context.get_or_generate_boundary(
    force_generate=False,  # True 则跳过用户数据
    config=BoundaryFallbackConfig(
        isochrone_time_minutes=15,
        polygonize_min_lines=3,
        morphological_min_features=5,
        bbox_buffer_km=2.0,
    )
)
```

---

## 维度与 GIS 工具绑定

### Layer 1: 现状分析（12 个维度）

| 维度 | 维度名称 | GIS 工具 | 数据来源 | 分析结果 |
|------|----------|----------|----------|----------|
| `natural_environment` | 自然环境分析 | `gis_coverage_calculator` | 用户上传 + WFS | 水系/道路/居民地 GeoJSON + 村庄中心坐标 |
| `land_use` | 土地利用分析 | `gis_coverage_calculator` | 用户上传 | 用地结构统计 + GeoJSON 图层 |
| `traffic` | 道路交通分析 | `accessibility_analysis` | 用户上传 + WFS + 高德 | 服务覆盖分析 + 可达性矩阵 |
| `public_services` | 公共服务设施分析 | `poi_search` | 高德 POI API | POI 列表 + GeoJSON 点图层 |
| `socio_economic` | 社会经济分析 | `population_model_v1` | 无 GIS | 人口预测数据 |

### Layer 3: 详细规划（12 个维度）

| 维度 | 维度名称 | GIS 工具 | 数据来源 | 分析结果 |
|------|----------|----------|----------|----------|
| `spatial_structure` | 空间结构规划 | `spatial_layout_generator` | 边界 + 规划方案 | 空间结构 GeoJSON 图层 |
| `traffic_planning` | 道路交通规划 | `isochrone_analysis` | 村庄中心 | 5/10/15 分钟等时圈 GeoJSON |
| `public_service` | 公共服务设施规划 | `facility_validator` | 规划设施位置 | 设施覆盖评估 + 建议优化点 |
| `ecological` | 生态绿地规划 | `ecological_sensitivity` | 水系 + 规划边界 | 敏感区分布 GeoJSON + 分级评估 |

### gis_coverage_calculator 数据融合

```python
def wrap_gis_coverage_calculator(context: Dict[str, Any]) -> str:
    """
    数据获取优先级：用户上传 > 会话缓存 > 自动获取（天地图 WFS）
    """
    # 1. 检查用户上传数据
    user_water = context.get("user_uploaded_data", {}).get("water")
    user_road = context.get("user_uploaded_data", {}).get("road")
    user_residential = context.get("user_uploaded_data", {}).get("residential")

    # 2. 自动获取（作为兜底）
    auto_result = fetcher.fetch_all_gis_data(location, buffer_km)

    # 3. 合并数据源：用户数据覆盖自动数据
    def get_geojson_with_source(data_type, user_data, auto_data):
        if user_data:
            return user_data, "user_upload"
        if auto_data and auto_data.get("success"):
            return auto_data.get("geojson"), "auto_fetch"
        return None, "missing"

    # 返回结果包含 data_sources 字段标记来源
```

---

## 数据源配置

### 环境变量

```bash
# .env 文件配置

# 天地图 API Key（服务端密钥，校验 IP 白名单）
TIANDITU_API_KEY=your_tianditu_api_key

# 高德地图 API Key
AMAP_API_KEY=your_amap_api_key

# GIS 服务超时时间（秒）
GIS_TIMEOUT=30

# 天地图速率限制（每秒请求数）
TIANDITU_RATE_LIMIT=5.0

# 高德速率限制（每秒请求数）
AMAP_RATE_LIMIT=30.0
```

### 前端环境变量

```bash
# frontend/.env.local

# 瓦片源配置: tianditu | geoq | openstreetmap
NEXT_PUBLIC_TILE_SOURCE=geoq

# 天地图前端密钥（浏览器端密钥，与服务端密钥不同）
NEXT_PUBLIC_TIANDITU_KEY=your_browser_key
```

### API Key 获取

| 服务 | 获取地址 | 说明 |
|------|----------|------|
| 天地图 | https://console.tianditu.gov.cn/ | 需要申请服务端和浏览器端两个密钥 |
| 高德 | https://lbs.amap.com/ | Web 服务 API Key |

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

## GIS 分析工具详解

### 1. GIS Coverage Calculator (`gis_coverage_calculator`)

**用途**: 获取并融合 GIS 空间数据，支持用户上传优先

**数据来源优先级**:
```
用户上传 > GISDataManager 缓存 > 天地图 WFS 自动获取
```

**输入参数**:
```python
{
    "location": "平远县泗水镇金田村",
    "buffer_km": 5.0,
    "user_uploaded_data": {  # 可选，用户上传数据注入
        "boundary": {...},
        "water": {...},
        "road": {...},
        "residential": {...}
    }
}
```

**输出结果**:
```python
{
    "success": True,
    "location": "平远县泗水镇金田村",
    "coverage_rate": 0.67,
    "layers": [
        {"geojson": {...}, "layerType": "boundary", "source": "user_upload"},
        {"geojson": {...}, "layerType": "water", "source": "auto_fetch"},
        {"geojson": {...}, "layerType": "road", "source": "user_upload"}
    ],
    "data_sources": {
        "boundary": "user_upload",
        "water": "auto_fetch",
        "road": "user_upload",
        "residential": "missing"
    }
}
```

---

### 2. POI 搜索 (`poi_search`)

**用途**: 搜索周边公共服务设施

**数据源**: 高德地图 POI API（优先）

**输入参数**:
```python
{
    "keyword": "学校|医院|超市|银行",
    "center": [116.04, 24.82],
    "radius": 5000
}
```

**输出结果**:
```python
{
    "success": True,
    "pois": [...],
    "geojson": {"type": "FeatureCollection", "features": [...]},
    "source": "amap"  # 数据来源标记
}
```

---

### 3. Spatial Layout Generator (`spatial_layout_generator`)

**用途**: 根据规划方案生成空间布局 GeoJSON

**数据依赖**:
- `village_boundary`: 村庄边界（用户上传或代理生成）
- `road_network`: 道路网络
- `planning_scheme`: 规划方案 JSON

**输出结果**:
```python
{
    "success": True,
    "geojson": {...},           # 合并布局
    "zones_geojson": {...},     # 功能分区
    "facilities_geojson": {...}, # 设施点位
    "axes_geojson": {...},      # 发展轴线
    "center": [116.04, 24.82],
    "statistics": {
        "zone_count": 5,
        "facility_count": 12,
        "total_area_km2": 3.2
    }
}
```

---

## 瓦片服务

### 前端瓦片配置

```typescript
// frontend/src/components/gis/MapView.tsx

const TILE_SOURCES = {
  geoq: {
    url: 'https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineCommunity/MapServer/tile/{z}/{y}/{x}',
    attribution: 'GeoQ',
  },
  tianditu: {
    url: `https://t0.tianditu.gov.cn/vec_w/wmts?...TILEMATRIXSET=w...`,
    attribution: '天地图',
  },
  openstreetmap: {
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: 'OpenStreetMap',
  },
};
```

### 瓦片源选择建议

| 瓦片源 | 国内可用 | 需要密钥 | 坐标系 | 推荐场景 |
|--------|---------|---------|--------|----------|
| geoq | ✅ | ❌ | EPSG:3857 | 开发测试（当前默认） |
| tianditu | ✅ | ✅ | EPSG:3857 | 生产环境 |
| openstreetmap | ⚠️ | ❌ | EPSG:3857 | 国际项目 |

---

## 前端可视化

### MapView 组件

```typescript
// frontend/src/components/gis/MapView.tsx

interface MapViewProps {
  layers: GISLayerConfig[];
  center?: [number, number];
  zoom?: number;
  height?: string;
}

interface GISLayerConfig {
  geojson: GeoJSON;
  layerType: string;     // boundary/water/road/residential/facility_point
  layerName: string;
  color?: string;
  source?: string;       // user_upload | auto_fetch | missing
}
```

### DataUpload 组件

```typescript
// frontend/src/components/gis/DataUpload.tsx

// 支持拖拽上传和点击上传
// 自动推断数据类型（与后端 LAYER_TYPE_KEYWORDS 同步）
// 上传成功后调用 GISDataManager 存储
```

---

## SSE 数据流转

### 数据提取函数

```python
# src/orchestration/nodes/dimension_node.py

def _extract_gis_data_for_sse(gis_tool_result: NormalizedToolResult) -> Optional[Dict]:
    """从 GIS 工具结果提取 SSE 事件所需的 GIS 数据"""
    result = {}

    if gis_tool_result.has_geojson:
        result["layers"] = gis_tool_result.layers_data or []

    if gis_tool_result.center:
        result["mapOptions"] = {
            "center": gis_tool_result.center,
            "zoom": 14
        }

    return result if result else None
```

### SSE 事件格式

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

---

## 诊断与调试

### 测试端点（开发环境）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dev/gis/test/spatial-layout` | POST | 测试空间布局生成 |
| `/api/dev/gis/test/boundary-fallback` | POST | 测试边界兜底机制 |

### 诊断脚本

```bash
# 运行完整 GIS 链路诊断
python scripts/debug_full_gis_chain.py
```

### 常见问题排查

#### 用户上传数据不生效

1. 检查 `GISDataManager.get_data_status(village_name)` 返回值
2. 确认 `user_uploaded` 列表包含预期数据类型
3. 检查上传时 `infer_data_type()` 推断结果

#### 边界生成失败

1. 查看边界生成结果的 `fallback_history` 字段
2. 检查各策略失败原因（`reason` 字段）
3. 确认村庄中心点已正确计算

#### 地图显示灰色

1. 检查瓦片服务配置（`NEXT_PUBLIC_TILE_SOURCE`）
2. 检查天地图密钥域名白名单
3. 检查浏览器网络请求

---

## 关键文件路径

| 功能 | 后端路径 | 前端路径 |
|------|----------|----------|
| GIS 数据解析 | `src/tools/gis/data_parser.py` | - |
| GIS 数据管理 | `src/tools/gis/data_manager.py` | - |
| GIS 上传 API | `backend/api/gis_upload.py` | - |
| GIS 测试 API | `backend/api/gis_test.py` | - |
| GIS 工具包装 | `src/tools/core/gis_tool_wrappers.py` | - |
| 边界兜底机制 | `src/tools/core/boundary_fallback.py` | - |
| 共享 GIS 上下文 | `src/orchestration/shared_gis_context.py` | - |
| WFS 数据获取 | `src/tools/core/gis_data_fetcher.py` | - |
| POI 数据 | `src/tools/geocoding/poi_provider.py` | - |
| 高德 API | `src/tools/geocoding/amap/provider.py` | - |
| 天地图 API | `src/tools/geocoding/tianditu/provider.py` | - |
| 路由注册 | `backend/api/routes.py` | - |
| 地图渲染 | - | `frontend/src/components/gis/MapView.tsx` |
| 数据上传 | - | `frontend/src/components/gis/DataUpload.tsx` |
| API 客户端 | - | `frontend/src/lib/api/data-api.ts` |

---

## 相关文档

- [工具系统实现](./tool-system-implementation.md) - 工具注册与执行
- [后端API与数据流](./backend-api-dataflow.md) - SSE 事件类型
- [前端状态与数据流](./frontend-state-dataflow.md) - 前端状态管理