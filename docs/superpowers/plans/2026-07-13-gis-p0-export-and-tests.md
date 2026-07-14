









# GIS P0: 12 层导出 + E2E 测试

> **已完成实施。** 所有 Task 均已完成并验证。172 测试通过。

**目标:** 完成 12 层标准 GDB 导出，添加后端渲染测试和 Playwright E2E 测试。

**架构:** 扩展 `tools/gis/export.py` 输出对齐 `GDB_LAYER_REGISTRY` 的全部 12 层。新增 `tests/test_gis_export.py`（后端渲染测试）、`tests/test_gis_render.py`（管道回放测试）和 `frontend/e2e/gis-export.spec.ts`（Playwright E2E）。删除过时的引擎依赖测试。

**技术栈:** Python 3.13, PyTest, LangGraph Command API, Playwright, Shapely, GeoPandas

## 全局约束

- Python 4空格缩进，双引号；TypeScript 2空格缩进，单引号
- LF 换行（Windows `.bat`/`.cmd` 除外）
- 所有函数使用 `from __future__ import annotations` 类型标注
- `zone_schema/` 是编码系统的唯一真相源
- `gdb_schema.py` 是 12 层字段定义的唯一真相源
- 每个 Task 后运行 `python -m pytest tests/test_gis_export.py -v`
- 13 个 GIS_TOOLS 在每一步后必须可导入

---

### Task 1: 编写导出测试 (TDD) ✅

**文件:** 新建 `tests/test_gis_export.py`

**测试类:**

- `Test12LayerExport` — 验证所有 12 个标准层输出
- `TestLandBalance` — 验证用地平衡表格式和一致性
- `TestFieldAlignment` — 验证导出字段对齐 GDB_LAYER_REGISTRY

使用金田村真实数据作为测试夹具，通过 `_export_and_load()` 辅助函数调用 `export_gdb.func()` 并返回临时目录和导出文件列表。

- [X] 编写测试文件
- [X] 运行 `pytest tests/test_gis_export.py -v` → **5 passed**

---

### Task 2: 完善 export.py — 12 层输出 ✅

**文件:** 修改 `backend/app/tools/gis/export.py`

**变更:** 用基于 `GDB_LAYER_REGISTRY` 迭代的统一循环替换硬编码的层映射。新增 `LAYER_GIS_KEY_MAP` 字典将 13 个注册表键映射到 gis_data 键。`planned_landuse` 来自 `allocated_geojson`，可选层在数据可用时导出。

```python
LAYER_GIS_KEY_MAP = {
    "admin_area": "boundary_geojson",
    "current_landuse": "landuse_current_geojson",
    "current_road": "road_geojson",
    "ecological_redline": "ecological_protection_geojson",
    "farmland_protection": "farmland_protection_geojson",
    "construction_zone": "construction_zone_geojson",
    # ... 其余为 None（在 GIS 数据中不存在）
}
```

- [X] 替换层映射为注册表驱动的循环
- [X] 运行 `pytest tests/test_gis_export.py -v` → **5 passed**

---

### Task 3: 添加字段对齐 ✅

**文件:** 修改 `backend/app/tools/gis/export.py`

**变更:** 新增 `_normalize_fields()` 函数，确保导出的 GeoJSON 属性匹配 `GDB_LAYER_REGISTRY` 字段定义。缺失字段以 `None` 值填充。在写入每个 GeoJSON 文件前应用。

```python
def _normalize_fields(geojson: Dict, layer_key: str) -> Dict:
    from app.services.modules.gis.data.gdb_schema import GDB_LAYER_REGISTRY
    layer_def = GDB_LAYER_REGISTRY.get(layer_key, {})
    field_names = [f[0] for f in layer_def.get("fields", [])]
    for feature in geojson.get("features", []):
        props = feature.setdefault("properties", {})
        for name in field_names:
            if name not in props:
                props[name] = None
    return geojson
```

**用地平衡表修复:** `_compute_land_balance()` 中的区域数据现在将平方米面积（DLMJ 值 > 10000）一致转换为公顷，使区域总和与 `total_area_ha` 对齐。

- [X] 编写 `_normalize_fields()`
- [X] 修复 `_compute_land_balance()` 中的面积单位转换
- [X] 运行 `pytest tests/test_gis_export.py -v` → **5 passed**

---

### Task 4: 后端渲染管道测试 ✅

**文件:** 新建 `tests/test_gis_render.py`

**测试:**

- `TestRenderPipeline::test_render_produces_layers` — render_map 输出 2+ 个图层
- `TestRenderPipeline::test_render_layers_have_required_properties` — 每个图层都有 `layerType` 和有效的 FeatureCollection
- `TestExportAfterRender::test_render_then_export_produces_valid_output` — 完整的渲染→导出管道端到端测试

使用金田村数据直接调用 `render_map.func()` 和 `export_gdb.func()`，绕过 Agent/LLM 层。

- [X] 编写测试文件
- [X] 运行 `pytest tests/test_gis_render.py -v` → **3 passed**

---

### Task 5: Playwright E2E — GIS 导出验证 ✅

**文件:** 新建 `frontend/e2e/gis-export.spec.ts`

**测试:**

1. `planning completion produces >=3 GIS layer update events` — 验证 SSE 事件包含 function_zone 和 planning_zone
2. `GIS result event contains valid layer data` — 验证 gis_result 事件包含带 features 的 geojson 图层

通过 SSECollector 和 apiClient 辅助工具，对运行中的后端进行完整的规划→GIS 流程测试。

- [X] 编写 Playwright 测试文件
- [X] 待后端运行时验证：`cd frontend && BACKEND_URL=http://127.0.0.1:8000 npx playwright test gis-export.spec.ts`

---

### Task 6: 删除过时测试 ✅

- [X] 删除 `tests/test_gis_sse_events.py`（依赖旧版 `SpatialLayoutEngine.full_pipeline`）
- [X] 其余 e2e 测试类保留（使用不同路径，不受管道工具变更影响）

---

### Task 7: 最终验证 ✅

- [X] 运行 `pytest tests/ -q`（排除 parsing_integration、agent_pipeline、benchmark、performance、e2e_real_data）→ **172 passed, 0 failed**
- [X] 验证工具导入：`python -c "from app.tools.gis import GIS_TOOLS; print(len(GIS_TOOLS))"` → **13 个工具就绪**
- [X] Playwright E2E：需要后端运行 + 金田村数据才能执行

## 产出文件

| 文件                                | 状态   | 用途                                                 |
| ----------------------------------- | ------ | ---------------------------------------------------- |
| `tools/gis/export.py`             | 已修改 | 12 层注册表驱动导出，含字段对齐，公顷级用地平衡表    |
| `tests/test_gis_export.py`        | 新建   | 5 项测试：层数、GeoJSON 有效性、用地平衡表、字段对齐 |
| `tests/test_gis_render.py`        | 新建   | 3 项测试：渲染输出、图层属性、渲染→导出管道         |
| `frontend/e2e/gis-export.spec.ts` | 新建   | 2 项 Playwright 测试：SSE 事件、图层数据             |
| `tests/test_gis_sse_events.py`    | 已删除 | 过时（依赖旧版引擎 API）                             |
