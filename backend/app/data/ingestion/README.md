# DATA ingestion

`app.data.ingestion` 是 DATA 的输入解析边界，不是领域对象组装层。

## 唯一写入路径

```text
UploadFile / declared source
  → bounded parser
  → source admission
  → DataAdmissionFacade.admit()
  → immutable DATA component products
```

上传入口是 `upload.process_uploaded_file`。它计算 source digest，执行 byte/text/row
预算和 temporal-role admission，然后把输入交给
`app.modules.data.application.DataAdmissionFacade`。上传记录只保存状态和 artifact refs；
current DATA 的事实来源是 CAS 中的 immutable products。

## 当前保留的组件

| 目录/文件 | 职责 |
|---|---|
| `upload.py` | 上传读取、文件类型识别、GeoJSON/通用矢量/栅格/表格/Markdown 解析 |
| `source_admission.py` | current/reference/control/planned 角色隔离和 temporal admission |
| `sources/` | `file_vector`、`api_vector`、`wmts_tile`、`local_raster`、`remote_raster`、`document` driver |
| `connections/` | 连接、凭据引用和 rate limiter |
| `documents/` | MinerU Markdown 文档入口；生产上传显式关闭本地解析 fallback |
| `providers/` | AMap、Tencent、Tianditu 的声明式 provider client；结果必须进入 provider run writer |
| `contracts.py` | `DataResult` 和 source metadata envelope |
| `source_identity.py` | source/dataset/feature identity 辅助 |
| `temporal_role_classifier.py` | 有界、可审计的来源时态角色分类 |

## 组件产品

`DataAdmissionFacade` 成功时发布：

```text
SourceSnapshotArtifact
NormalizedResourceArtifact
RepresentationSnapshotArtifact
CapabilityIndexArtifact
DataResourceCatalogIndexSnapshot
DataAdmissionReceipt
```

失败时发布 terminal receipt 或 `DataAdmissionGap`，不发布 current catalog 指针。

## 明确删除的旧入口

以下能力不再属于 DATA ingestion：

- typed landuse/parcel/feature/raster ingest；
- `VillageBundle` 组装；
- BSM/DLBM 派生和固定地类字段转换；
- POI 优先级聚合和 provider 间 fallback；
- provider anchor service；
- data-side fuzzy gazetteer、行政码 loader 和独立编码探测器；
- 通过缺省 parser、固定 boundary 或外部锚点补齐缺失输入。

它们已经从工作树物理删除，不提供 re-export 或兼容 shim。

## 约束

- 不在 ingestion 内决定实体身份、规划意图或候选胜负。
- 不在远程 admission 阶段发起网络请求。
- 未知 CRS、非法 geometry、缺 receipt、部分 coverage 和 provider 失败均 fail closed。
- 三家地图结果只能作为带 manifest 的 advisory observation，不能覆盖本地 DATA geometry。
