# GIS 数据系统架构

本文档详细说明 GIS 数据获取、坐标系统、瓦片服务和前端可视化的完整链路。

## 目录

- [系统概览](#系统概览)
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
┌─────────────────────────────────────────────────────────────────┐
│                        数据源层                                  │
├──────────────────┬──────────────────┬──────────────────────────┤
│   天地图 API     │    高德 API      │       其他数据源          │
│  - WFS 服务      │   - POI 搜索     │    - 路径规划            │
│  - 地理编码      │   - 地理编码     │    - 等时圈分析          │
│  - POI 搜索      │   - 路径规划     │                          │
└────────┬─────────┴────────┬─────────┴──────────┬───────────────┘
         │                  │                    │
         ▼                  ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      数据获取层                                 │
├──────────────────┬──────────────────┬──────────────────────────┤
│  GISDataFetcher  │   POIProvider    │   TiandituProvider       │
│  - WFS 数据      │   - 高德优先     │    - 地理编码            │
│  - 村级定位      │   - 坐标转换     │    - 边界查询            │
└────────┬─────────┴────────┬─────────┴──────────┬───────────────┘
         │                  │                    │
         ▼                  ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      工具封装层                                 │
├──────────────────┬──────────────────┬──────────────────────────┤
│ gis_tool_wrappers│   ToolRegistry   │   dimension_node         │
│ - wrap_gis_data  │   - 工具注册     │    - SSE 数据提取        │
│ - wrap_poi_search│   - 统一接口     │    - 维度工具绑定        │
└────────┬─────────┴────────┬─────────┴──────────┬───────────────┘
         │                  │                    │
         ▼                  ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SSE 事件层                                 │
│   dimension_complete → gis_data → Frontend                      │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      前端可视化层                               │
├──────────────────┬──────────────────┬──────────────────────────┤
│    MapView.tsx   │ DimensionSection │   LayerReportCard        │
│   - 瓦片渲染     │   - 地图组件     │    - 图层展示            │
│   - GeoJSON 图层 │   - 交互控制     │    - 数据可视化          │
└──────────────────┴──────────────────┴──────────────────────────┘
```

---

## 维度与 GIS 工具绑定

### Layer 1: 现状分析（12 个维度）

| 维度 | 维度名称 | GIS 工具 | 分析目的 | 分析结果 |
|------|----------|----------|----------|----------|
| `natural_environment` | 自然环境分析 | `wfs_data_fetch` | 获取水系、道路、居民地空间数据 | 水系/道路/居民地 GeoJSON 图层 + 村庄中心坐标 |
| `land_use` | 土地利用分析 | `gis_coverage_calculator` | 计算各类用地覆盖率 | 用地结构统计 + GeoJSON 图层 |
| `traffic` | 道路交通分析 | `accessibility_analysis` | 交通可达性分析 | 服务覆盖分析 + 可达性矩阵 |
| `public_services` | 公共服务设施分析 | `poi_search` | 周边公共服务设施搜索 | POI 列表 + GeoJSON 点图层 |
| `socio_economic` | 社会经济分析 | `population_model_v1` | 人口趋势预测 | 人口预测数据 |

### Layer 3: 详细规划（12 个维度）

| 维度 | 维度名称 | GIS 工具 | 分析目的 | 分析结果 |
|------|----------|----------|----------|----------|
| `spatial_structure` | 空间结构规划 | `planning_vectorizer` | 规划方案矢量化 | 空间结构 GeoJSON 图层 |
| `traffic_planning` | 道路交通规划 | `isochrone_analysis` | 等时圈分析 | 5/10/15 分钟等时圈 GeoJSON |
| `public_service` | 公共服务设施规划 | `facility_validator` | 设施配置验证 | 设施覆盖评估 + 建议优化点 |
| `ecological` | 生态绿地规划 | `ecological_sensitivity` | 生态敏感性分析 | 敏感区分布 GeoJSON + 分级评估 |

### 工具参数配置示例

```python
# dimension_metadata.py 中的工具参数配置

"natural_environment": {
    "tool": "wfs_data_fetch",
    "tool_params": {
        "location": {"source": "config", "path": "village_name"},
        "buffer_km": {"source": "literal", "value": 5.0}
    }
}

"traffic": {
    "tool": "accessibility_analysis",
    "tool_params": {
        "analysis_type": {"source": "literal", "value": "service_coverage"},
        "center": {"source": "gis_cache", "path": "_auto_fetched.center"}
    }
}

"public_services": {
    "tool": "poi_search",
    "tool_params": {
        "keyword": {"source": "literal", "value": "学校|医院|超市|银行"},
        "center": {"source": "gis_cache", "path": "_auto_fetched.center"},
        "radius": {"source": "literal", "value": 5000}
    }
}

"traffic_planning": {
    "tool": "isochrone_analysis",
    "tool_params": {
        "center": {"source": "gis_cache", "path": "_auto_fetched.center"},
        "time_minutes": {"source": "literal", "value": [5, 10, 15]},
        "travel_mode": {"source": "literal", "value": "walk"}
    }
}
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

### 坐标转换

高德 POI 数据使用 GCJ-02 坐标系，需转换为 WGS84：

```python
# src/tools/geocoding/amap/provider.py

def gcj02_to_wgs84(lon: float, lat: float) -> Tuple[float, float]:
    """GCJ-02 转 WGS-84"""
    if _out_of_china(lon, lat):
        return lon, lat
    # 坐标转换计算...
    return wgs_lon, wgs_lat
```

### 数据源坐标系统

| 数据源 | 原始坐标系 | 转换后 | 说明 |
|--------|-----------|--------|------|
| 天地图 WFS | CGCS2000 | 无需转换 | 与 WGS84 兼容 |
| 天地图 POI | CGCS2000 | 无需转换 | 与 WGS84 兼容 |
| 天地图瓦片 | 经纬度投影 | 无需转换 | 与 WGS84 兼容 |
| 高德 POI | GCJ-02 | WGS84 | 自动转换 |

---

## GIS 分析工具详解

### 1. WFS 数据获取 (`wfs_data_fetch`)

**用途**: 获取天地图 WFS 服务的空间数据

**数据源**: 天地图 WFS 服务 (`gisserver.tianditu.gov.cn/TDTService/wfs`)

**可用图层**:
| WFS 图层 | 说明 | 几何类型 |
|----------|------|----------|
| TDTService:HYDA | 水系面 | Polygon |
| TDTService:HYDL | 水系线 | LineString |
| TDTService:LRDL | 公路 | LineString |
| TDTService:LRRL | 铁路 | LineString |
| TDTService:RESA | 居民地面 | Polygon |
| TDTService:RESP | 居民地点 | Point |

**输入参数**:
```python
{
    "location": "平远县泗水镇金田村",  # 行政区名称
    "buffer_km": 5.0,                 # 缓冲距离（公里）
    "max_features": 500               # 各类要素最大数量
}
```

**输出结果**:
```python
{
    "success": True,
    "location": "平远县泗水镇金田村",
    "center": [116.04, 24.82],        # 村庄中心坐标
    "is_village_level": True,
    "water": {
        "success": True,
        "geojson": {...},              # 水系 GeoJSON
        "metadata": {"feature_count": 12}
    },
    "road": {
        "success": True,
        "geojson": {...},              # 道路 GeoJSON
        "metadata": {"feature_count": 8}
    },
    "residential": {
        "success": True,
        "geojson": {...},              # 居民地 GeoJSON
        "metadata": {"feature_count": 25}
    }
}
```

**实现逻辑**:
```
1. 解析地址层级（省/市/县/镇/村）
2. 如果是村级地址：
   a. 先获取县级边界作为参考
   b. 地理编码定位村级中心
   c. 失败则 POI 搜索定位
   d. 失败则使用县级中心
3. 根据中心坐标计算缓冲 bbox
4. 并行获取水系、道路、居民地数据
```

---

### 2. POI 搜索 (`poi_search`)

**用途**: 搜索周边公共服务设施

**数据源**: 高德地图 POI API（优先） / 天地图 POI API（备选）

**输入参数**:
```python
{
    "keyword": "学校|医院|超市|银行",  # 搜索关键词（支持多类型）
    "center": [116.04, 24.82],        # 中心坐标
    "radius": 5000                    # 搜索半径（米）
}
```

**输出结果**:
```python
{
    "success": True,
    "pois": [
        {
            "id": "B0FFAB1234",
            "name": "某某学校",
            "lon": 115.892285,        # WGS-84 经度（已转换）
            "lat": 24.559714,         # WGS-84 纬度（已转换）
            "lon_gcj02": 115.893000,  # 原始 GCJ-02 坐标
            "lat_gcj02": 24.560000,
            "address": "广东省梅州市平远县",
            "distance": 500,
            "category": "科教文化服务;学校"
        }
    ],
    "geojson": {
        "type": "FeatureCollection",
        "features": [...]
    },
    "source": "amap"                  # 数据来源
}
```

**高德优先策略**:
- 高德 QPS 限制 30，天地图 QPS 限制 5
- 高德 POI 数据更丰富
- 自动进行 GCJ-02 → WGS84 坐标转换

---

### 3. 可达性分析 (`accessibility_analysis`)

**用途**: 分析交通可达性和服务覆盖

**数据源**: 天地图路径规划 API

**分析类型**:
| 类型 | 说明 | 适用场景 |
|------|------|----------|
| `driving_accessibility` | 驾车可达性 | 对外交通分析 |
| `walking_accessibility` | 步行可达性 | 村内交通分析 |
| `service_coverage` | 服务半径覆盖 | 设施覆盖分析 |
| `poi_coverage` | POI 设施覆盖 | 多类型设施分析 |

**服务半径标准**:
```python
SERVICE_RADIUS_STANDARDS = {
    "幼儿园": 300,
    "小学": 500,
    "中学": 1000,
    "医院": 1000,
    "诊所": 500,
    "公园": 500,
    "公交站": 300,
    "超市": 500,
}
```

**输出结果**:
```python
{
    "success": True,
    "data": {
        "geojson": {...},              # 设施点 GeoJSON
        "facilities": [...],           # 设施列表
        "covered_points": [...],       # 覆盖点
        "uncovered_points": [...],     # 未覆盖点
        "summary": {
            "total_facilities": 12,
            "covered_count": 8,
            "coverage_rate": 0.67
        }
    }
}
```

---

### 4. 等时圈分析 (`isochrone_analysis`)

**用途**: 生成基于时间的可达性区域

**数据源**: 天地图路径规划 API（驾车模式）/ 圆形近似（步行模式）

**旅行速度**:
| 模式 | 速度 | 说明 |
|------|------|------|
| walk | 5 km/h | 步行 |
| bike | 15 km/h | 骑行 |
| drive | 40 km/h | 驾车（城市平均） |

**输入参数**:
```python
{
    "center": [116.04, 24.82],
    "time_minutes": [5, 10, 15],      # 时间区间（分钟）
    "travel_mode": "walk"              # 步行/驾车/骑行
}
```

**输出结果**:
```python
{
    "success": True,
    "data": {
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "time_minutes": 5,
                        "travel_mode": "walk",
                        "radius_km": 0.42
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [...]
                    }
                },
                // 10分钟、15分钟等时圈...
            ]
        },
        "isochrones": [...],
        "center": [116.04, 24.82]
    }
}
```

**实现逻辑**:
```
1. 计算理论半径: radius = (time / 60) * speed
2. 对于驾车模式：
   a. 在 16 个方向上采样
   b. 调用路径规划 API 获取实际可达点
   c. 根据实际时间调整半径
3. 对于步行模式：
   a. 使用圆形近似
   b. 生成 16 个采样点
4. 构建多边形 GeoJSON
```

---

### 5. 空间分析 (`spatial_analysis`)

**用途**: 空间叠加分析和查询

**依赖**: GeoPandas + Shapely

**操作类型**:
| 操作 | 说明 | 适用场景 |
|------|------|----------|
| `intersect` | 交集 | 两图层重叠区域 |
| `union` | 并集 | 合并两图层 |
| `difference` | 差集 | A 中不在 B 的部分 |
| `clip` | 裁剪 | 用 B 边界裁剪 A |

**查询类型**:
| 查询 | 说明 | 适用场景 |
|------|------|----------|
| `contains` | 包含 | 查找包含查询几何的要素 |
| `intersects` | 相交 | 查找与查询几何相交的要素 |
| `within` | 在内部 | 查找在查询几何内部的要素 |
| `nearest` | 最近 | 查找最近的要素 |

---

### 6. 生态敏感性分析 (`ecological_sensitivity`)

**用途**: 评估区域生态敏感程度

**分析因素**:
- 水系缓冲区
- 坡度分析
- 植被覆盖
- 地质条件

**输出结果**:
```python
{
    "success": True,
    "data": {
        "geojson": {...},              # 敏感区分布 GeoJSON
        "sensitivity_levels": {
            "high": {"area_km2": 2.5, "percentage": 15},
            "medium": {"area_km2": 5.0, "percentage": 30},
            "low": {"area_km2": 9.2, "percentage": 55}
        },
        "recommendations": [...]
    }
}
```

---

## 瓦片服务

### 前端瓦片配置

```typescript
// frontend/src/components/gis/MapView.tsx

const TILE_SOURCES = {
  // GeoQ ArcGIS - 国内可用，无需密钥，EPSG:3857
  geoq: {
    url: 'https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineCommunity/MapServer/tile/{z}/{y}/{x}',
    attribution: 'GeoQ',
  },
  // 天地图 - 需要前端密钥，EPSG:3857 (TILEMATRIXSET=w)
  tianditu: {
    url: `https://t0.tianditu.gov.cn/vec_w/wmts?...TILEMATRIXSET=w...`,
    attribution: '天地图',
  },
  // OpenStreetMap - 默认备选（国内可能不稳定）
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
  center?: [number, number];  // [longitude, latitude]
  zoom?: number;
  height?: string;
  title?: string;
}

