# spatial_ops.output — 前端图层契约与成果导出

## 职责边界

- `map_layers.py`：将 DELIVER 已加载的 snapshot 图层和规划覆盖层转换为前端
  MapLibre 图层契约；它不读取 AgentState，也不决定空间事实。
- `build_trace_layer(...)`：仅用于 EXPLORE 定位校核视图，不属于正式交付图层。
- `export_package.py`：标准 GeoJSON 规划成果包导出。
  - `export_delivery_package(...)`：只接收 `DeliverySpatialSnapshot`，按
    GDB_LAYER_REGISTRY 写 current/、planned/、
    tables/（land_balance.json）、layout.json 与 run_manifest.json；
    输出字段按 registry 归一化补齐。

## 输入输出契约

- 输入：`DeliverySpatialSnapshot` + 规划覆盖层 `layout_configs` + 村庄名/会话
  id/校验结果。snapshot 内的 source refs 是 current/constraint 的唯一来源。
- 输出：MapLibre 图层 dict 列表（含 semantic_group/default_visible/
  source_label，经 `GISLayerConfig` 归一化）。
- 导出返回 `{status, output_dir, exported_files, file_count}`；
  默认输出到 `<project_root>/output/gis/<run_key>/`。

## 依赖方向

- 依赖 `app.utils.sse_events.GISLayerConfig` 与
  `app.modules.schema.output.gdb.GDB_LAYER_REGISTRY`。
- 不依赖 Agent / LangChain 工具封装。

## 禁止行为

- 禁止在转换过程中修改传入的 gis_data/layout_configs（只读）。
- 禁止绕过 GDB_LAYER_REGISTRY 自定义输出字段名。
- 禁止写死村庄名/会话路径（须由参数传入并安全转义）。
- 禁止在导出时做空间计算（仅文件序列化与字段归一化）。
