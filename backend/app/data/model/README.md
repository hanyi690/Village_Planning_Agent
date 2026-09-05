# DATA model package

当前 DATA 模型层只保留跨运行时仍有直接消费者的不可变产品契约：

- `snapshot.py`：`SessionDataSnapshot`、`CollectionSnapshot`，用于 session manifest 和
  DATA→WM/Evidence 的稳定输入清单；
- `audit.py`：上层需要的 provenance/audit value objects。

原先的 `base.py`、`spatial_types.py`、`raster_types.py`、`table_types.py`、
`document_types.py`、`canonical.py`、`layer_registry.py` 以及对应 YAML 已物理删除。
它们属于旧 typed ingest / Bundle schema，不能再作为 DATA 输入、catalog writer 或
兼容导入路径。

现在的 DATA 输入不依赖文件名、字段名或预设图层注册表。所有本地和声明式远程输入都先
进入 `app.modules.data.application.DataAdmissionFacade`，被归一化为：

```text
SourceDataset
SourceFeature
NormalizedResource
SpatialRepresentation
DataCapability
DataResourceCatalogSnapshot
```

其中 `SourceFeature.geometry` 是不可覆盖的 native geometry，
`SourceFeature.normalized_geometry` 是经过显式 CRS 和 topology policy 校验后的空间视图。
Polygon/MultiPolygon 只在同属 polygon surface family 且修复审计通过时适配；不能无损
保留或无法确定语义的结果进入 read-only/UNRESOLVED 路径，不转换成规划地块。

WM 通过 `source_catalog_adapter` 消费 normalized representation 和 source digest；Evidence
通过 DATA catalog retriever 消费 feature/ref/attribute/provenance。二者都不能导入旧
Bundle、BSM 派生对象或固定 layer registry。