interface GISLayerConfig {
  geojson: GeoJSON;      // GeoJSON 数据
  layerType: string;     // 图层类型: water/road/residential/facility_point/isochrone
  layerName: string;     // 图层名称
  color?: string;        // 颜色
}
```

### 规划符号样式

```typescript
// frontend/src/lib/constants/gis.ts

const PLANNING_COLORS = {
  function_zone: {
    '居住用地': { fill: '#FFD700', stroke: '#B8860B' },
    '产业用地': { fill: '#FF6B6B', stroke: '#CC5555' },
    '公共服务用地': { fill: '#4A90D9', stroke: '#3A70A9' },
  },
  water: { fill: '#3b82f6', stroke: '#2563eb' },
  road: { stroke: '#ef4444', width: 2 },
  residential: { fill: '#f97316', stroke: '#ea580c' },
  isochrone: {
    '5min': { fill: '#22c55e', stroke: '#16a34a' },
    '10min': { fill: '#eab308', stroke: '#ca8a04' },
    '15min': { fill: '#f97316', stroke: '#ea580c' },
  },
};
```

---

## SSE 数据流转

### 数据提取函数

```python
# src/orchestration/nodes/dimension_node.py

def _extract_gis_data_for_sse(gis_tool_result: NormalizedToolResult) -> Optional[Dict]:
    """从 GIS 工具结果提取 SSE 事件所需的 GIS 数据"""
    if not gis_tool_result or not gis_tool_result.success:
        return None

    result = {}

    if gis_tool_result.has_geojson:
        result["layers"] = gis_tool_result.layers_data or []

    if gis_tool_result.has_analysis:
        result["analysisData"] = gis_tool_result.analysis_data

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
  "dimension_name": "自然环境分析",
  "layer": 1,
  "gis_data": {
    "layers": [
      {
        "geojson": {"type": "FeatureCollection", "features": [...]},
        "layerType": "water",
        "layerName": "水系",
        "color": "#3b82f6"
      },
      {
        "geojson": {"type": "FeatureCollection", "features": [...]},
        "layerType": "road",
        "layerName": "道路",
        "color": "#ef4444"
      }
    ],
    "mapOptions": {
      "center": [116.04, 24.82],
      "zoom": 14
    }
  }
}
```

### 数据流转链路图

```
gis_data_fetcher.py
    │ fetch_all_gis_data() → {water, road, residential}
    ▼
