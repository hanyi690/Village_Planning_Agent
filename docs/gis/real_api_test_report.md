# GIS 工具实际 API 验证测试报告

**生成时间**: 2026-04-03 18:57:29

## 测试概览

| 测试模块 | 测试项 | 状态 | 关键指标 |
|---------|--------|------|----------|
| 环境检查 | API Key | FAIL | 3f0e279e92...ef3d |
| 数据获取 | boundary_fetch | PASS | center=(115.886561, 24.56936) |
| 数据获取 | poi_fetch | PASS | count=5 |
| 数据获取 | reverse_geocode | PASS | - |
| 数据获取 | route_fetch | PASS | - |
| 数据获取 | wfs_fetch | PASS | - |
| 可达性分析 | service_coverage | PASS | facilities=3 |
| 可达性分析 | poi_coverage | PASS | - |
| 可达性分析 | driving_accessibility | PASS | reachable=3 |

## 详细测试结果

### 1. 环境检查

- **状态**: 已配置
- **Key Preview**: `3f0e279e92...ef3d`

### 2. 数据获取测试 (GISDataFetchAdapter)

#### boundary_fetch

- **成功**: True
- **center**: `(115.886561, 24.56936)`
- **admin_code**: `156441426`
- **location**: `平远县`

#### poi_fetch

- **成功**: True
- **poi_count**: `5`
- **total_count**: `5`
- **sample_pois**:
  - 平远县联发机动车驾驶员培训学校(报名处) @ (115.88421, 24.57002)
  - 平远县嘉润机动车驾驶员培训学校谢长江培训班 @ (115.89011, 24.57578)
  - 平远县老年人学校 @ (115.8951, 24.5757)

#### reverse_geocode_fetch

- **成功**: True
- **address**: ``
- **county**: ``
- **town**: ``

#### route_fetch

- **成功**: True
- **distance**: `27210.0`
- **duration**: `2784.0`
- **steps_count**: `0`

#### wfs_fetch

- **成功**: True
- **feature_count**: `22`
- **layer**: `LRDL`

### 3. 可达性分析测试 (AccessibilityAdapter)

#### service_coverage

- **成功**: True
- **facility_count**: `3`
- **coverage_rate**: `1.0`
- **radius**: `500`

#### poi_coverage

- **成功**: True
- **total_types**: `3`
- **covered_types**: `3`
- **coverage_summary**:
  - 学校: in_range=1, radius=500m
  - 医院: in_range=20, radius=1000m
  - 公园: in_range=1, radius=500m

#### driving_accessibility

- **成功**: True
- **total_count**: `3`
- **reachable_count**: `3`
- **coverage_rate**: `1.0`

### 4. 端到端流程验证

测试流程: boundary_fetch -> poi_fetch -> service_coverage

- **起点**: 通过 boundary_fetch 获取 center=(115.886561, 24.56936)
- **POI 搜索**: 找到 5 个学校
- **覆盖分析**: facility_count=3, coverage_rate=1.0
- **流程状态**: 全流程成功

---

*测试完成于 2026-04-03 18:57:29*