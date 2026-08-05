# Tools GIS _analytics — 空间分析逻辑

> **定位**：GIS 工具的分析逻辑子目录（自 `modules/gis/analysis/` 迁移的非冲突、非校验文件）。**分析即计算，无 LLM**。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：
- 可达性分析（`accessibility.py`，基于天地图 API）
- 数据覆盖计算（`coverage.py`，经 `DataCatalog`）
- 等时圈分析（`isochrone.py`，5/10/15 分钟步行/驾车等时圈 + 服务区缺口分析）
- 指标计算（`metrics_calculator.py`，`GISMetricsCalculator`）

**不负责**：
- 不做生成/校验/冲突/渲染（那是其余子目录与 `modules/spatial_ops`）
- 不做 LLM 调用（纯数据计算）

---

## 输入/输出契约

**导出**（`_analytics/__init__.py`）：`GISMetricsCalculator` / `calculate_coverage` / `run_accessibility_analysis` / `generate_isochrones`。

| 文件 | 入口 | 输出 |
|---|---|---|
| `accessibility.py` | 中心点 + 服务配置 | 可达性分析结果 + `format_accessibility_result` |
| `coverage.py` | 数据源 | 覆盖统计 + `format_coverage_result` |
| `isochrone.py` | 中心点 + 时间 | 等时圈多边形 + 覆盖/缺口 + `format_isochrone_result` |
| `metrics_calculator.py` | GeoJSON landuse | 摘要指标（`compute_land_use_metrics` 纯计算已抽到 `modules/schema/utils/metrics.py`） |

---

## 依赖方向

```
_analytics/ → modules/data（DataCatalog / providers）、modules/schema、app.utils（crs / geo / area）
   ▲ 被 GIS 分析工具（_analytics 由工具层包装）与 pipeline 消费
```

- 允许：`modules/*`、`app.utils`
- 禁止：`agent` / `services` / `api`；不依赖 LangGraph State

---

## 禁止行为

- 把纯计算塞进 metrics_calculator 而绕过 `modules/schema/utils/metrics.py`（KG 需要它但不得 import tools）
- 硬编码指标值（必须从 GIS 数据推导）
- 在分析逻辑内做 LLM 调用
