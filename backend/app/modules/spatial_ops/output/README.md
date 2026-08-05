# spatial_ops.output — 前端图层契约与成果导出

## 职责边界

- `map_layers.py`：后端 GIS 图层 → 前端 MapLibre 图层契约的纯转换。
  - `build_map_layers(layout_configs, gis_data) -> List[dict]`：汇总现状底图
    （现状用地/道路/注记/边界）、生成层（规划主分区/功能分析/空间管制/发展轴线
    等语义分组）、输入管制层（生态/基本农田/历史保护/建设边界）。
  - `build_trace_layer(explore_instructions, gis_data)`：构建"定位校核"图层
    （EXPLORE grounding 候选 BSM → 面标注），供前端核对语义落点。
- `export_package.py`：标准 GeoJSON 规划成果包导出。
  - `export_gdb_package(...)`：按 GDB_LAYER_REGISTRY 写 current/、planned/、
    tables/（land_balance.json）、layout.json 与 run_manifest.json；
    输出字段按 registry 归一化补齐。

## 输入输出契约

- 输入：layout_configs（layer_type/data/color/style...）+ gis_data
  （各类 *_geojson）+ 村庄名/会话 id/校验结果。
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
