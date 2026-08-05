# Tools GIS _rendering — 渲染子目录（空槽位）

> **定位**：GIS 渲染内部子目录——当前**为空（仅 `__init__.py`），保留 deprecated 槽位**。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：暂无实际逻辑（`__init__.py` 为空文件，无导出）。

**现状说明**：会话 GIS 结果的**实际渲染能力**位于工具根级——`tools/gis/render.py`（`render_map` → 前端 MapLibre 格式）、`tools/gis/html_render.py`（交互 HTML）、`tools/gis/static_render.py`（静态预览）；图层契约来自 `modules/spatial_ops/output/map_layers.py`。

---

## 输入/输出契约

无（空包，无公共 API）。

---

## 依赖方向

无（空包）。

---

## 禁止行为

- 在此新建第二套渲染实现（渲染逻辑已稳定在根级工具文件 + `modules/spatial_ops/output`）
- 在无明确需求前向空槽位填充代码（保持 deprecated 标记即可）
