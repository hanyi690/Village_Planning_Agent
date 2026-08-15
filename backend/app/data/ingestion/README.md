# data/ingestion 摄取子包

> 本 README 以 `backend/app/data/ingestion/` 实际代码为准（核验日期 2026-08-15）。
> 旧 `app/data/ingestion`、`modules/data` 内容已收敛到本包。

## 定位

会话输入与外部数据进入系统的摄取边界：上传文件解析、空间/非空间来源适配、文档加载、
表格与语义提取、地名解析、编译（l1/l2 profiles）。

## 文件职责

| 文件/目录 | 职责 |
|---|---|
| `upload.py` | `process_uploaded_file`：按文件名推断数据类型，解析文档/GeoJSON/栅格，返回文本与审计 |
| `ingest.py` | `ingest_current_landuse`/`ingest_planned_landuse`/`ingest_feature`/`ingest_raster`：原始→typed 模型；`result_to_parcels`/`result_to_features`/`result_to_raster` |
| `gazetteer.py` | 地名词典（地名→编码/坐标），供 L1 事实与 grounding |
| `semantics.py` | MetricConcept/ValueSemantics（跨维度指标冲突检测） |
| `tables.py` | 表格提取（分区/项目表），`table_schema_inference.py` 列语义推断 |
| `summary_generator.py` / `summary_parser.py` | 维度报告结构化摘要生成/解析（ReportStore 使用） |
| `spatial_language.py` | 空间关系语言解析 |
| `documents/` | 文档加载：`document_loader`、`docling_loader`、`mineru_loader`、`pdf_fallback`、`loader` |
| `sources/` | 数据来源驱动：`base`/`registry`/`file_vector`/`api_vector`/`document`/`local_raster`/`remote_raster`/`wmts_tile` |
| `connections/` | 连接抽象：`base`/`rate_limiter`/`tianditu`/`gd_tianditu`/`amap` |
| `providers/` | 地图 provider：`amap/`（anchor_service/provider/types）、`tencent/`、`tianditu/`（provider/tiles/wfs/gd_service） |
| `adapters/` | 摄取策略适配：`features`/`parcels`/`raster`/`table`/`document` |
| `compiler/` | 编译管线：`core`、`diagnostics`、`provenance`、`spec_mapper`、`profiles/l1_observation`、`profiles/l2_strategy` |

## 数据流

```text
上传文件 / 外部来源
  → upload / sources / providers / documents
  → adapters / ingest → typed records（canonical/spatial/table/raster models）
  → SessionDataSnapshot / SpatialWorkspace / VillageBundle
  → evidence / domain / workflow 消费
```

## 边界规则

- 不在此实现空间几何计算（BBox/距离/面积/过滤由 `app/spatial/` 完成）。
- 所有摄取结果保留来源、解析诊断与质量状态；失败必须显式报告，不允许静默降级。