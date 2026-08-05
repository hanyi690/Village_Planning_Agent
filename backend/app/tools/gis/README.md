# Tools GIS — GIS 工具集

> **定位**：把 `modules/spatial_ops` 等领域能力封装为 **LangChain `@tool`** 供 Agent / API 调用的 GIS 工具集。**薄适配器，不实现算法**。
> **Updated: 2026-08-05**（Batch B：`_conflict/` 已移除——detector/resolver 迁至 `modules/spatial_ops/conflict`；axis_builder / custom_zone_generator 迁至 `modules/spatial_ops/geometry` 与 `zoning`）

---

## 职责边界

**负责**：GIS 工具调用面（冲突检测 / GDB 导出 / 结构化文本提取 / KG 构建查询 / 编码查询 / 地图渲染 / 布局校验）+ 内部逻辑子目录（生成 / 校验 / 分析 / 渲染）。

**不负责**：
- 不实现空间算法（冲突检测在 `modules/spatial_ops/conflict`，渲染图层契约在 `modules/spatial_ops/output`，分区生成在 `modules/spatial_ops/zoning`）
- 不 import agent 作为业务依赖

---

## 输入/输出契约

**入口**（`gis/__init__.py`）：`get_gis_pipeline_tools()` 懒加载工具集（`detect_conflicts` / `export_gdb` / `extract_structured_text` / `build_knowledge_graph` / `query_knowledge_graph` / `lookup_land_use_code` / `render_map` / `validate_layout` 等）。

**根级工具文件**：

| 文件 | 工具/职责 |
|---|---|
| `conflict.py` | `detect_conflicts`（合并自 layout/conflict detector+resolver 的 @tool 包装） |
| `export.py` | `export_gdb`（GIS 输出包服务适配器） |
| `extract.py` | `extract_structured_text`（表格文本 → 结构化 JSON 行） |
| `kg.py` | `build_knowledge_graph` / `query_knowledge_graph`（KG 服务适配器） |
| `lookup.py` | `lookup_land_use_code`（同系统 code↔name；跨系统 `map_code` 已移除，advisory 不暴露给 LLM） |
| `render.py` | `render_map`（GeoJSON → 前端 MapLibre 格式，经 `spatial_ops/output/map_layers`） |
| `html_render.py` / `static_render.py` | 会话 GIS 结果的交互 HTML / 静态规划预览渲染器 |
| `validate.py` | `validate_layout`（合并 validate_aggregate + facility_validator） |

**内部子目录**：

| 子目录 | 现状 | 见 README |
|---|---|---|
| `_generation/` | 仅剩 `pipeline.py` 编排器（axis_builder / custom_zone_generator 已迁出） | `_generation/README.md` |
| `_validation/` | `facility_validator.py` | `_validation/README.md` |
| `_analytics/` | accessibility / coverage / isochrone / metrics_calculator | `_analytics/README.md` |
| `_rendering/` | 空（仅 `__init__.py`，deprecated 槽位） | `_rendering/README.md` |
| `_conflict/` | **已移除**（Batch B：detector/resolver → `modules/spatial_ops/conflict`） | —（根 README 声明） |

---

## 依赖方向

```
gis/ → modules/spatial_ops（conflict / output / zoning）、modules/kg、modules/data、schema/output、app.utils
     → langchain_core.tools / langgraph.prebuilt
   ▲ 被 agent（get_gis_pipeline_tools）与 API 消费
```

- 允许：`modules/*`（消费领域能力）、`schema/*`、`app.utils`、LangChain
- 禁止：在工具内实现算法；反向 import agent 作为业务依赖

---

## 禁止行为

- 在工具文件里复刻 `modules/` 算法（内联几何 / 内联冲突检测 / 内联分区生成）
- 恢复已迁移的 `_conflict/`（冲突能力统一在 `modules/spatial_ops/conflict`）
- 向 LLM 暴露 cross-system advisory 映射（`lookup.py` 只做同系统）
- 新增工具不加入 `get_gis_pipeline_tools()` 懒加载清单
