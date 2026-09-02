# Data Catalog — 声明式数据源注册与受控读取

> `DataCatalog` 只负责读取经过 Pydantic 校验的 `sources.yaml`，初始化 driver，并执行
> 显式、边界受控的 source query。DATA 产品、准入 receipt、规范化 representation 和
> artifact 持久化统一由 `DataAdmissionFacade` 负责；旧 Bundle 组装路径已物理删除。

---

## 职责边界

**负责**：
- 读取 `sources.yaml`，经 `CatalogConfig` 与 `DriverRegistry` 校验/实例化连接和 driver
- 按名称获取单个声明式 source：`get_source(...).fetch() -> DataResult`
- 对显式 bbox/layer 查询进行 bounded dispatch；远程 source 的 admission 必须先通过
  `RemoteSourceAdmissionRequest`，provider run 再提交 coverage proof

**不负责**：
- 不组装 session Bundle，不推断 boundary，不注入外部锚点，不把 provider 观测写回 current DATA
- 不做具体连接/驱动实现（那是 `connections/` 与 `sources/`）
- 不做类型定义、规划决策或隐式网络重试

---

## 输入/输出契约

**输入**：`catalog/sources.yaml`（`CatalogConfig` / `ConnectionConfig` / 各 `*SourceConfig` Pydantic 模型，`config.py`）。

**输出**：

| 入口 | 输出 | 说明 |
|---|---|---|
| `DataCatalog.get_source(name).fetch()` | `DataResult`（`data/contracts.py`） | 单源抓取 |
| `DataCatalog.find_sources_by_layer_type(type)` | driver 列表 | 显式 source registry 查询 |

**文件清单**：

| 文件 | 职责 |
|---|---|
| `catalog.py` | `DataCatalog` 主类：加载配置 → 初始化 Driver/Connection → 显式查询 |
| `config.py` | Pydantic 配置模型（支持 v1.0 / v2.0 YAML） |
| `provider_run_lease.py` | provider 多进程 lease、fencing、原子发布和 crash recovery |
| `../boundary_scope.py` | 从已准入 boundary 构建 BoundaryScopeArtifact |
| `../resource_catalog.py` | generic source/normalized/representation/capability catalog |
| `sources.yaml` | 数据源物理配置（连接 + 源声明） |

---

## 依赖方向

```
catalog/ → app/data/ingestion（connections/sources/adapters）
        → app/contracts/data（remote/run contracts）
        → app/data/model（仅 BBox 等基础值对象）
```

- 允许：`app/contracts`、`app/data/` 内部各子包、`app.utils`
- 禁止：`agent` / `services` / `tools`；禁止通过固定文件名推断 boundary 或绕过 admission。

---

## 禁止行为

- 绕过 `DataCatalog` 直接 new Driver / 手工拼 URL（历史"三套并行抽象"病灶，已统一）
- 在 catalog 内做 LLM 调用或规划决策
- 每次业务读取隐式重新抓取外部锚点（设计文档 §2.2：外部锚点不得隐式重抓）

上传和 session bootstrap 必须使用
`DataAdmissionFacade` 的 receipt、catalog index 以及 source/normalized/representation/
capability 四类 component products；缺失任一 component 必须 fail closed。
- 直接修改 `sources.yaml` 之外的自定义 schema 字段 —— 配置必须经 Pydantic 校验
