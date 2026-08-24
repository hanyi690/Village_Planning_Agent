# Data 数据层

> 本 README 以 `backend/app/data/` 实际代码为准；已退役路径只保存在历史归档中。

## 定位

所有空间数据（矢量/栅格/瓦片）与非空间文档进入系统的唯一边界：上传、摄取、catalog、
编码、快照与来源管理。数据层拥有 `SessionDataSnapshot` / `SpatialWorkspace`，是 Agent
空间输入的权威来源。

## 目录职责

| 目录 | 职责 |
|---|---|
| `ingestion/` | 上传与摄取：文件解析（documents/）、空间来源（sources/）、地图 provider（providers/amap|tencent|tianditu）、连接（connections/）、适配器（adapters/）、编译器（compiler/，l1/l2 profiles + spec_mapper）、gazetteer/语义/表格/摘要 |
| `catalog/` | 数据目录：`catalog.DataCatalog`、`collection_registry`、`assembly`、`dedup`、`external_anchors`、`geometry_fallback`、`inference`、`admin_code_loader`、`advisory_crosswalks/`（crosswalks + registry） |
| `encodings/` | 用地分类编码：`classification`（ClassificationSchema）、`code_lookup`、`code_sets`、`metrics`、`dicts/`（candidate_engine/disambiguation/loader/rule_loader + vocabularies） |
| `model/` | typed 数据模型：`snapshot.SessionDataSnapshot`/`CollectionSnapshot`、`canonical`、`spatial_types`、`table_types`、`raster_types`、`document_types`、`layer_registry`、`location_parser`、`village_name_registry`、`audit`、`base` |
| `snapshots/` | 快照服务：`snapshot_service`（freeze_session_snapshot）、`data_quality` |
| `ports/` | 数据侧 Port：`ingest.DataIngestPort` |

## 关键入口

- `ingestion/upload.py::process_uploaded_file`：会话创建时上传文件（村庄数据/任务/约束）
  的解析入口，返回 `parsed_text` 等；供 `application/commands/create_session` 使用。
- `ingestion/ingest.py`：`ingest_current_landuse` / `ingest_planned_landuse` /
  `ingest_feature` / `ingest_raster` / `result_to_parcels` 等把原始 GeoJSON/栅格转换为
  typed 模型。
- `catalog/catalog.py::DataCatalog.load_village_bundle`：组装单村 `VillageBundle`
  （parcels/roads/constraints/water 等四形态 Group），供 context/KG/evidence 消费。
- `model/snapshot.py::SessionDataSnapshot`：冻结一次会话的输入资料 manifest（结构、CRS、
  来源、质量）；`spatial/model/workspace.SpatialWorkspace` 由它注入。

## 边界规则

- 数据层不做规划决策：不推导 DLBM→GHYTBM 分类，不生成 `PlanningProgram`/`ParcelChange`。
- 上传/摄取结果必须带 source identity、时间、CRS/schema、解析诊断与质量状态。
- 空间计算在 `app/spatial/`；本层只负责解析、注册与快照。
