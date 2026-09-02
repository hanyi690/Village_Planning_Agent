# DATA provider clients

本目录只包含外部 provider 的协议客户端。客户端负责受控请求和 response envelope，不负责
DATA catalog 组装、外部锚点注入、地名词典、POI 聚合或 provider 间 fallback。

## 保留的 provider

| 目录 | 能力 |
|---|---|
| `amap/` | AMap API response client：行政区、地理编码、POI、路线和受控查询 |
| `tencent/` | Tencent Map response client：区域/周边查询 |
| `tianditu/` | Tianditu API、WFS、WMTS、广东专题 MapServer/WFS client |

provider run 的边界由 `BoundaryScopeArtifact`、remote admission receipt、`ProviderAcquisitionPlan`、
`ProviderRunLeaseStore` 和 `ProviderObservationWriter` 共同构成。provider client 本身不直接
写 `data/cache/map_observations`；缓存必须由统一 writer 发布并带完整 manifest/coverage。

## 依赖

```text
provider client
  → connections / settings / provider SDK or HTTP
  → DataResult / provider result envelope
  → provider run writer
  → advisory observation cache
```

所有凭据来自 connection/settings；不写入 URL、manifest 或日志。未知 CRS、缺少 declaration、
部分 coverage 和请求失败必须保留为 failure/gap，不能产生可执行 current DATA。
