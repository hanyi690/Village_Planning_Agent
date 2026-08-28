# Spatial 空间层

> 本 README 以 `backend/app/spatial/` 实际代码为准（核验日期 2026-08-15）。

## 定位

几何、空间查询、接地、变更、网络（路网）、地形与空间校验。SELECT 的分配和选地实现归属
`modules/select/`；`spatial/` 消费
`data/` 提供的 `SpatialWorkspace` / typed 输入，产出 typed 空间结果供
`modules/ground`、`modules/select` 和 `modules/execute` 消费；
不读取 workflow state 的裸 payload。

## 目录职责

| 目录 | 职责 | 关键文件 |
|---|---|---|
| `model/` | 几何基础模型 | `workspace.SpatialWorkspace`（空间工作边界）、`geometry`（ParcelRelations/邻接计算）、`subdivision`（地块切分/setback）、`area_engine`、`crs_engine`、`coord_transform`、`geojson_utils`、`parcel_ops`、`relations`、`axis_builder` |
| `grounding/` | 空间接地 | `grounding`/`grounding_service`（bbox/近邻查询）、`resolver`（空间引用解析）、`flash_mention_extractor`（地名实体提取）、`bundle_binder`、`coordinate_identity`（坐标/BSM 合并）、`topology`（拓扑证据） |
| `query/` | 空间查询 | `bridge`（SpatialIndex/ConstraintIndex/OverlapResult）、`context.compute_context_blocks`（ContextBlock 生成）、`feature_query` |
| `change/` | 地块变更 | `parcel_change` |
| `delivery/` | 空间交付辅助 | `land_balance`（土地平衡）、`style`（分类着色） |
| `validation/` | 空间冲突校验 | `detector.ConflictDetector`（metric/constraint/spatial 冲突）、`resolver.ConflictResolver`、`spatial_quality` |
| `terrain/` | 地形证据 | `evidence`（DEM 源解析/校验/哈希） |
| `network/` | 路网规划 | `network_builder`（拓扑构建）、`planner`（道路规划主入口）、`road_candidate_preparation`、`terrain_router`（A* 地形路由）、`spatial_binder`、`text_structurer`、`location_confirmation`、`comparison_evaluator`、`kg_rdflib_adapter`、`kg_retry`、`stage2_6_validator`、`qgis_export`、`schemas` |

## 关键入口

- `model/workspace.SpatialWorkspace`：数据层冻结的 `SessionDataSnapshot` 注入的空间工作边界，
  是 Agent 侧唯一空间入口（`workflow/layers/context_bootstrap` 构建）。
- `grounding/resolver.resolve_spatial_reference` + `grounding_service.resolve_spatial_reference`：
  GROUND 阶段把 `SpatialReferenceSpec` 的文本/坐标引用解析为候选地块/实体。
- `network/planner.py`：路网规划（含 DEM 地形、可达性、成本面、A* 路由），产出
  `NetworkBuildResult` 与道路证据。
- `validation/detector.ConflictDetector`：跨维度指标/约束/空间冲突检测，产出 `ConflictReport`。

## 边界规则

- 空间计算只在这里（及 `data/` 的解析边界）完成；业务模块只消费 typed 结果，不做几何。
- 所有输入使用 workspace/typed model，不允许从 workflow state 读裸 GIS。
- 交付图层最终由 `workflow/delivery` + `infrastructure/export` 从 `DeliverySpatialSnapshot`
  派生；本层不单独维护第二份 current/planned 来源。