gis_tool_wrappers.py
    │ wrap_gis_data_fetch() → NormalizedToolResult
    ▼
dimension_node.py
    │ _extract_gis_data_for_sse() → 提取 layers 和 mapOptions
    ▼
sse_publisher.py
    │ send_dimension_complete(gis_data=...)
    ▼
前端 DimensionSection.tsx
    │ 接收 SSE 事件，解析 gis_data
    ▼
MapView.tsx
    │ 渲染 GeoJSON 图层
```

---

## 诊断与调试

### 诊断脚本

```bash
# 运行完整 GIS 链路诊断
python scripts/debug_full_gis_chain.py
```

### 诊断内容

| 模块 | 检查项 | 说明 |
|------|--------|------|
| WFS 数据 | API Key 配置 | 天地图密钥有效性 |
| WFS 数据 | 数据获取 | 水系/道路/居民地数据 |
| POI 数据 | 高德 API Key | 高德密钥有效性 |
| POI 数据 | 坐标转换 | GCJ-02 → WGS84 |
| 瓦片服务 | 前端配置 | 瓦片源和密钥 |

### 常见问题排查

#### 地图显示灰色

1. 检查瓦片服务配置（`NEXT_PUBLIC_TILE_SOURCE`）
2. 检查天地图密钥是否配置域名白名单
3. 检查浏览器控制台网络请求

#### POI 点位偏移

1. 确认高德 POI 坐标已转换（检查 `lon_gcj02` 字段存在）
2. 检查 `gcj02_to_wgs84` 函数是否被调用

#### WFS 数据不显示

1. 检查 `_extract_gis_data_for_sse` 是否正确提取嵌套格式
2. 检查 SSE 事件中 `gis_data.layers` 是否有数据
3. 检查 `features` 数组是否非空

---

## 关键文件路径

| 功能 | 后端路径 | 前端路径 |
|------|----------|----------|
| WFS 数据获取 | `src/tools/core/gis_data_fetcher.py` | - |
| GIS 工具包装 | `src/tools/core/gis_tool_wrappers.py` | - |
| 可达性分析 | `src/tools/core/accessibility_core.py` | - |
| 等时圈分析 | `src/tools/core/isochrone_analysis.py` | - |
| 空间分析 | `src/tools/core/spatial_analysis.py` | - |
| POI 数据 | `src/tools/geocoding/poi_provider.py` | - |
| 高德 API | `src/tools/geocoding/amap/provider.py` | - |
| 天地图 API | `src/tools/geocoding/tianditu/provider.py` | - |
| 维度元数据 | `src/config/dimension_metadata.py` | - |
| 维度节点 | `src/orchestration/nodes/dimension_node.py` | - |
| 地图渲染 | - | `frontend/src/components/gis/MapView.tsx` |
| 维度展示 | - | `frontend/src/components/chat/DimensionSection.tsx` |
| GIS 常量 | - | `frontend/src/lib/constants/gis.ts` |

---

## 相关文档

- [工具系统实现](./tool-system-implementation.md) - 工具注册与执行
- [后端API与数据流](./backend-api-dataflow.md) - SSE 事件类型
- [前端状态与数据流](./frontend-state-dataflow.md) - 前端状态管理