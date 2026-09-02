# DATA 数据层

DATA 负责把显式声明的本地/远程来源转换成可追踪、不可变、可重载的输入产品。
唯一的 current DATA 写边界是
`app.modules.data.application.DataAdmissionFacade`；`DataCatalog` 只管理声明式 source
registry 和显式 bounded query。

## 真实输入闭包

当前金田村基线由以下输入组成：

- `data/gis/jintian/current/` 下的 10 个现状 GeoJSON；
- `data/gis/jintian/terrain/dem.tif`；
- `docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md`；
- `data/cache/map_observations/{amap,tianditu,tencent}/` 下带 manifest 的 provider observation；
- `data/cache/tiles/` 下的 WMTS tile cache。

`output/` 不承载 DATA cache 或旧 Bundle 输入。旧 output cache 和旧 DATA 历史模块已经物理删除。

## 活跃目录

| 目录 | 责任 |
|---|---|
| `ingestion/` | 上传、文件解析、source admission、连接和远程 driver |
| `catalog/` | YAML source registry、session artifact reload、provider lease/writer、advisory observation cache |
| `resource_catalog.py` | generic source/normalized/representation/capability catalog 和严格拓扑审计 |
| `boundary_scope.py` | 从已准入 boundary 生成 `BoundaryScopeArtifact` |
| `coordinate_contract.py` | 显式 CRS/坐标转换契约，未知坐标 fail closed |
| `model/` | DATA 所需 snapshot、基础值对象和资源类型 |
| `snapshots/` | DATA snapshot quality 辅助 |
| `modules/data/` | admission facade、catalog application、dependency invalidation、production gate |

## 统一产品链

```text
source bytes/declaration
  → DataAdmissionReceipt
  → SourceSnapshot
  → NormalizedResource
  → RepresentationSnapshot
  → CapabilityIndex
  → DataResourceCatalogIndexSnapshot
  → BoundaryScopeArtifact / provider observation snapshot
```

catalog index 只保存 refs、identity、digest 和 capability 索引；原始 geometry、normalized geometry
和 raw attributes 分别保存在对应 immutable component product 中。

## 下游边界

- WM 通过 `project_source_catalog()` 消费 normalized DATA catalog；
- Evidence 通过 `data_catalog_retriever` 读取 source-feature facts；
- 三家地图 cache 通过 `cached_map_retriever` 作为 advisory observation 读取；
- Planning Ground 只消费带 resource/representation/CRS/capability lineage 的数据；
- 任意下游结果带 `data_dependency_graph_digest`，DATA 变化时按依赖子图失效。

generic catalog 缺失时必须 fail closed。

## 已物理删除的兼容路径

DATA 不再提供旧 Bundle、BSM/DLBM 派生、external anchor injection、typed ingest adapters、
provider anchor aggregators、data-side fuzzy gazetteer、固定 boundary 读取或 output cache fallback。
旧路径缺失时必须得到明确的 gap/failure，不能返回空成功。
