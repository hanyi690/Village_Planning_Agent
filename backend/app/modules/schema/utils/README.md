# Schema Utils — 纯计算工具

> **定位**：schema 层的**纯计算工具**（零外部依赖），供 KG / 工具层在**不 import tools** 的前提下复用。目前只有用地指标计算。

---

## 职责边界

**负责**：
- `metrics.py`：`compute_land_use_metrics` —— 从 GIS 数据聚合用地指标（纯函数，依赖 schema code sets + Python 标准库）

**不负责**：
- 不做完整 `GISMetricsCalculator`（`compute_summaries` / `compute_zone_distribution` / `_layer_geometry_area_ha` 等依赖 GeoDataFrame / area engine 的方法仍留在 `tools/gis/_analytics/metrics_calculator.py`）
- 不做 I/O / 几何引擎集成

---

## 输入/输出契约

**导出**（`utils/__init__.py`，wildcard）：`compute_land_use_metrics` 及指标相关类型。

**消费方**：KG builder（需要指标但不得 import tools 层）。

---

## 依赖方向

```
utils/ → schema/encodings（code sets）、标准库
   ▲ 被 kg/builder 与 tools/gis/_analytics 复用
```

- 允许：`schema` 内部、标准库
- 禁止：`agent` / `services` / `api` / `tools`、`data`、`kg`、`spatial_ops`

---

## 禁止行为

- 在 utils 内 import tools 层（本目录存在的意义就是打破 tools → schema 依赖）
- 把依赖 GeoDataFrame / 外部引擎的代码塞进纯函数目录（留在 metrics_calculator）
- 加非纯计算（I/O / 全局状态）工具到本目录
