# DATA Catalog Infrastructure

本目录只保存已准入 DATA 产品的重载、provider observation cache、lease/fencing 和
advisory crosswalk。不存在按 YAML、村名或固定文件名发现 source 的运行时入口；本地
输入统一经过 `DataAdmissionFacade`，远程输入统一经过声明式 admission contract。

---

## 职责边界

**负责**：
- 从 session artifact refs 重载已准入 generic catalog
- 保存 provider run 的 observation、coverage、lease 和 fencing 证明
- 通过明确的 remote admission contract 把 API vector、WFS、MapServer、WMTS、remote raster
  声明交给 provider runtime；声明本身不触网

**不负责**：
- 不组装 session Bundle，不推断 boundary，不注入外部锚点，不把 provider 观测写回 current DATA
- 不做具体连接/驱动实现（那是 `connections/` 与 `sources/`）
- 不做类型定义、规划决策或隐式网络重试

---

## 输入/输出契约

**输入**：session DATA artifact refs、`RemoteSourceAdmissionRequest`、`BoundaryScopeArtifact`。

**输出**：`DataResourceCatalog`、`BoundaryScopeArtifact`、`ProviderRunManifest` 和
`ExternalObservationSnapshot`；未完成 coverage 的 observation 只能作为诊断，不能进入
current DATA、WM 或 Evidence 的权威事实。

**文件清单**：

| 文件 | 职责 |
|---|---|
| `provider_run_lease.py` | provider 多进程 lease、fencing、原子发布和 crash recovery |
| `../boundary_scope.py` | 从已准入 boundary 构建 BoundaryScopeArtifact |
| `../resource_catalog.py` | generic source/normalized/representation/capability catalog |

---

## 依赖方向

```
catalog/ → app/data/ingestion（provider transports/adapters）
        → app/contracts/data（remote/run contracts）
        → app/data/model（仅 BBox 等基础值对象）
```

- 允许：`app/contracts`、`app/data/` 内部各子包、`app.utils`
- 禁止：`agent` / `services` / `tools`；禁止通过固定文件名推断 boundary 或绕过 admission。

---

## 禁止行为

- 绕过 admission/lease 直接写 observation cache
- 在 catalog 内做 LLM 调用或规划决策
- 每次业务读取隐式重新抓取外部锚点（设计文档 §2.2：外部锚点不得隐式重抓）

上传和 session bootstrap 必须使用
`DataAdmissionFacade` 的 receipt、catalog index 以及 source/normalized/representation/
capability 四类 component products；缺失任一 component 必须 fail closed。
- 把 provider observation 直接升级为 current DATA geometry 或 World Model 事实
