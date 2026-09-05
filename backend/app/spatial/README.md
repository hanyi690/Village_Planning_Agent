# Spatial 空间运行时

`backend/app/spatial/` 提供 DATA 之后的确定性空间计算，不再负责输入发现、文件名映射或
旧 Bundle 组装。正式输入由 `DataAdmissionFacade` 归一化，空间运行时只接收
`SpatialWorkspace`、`DataResourceCatalog`、BoundaryScope 或 WM/Evidence 的显式引用。

## 目录职责

| 目录 | 当前职责 |
| --- | --- |
| `model/` | `SpatialWorkspace`、CRS/面积/几何工具、只读空间计算和规划所需的显式几何操作 |
| `grounding/` | `resolver.SpatialResolver`：消费 DATA normalized representation、WM current view 和 Evidence packet，生成带 lineage 的候选；不读取 Bundle |
| `change/` | 已有空间产品的变更比较 |
| `delivery/` | 交付快照的土地平衡与显示样式 |
| `validation/` | 几何、指标和约束冲突检查 |
| `terrain/` | DEM 的显式 source/ref 校验和地形证据 |
| `network/` | 由 DATA 道路线要素构建可重放的网络 snapshot、路线和服务区计算 |
| `relations/` | 在显式空间输入上执行 bounded topology/network relation |

## 正式入口

- `app.spatial.model.workspace.SpatialWorkspace`：承载当前 DATA catalog 的只读空间视图；
- `app.spatial.grounding.resolver.SpatialResolver`：接收闭集
  `SpatialQueryDraft/SpatialReferenceSpec`，从 DATA/WM/Evidence 的显式引用生成候选；
- `app.spatial.network.network_graph.build_network_graph`：接收带 DATA feature digest 的
  道路序列，生成可重放的 `NetworkGraphSnapshot`；
- `app.spatial.validation` 和 `app.spatial.terrain`：只消费已声明、已归一化的空间产品。

## Geometry policy

`Polygon` 表示一个单独的二维面，包含一个外环及可选内环；`MultiPolygon` 表示由多个
Polygon 组成的同质二维面集合。二者在 DATA 中属于同一个 polygon surface family，但并不
意味着可以无审计地互相转换。`make_valid` 只有在修复结果有效、范围合法、仍处于允许
surface family 且审计 trace 完整时才发布 normalized view；混合维度、低维坍缩或无法确认
的结果保持 read-only/UNRESOLVED，不能成为可执行面。

native geometry 永不被空间操作覆盖。WM/Evidence 通过 resource/representation/source
digest 回到 DATA 取 normalized geometry；外部地图 observation 只作为 advisory evidence，
不会写回本地 geometry 或构造 WorldEntity。

## 已删除的旧边界

旧的 `spatial/query`、Bundle grounding、Bundle binder、coordinate identity、旧 topology
适配器以及 typed model registry 已物理删除。当前代码不得重新引入：

- `VillageBundle` 作为 DATA 输入；
- BSM/DLBM 自动派生为通用空间 identity；
- 通过文件名猜测 layer 或 boundary；
- 通过 centroid/nearest point 伪造可执行 geometry；
- 未带 source snapshot、feature digest 或 representation ref 的空间结果。
