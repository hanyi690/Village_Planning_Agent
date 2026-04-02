# GIS 功能测试报告

**生成时间**: 2026-04-02

## 架构变更

GIS 数据获取功能已重构为使用天地图 API：

- **移除**: OSM/osmnx 数据源（国内不可用）
- **移除**: 多服务降级策略（高德/百度）
- **新增**: 天地图行政区划边界服务
- **支持**: 省/市/县/乡/村五级行政区划

## 当前架构

```
src/tools/
├── adapters/
│   └── data_fetch/
│       └── gis_fetch_adapter.py      # GIS 数据获取适配器（天地图）
├── geocoding/
│   ├── tianditu_boundary.py          # 行政边界服务（核心）
│   ├── tianditu_provider.py          # 地理编码服务
│   └── base_provider.py              # 基类
```

## 配置要求

需要在 `.env` 文件中配置天地图 API Key：

```
TIANDITU_API_KEY=your_api_key_here
```

申请方式：
1. 访问 [天地图开发者平台](https://console.tianditu.gov.cn/)
2. 注册/登录账号
3. 创建应用获取 Key

免费额度：每日 1 万次调用

## 测试概览

| 功能 | 状态 | 说明 |
|------|------|------|
| boundary_fetch (县级) | 待测试 | 需配置 API Key |
| boundary_fetch (乡镇级) | 待测试 | 需配置 API Key |
| boundary_fetch (村级) | 待测试 | 需配置 API Key |
| smart_fetch | 待测试 | LLM 代码生成 |

## 使用示例

```python
from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

adapter = GISDataFetchAdapter()

# 获取县级边界
result = adapter.execute("boundary_fetch", location="平远县", level="county")

# 获取乡镇级边界
result = adapter.execute("boundary_fetch", location="泗水镇", level="town")

# 获取村级边界
result = adapter.execute("boundary_fetch", location="金田村", level="village")
```

## 精简内容

| 移除项 | 原因 |
|--------|------|
| OSM/osmnx | 国内访问不稳定 |
| 高德地理编码 | 移除多服务降级 |
| 百度地理编码 | 移除多服务降级 |
| Overpass API | 依赖 OSM |
| 坐标转换工具 | 天地图使用 WGS-84 |
| road_fetch | OSM 功能 |
| poi_fetch | OSM 功能 |