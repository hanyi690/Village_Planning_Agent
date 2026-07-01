# GIS E2E Playwright Test Report

**Date**: 2026/7/1 15:21:42
**Page**: http://localhost:3000/test-gis

## Summary

| Metric | Value |
|--------|-------|
| Total | 12 |
| Passed | 3 |
| Failed | 9 |
| P3 Tests | 1/4 |

## Results

| Tool | Status | Duration | Error |
|------|--------|----------|-------|
| GIS 数据获取 | FAIL | 12462ms | unknown error |
| 村级中心定位 | FAIL | 436ms | 运行测试 button not found |
| 数据覆盖率 | FAIL | 12447ms | unknown error |
| 等时圈分析 | PASS | 4435ms |  |
| 可达性分析 | FAIL | 460ms | 运行测试 button not found |
| POI 搜索 | PASS | 6456ms |  |
| 生态敏感性 | FAIL | 440ms | 运行测试 button not found |
| 设施选址验证 | FAIL | 2383ms | unknown error |
| 约束验证 [P3#13] | FAIL | 445ms | 运行测试 button not found |
| 灾害缓冲区 [P3#9] | FAIL | 121296ms | timeout |
| 空间布局生成 [P3#12+#9] | FAIL | 425ms | 运行测试 button not found |
| 用地变化分析 [P3#13] | PASS | 2433ms |  |

## Screenshots

- GIS 数据获取: gis-e2e-data-fetch.png
- 村级中心定位: gis-e2e-center.png
- 数据覆盖率: gis-e2e-coverage.png
- 等时圈分析: gis-e2e-isochrone.png
- 可达性分析: gis-e2e-accessibility.png
- POI 搜索: gis-e2e-poi-search.png
- 生态敏感性: gis-e2e-ecological.png
- 设施选址验证: gis-e2e-facility-validation.png
- 约束验证: gis-e2e-constraint-validator.png
- 灾害缓冲区: gis-e2e-hazard-buffer.png
- 空间布局生成: gis-e2e-spatial-layout.png
- 用地变化分析: gis-e2e-landuse-change.png

## P3 Improvements Verified

| P3 Item | Tool | Status |
|---------|------|--------|
| P3#13 | 约束验证 | FAIL |
| P3#9 | 灾害缓冲区 | FAIL |
| P3#12+#9 | 空间布局生成 | FAIL |
| P3#13 | 用地变化分析 | PASS |
