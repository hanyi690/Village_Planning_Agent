# Data Catalog — 声明式数据源编排

> **定位**：数据层 **Layer 3（声明式编排）**。`sources.yaml` 声明物理数据源，`DataCatalog` 统一加载并组装 `VillageBundle`。`app.data` 的唯一入口。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：
- 读取 `sources.yaml`（连接 + 数据源声明，单一真相源），经 `DriverRegistry` 实例化 Driver
- `load_village_bundle()` / `load_village_bundle_async()`：按 entry 的 `ingest.adapter` 分派到 `adapters/`，把原始数据组装为形态优先的 typed `VillageBundle`
- 按名称获取单个数据源：`get_source(...).fetch() -> DataResult`
- 外部锚点补全（`external_anchors.py`）与去重（`dedup.py`）

**不负责**：
- 不做具体连接/驱动实现（那是 `connections/` 与 `sources/`）
- 不做类型定义（那是 `schema/`）
- 不缓存 session 级 bundle（那是 `services/session_bundle.py`）

---

## 输入/输出契约

**输入**：`catalog/sources.yaml`（`CatalogConfig` / `ConnectionConfig` / 各 `*SourceConfig` Pydantic 模型，`config.py`）。

**输出**：

| 入口 | 输出 | 说明 |
|---|---|---|
| `DataCatalog.get_source(name).fetch()` | `DataResult`（`data/contracts.py`） | 单源抓取 |
| `DataCatalog.load_village_bundle(name)` | `VillageBundle` | 全图层 typed 数据束 |

**文件清单**：

| 文件 | 职责 |
|---|---|
| `catalog.py` | `DataCatalog` 主类：加载配置 → 初始化 Driver/Connection → 查询 → bundle 组装（含 `_merge_geojson_into_bundle`） |
| `config.py` | Pydantic 配置模型（支持 v1.0 / v2.0 YAML） |
| `dedup.py` | 外源锚点去重（优先级：本地 → WFS → AMap POI → 百度；`(name_norm, lat_3, lon_3, type_key)` 唯一键） |
| `external_anchors.py` | 4 阶段外源锚点管线：collect → normalize → dedup → inject（GCJ02/BD09 → WGS84 归一） |
| `sources.yaml` | 数据源物理配置（连接 + 源声明） |

---

## 依赖方向

```
catalog/ → data/connections（连接）、data/sources（驱动）、data/adapters（ingest 策略）
        → modules/schema（VillageBundle / 类型）/ modules/schema.advisory_crosswalks
        → app.utils（logger 等）
```

- 允许：`schema`、`data/` 内部各子包、`app.utils`
- 禁止：`agent` / `services` / `api` / `tools`；反向被 `kg` 直接 import（kg 经 `BundleAssemblyPort` 注入）

---

## 禁止行为

- 绕过 `DataCatalog` 直接 new Driver / 手工拼 URL（历史"三套并行抽象"病灶，已统一）
- 在 catalog 内做 LLM 调用或规划决策
- 每次业务读取隐式重新抓取外部锚点（设计文档 §2.2：外部锚点不得隐式重抓）
- 直接修改 `sources.yaml` 之外的自定义 schema 字段 —— 配置必须经 Pydantic 校验
