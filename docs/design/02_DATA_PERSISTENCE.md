# 数据持久化策略

> **Status: [CURRENT] | Type: 持久化设计**
> **覆盖**: 各数据形态的落盘策略、从散落 GeoJSON 到 GeoPackage 的迁移路径、实现状态。
> **关联**: `01_LAYERED_ARCHITECTURE.md`（五层）、`03_KG_SEMANTIC_BRIDGE.md`（KG 持久化）。

---

## 1. 持久化总览

系统按**数据语义**而非"统一一种存储"来分型持久化。一刀切存储会导致：栅格无法进 SQLite、RDF 三元组用关系表表达会丢语义、规划报告需要版本追踪而图斑不需要。

| 数据类型 | 存储介质 | 技术 | 状态 |
|---|---|---|---|
| 空间矢量数据 | GeoPackage (`.gpkg`) | SQLite + 空间扩展 | [IMPLEMENTED] |
| 元数据 / 编目 | SQLite 关系表 | SQLModel async | [IMPLEMENTED] |
| 知识图谱 (KG) | RDFLib + SQLite backend | triples 持久化 | [IMPLEMENTED] |
| 会话状态 | SQLite | LangGraph Checkpointer | [IMPLEMENTED] |
| 规划报告 | 文件系统 + SQLite 索引 | `DimensionReport` 表 + 文件 | [IMPLEMENTED] |
| 成果输出 | 文件系统 | GeoJSON / GDB | [IMPLEMENTED] |

---

## 2. 分型策略与理由

### 2.1 空间矢量数据 → GeoPackage [IMPLEMENTED]

| 项 | 内容 |
|---|---|
| 介质 | GeoPackage (`.gpkg`) |
| 底层 | SQLite + 空间扩展 |
| 理由 | 单文件、跨平台、支持多图层、空间索引、事务；远优于散落 GeoJSON |
| 对应层 | Data 层 persist 阶段 |

**GeoPackage vs GeoJSON**：
- GeoJSON 是文本、无空间索引、大文件慢、多文件难管理。
- GeoPackage 是二进制 SQLite、内置 R-Tree、单文件多图层、支持事务回滚。
- 规划成果需汇交为数据库，GeoPackage 天然对齐 DB14/T 2979-2024。

### 2.2 元数据 / 编目 → SQLite 关系表 [IMPLEMENTED]

| 项 | 内容 |
|---|---|
| 介质 | SQLite 关系表 |
| 表 | `data_sources` · `layer_registry` |
| ORM | SQLModel，async 操作 |
| 位置 | `backend/app/database/` |

**职责**：记录"有哪些数据源、每个图层在哪、什么类型、何时入库"。是 Data 层 `DataCatalog` 的持久化后盾。`layer_registry` 与 GeoPackage 图层一一对应。

### 2.3 知识图谱 (KG) → RDFLib + SQLite backend [IMPLEMENTED]

| 项 | 内容 |
|---|---|
| 介质 | SQLite（RDFLib backend） |
| 内容 | RDF triples 持久化 |
| 位置 | `backend/app/modules/kg/manager.py` |
| 缓存 | 3-layer cache（manager.py） |

**理由**：KG 是语义结构（主-谓-宾三元组），强行用关系表表达会丢失 SPARQL 查询能力与语义推理。RDFLib 原生支持 SQLite backend，三元组可持久化、可查询。详见 `03_KG_SEMANTIC_BRIDGE.md`。

### 2.4 会话状态 → SQLite (LangGraph Checkpointer) [IMPLEMENTED]

| 项 | 内容 |
|---|---|
| 介质 | SQLite |
| 机制 | LangGraph Checkpointer |
| 位置 | `backend/app/services/checkpoint.py` |
| 内容 | Agent 主图 5 节点状态、对话历史、中间产物 |

**理由**：LangGraph 原生提供 Checkpointer 抽象，SQLite backend 支持断点续跑、状态回放、多会话隔离。无需自研会话持久化。

### 2.5 规划报告 → 文件系统 + SQLite 索引 [IMPLEMENTED]

| 项 | 内容 |
|---|---|
| 正文 | 文件系统（按 `session_id` / 维度组织） |
| 索引 | SQLite `DimensionReport` 表 |
| 服务 | `backend/app/services/report_store.py` |
| 能力 | 版本追踪、最新报告查询、图层摘要、批量保存 |

**理由**：报告正文是长文本/结构化文档，放文件系统便于导出与人工查阅；但需按维度、版本、会话检索，故用 SQLite 建索引。正文与索引分离 = 文件存内容、DB 存元数据。

**ReportStore API**（`backend/app/services/report_store.py`）：
- `get_layer_summaries(session_id, layer)` — 取某会话某图层的摘要
- `get_latest_report(session_id, dim_key)` — 取某维度最新版本报告
- `bulk_save(...)` — 批量保存（含版本号自增）
- 版本追踪 — 同一 `dim_key` 多版本，查询默认取最新

### 2.6 成果输出 → 文件系统 [IMPLEMENTED]

| 项 | 内容 |
|---|---|
| 介质 | 文件系统 |
| 格式 | GeoJSON / GDB（File Geodatabase） |
| 场景 | 最终汇交成果导出、与外部 GIS 软件交互 |

**理由**：汇交成果需符合规范格式（一图一表一规则的"图"常为 GDB/GeoJSON）。文件系统是跨系统交换的最通用介质。

---

## 3. 迁移路径：散落 GeoJSON → GeoPackage

### 3.1 现状问题（迁移前） [DEPRECATED]

```
[DEPRECATED 旧态]
workspace/
├── village_a/
│   ├── current_landuse.geojson      ← 散落、无索引、无元数据
│   ├── roads.geojson
│   └── three_zone.geojson
└── village_b/
    └── ... (重复结构，无法统一查询)
```

问题：
1. 无空间索引，相交查询全表扫描。
2. 无元数据，不知道图层来源、坐标系、入库时间。
3. 多文件难管理，跨村查询需遍历目录。
4. 无事务，写入中断会损坏。

### 3.2 目标态（迁移后） [IMPLEMENTED]

```
[IMPLEMENTED 新态]
workspace/
├── data/
│   └── {village_id}.gpkg            ← 单文件多图层 + R-Tree 空间索引
│       ├── current_landuse          (Polygon 图层)
│       ├── roads                    (Line 图层)
│       └── three_zone               (Polygon 图层)
├── catalog.db                       ← SQLite 元数据库
│   ├── data_sources                 (数据源登记)
│   └── layer_registry               (图层登记, 指向 gpkg 图层)
└── sessions/
    └── {session_id}.db              ← 会话状态 + KG + 报告索引
```

### 3.3 迁移步骤

```
Step 1 [IMPLEMENTED]: 建 GeoPackage 骨架
    Data 层 persist 阶段新增 .gpkg 写入适配器
    → 矢量数据写入对应图层，建空间索引

Step 2 [IMPLEMENTED]: 建元数据库
    backend/app/database/models.py 定义 data_sources / layer_registry
    → 每入一个图层, 同步写一条 layer_registry 记录

Step 3 [IMPLEMENTED]: 旧 GeoJSON 导入
    Data 层 fetch 阶段识别 .geojson → typify → persist 进 .gpkg
    → 旧文件保留为原始备份, 不再作为运行时数据源

Step 4 [DEPRECATED]: 清理散落文件
    迁移完成后, 旧 .geojson 仅作归档, 运行时不再读取
```

### 3.4 迁移验收

- [IMPLEMENTED] 所有运行时矢量读取经 GeoPackage（经 Data 层）。
- [IMPLEMENTED] `layer_registry` 与 `.gpkg` 图层一一对应。
- [DEPRECATED] 散落 GeoJSON 不再作为运行时数据源。

---

## 4. 数据库模型实现

**位置**：`backend/app/database/`
**文件**：`models.py`（SQLModel 定义）· `operations.py`（async 操作）· `engine.py`（引擎）

**核心表**：
- `data_sources` — 数据源登记（来源、类型、入库时间）
- `layer_registry` — 图层登记（图层名、所属 gpkg、类型、坐标系）
- `DimensionReport` — 规划报告索引（session_id、dim_key、version、文件路径）

**技术栈**：SQLModel（SQLAlchemy + Pydantic），async 操作。与 Schema 层的 Pydantic 模型共享类型基础，但数据库模型面向持久化，Schema 模型面向业务——两者分离，DB 模型可 import Schema，Schema 不 import DB 模型（守依赖方向）。

---

## 5. 实现状态矩阵

| 组件 | 状态 | 位置 |
|---|---|---|
| GeoPackage 持久化 | [IMPLEMENTED] | Data 层 persist |
| 元数据库 (data_sources / layer_registry) | [IMPLEMENTED] | `backend/app/database/models.py` |
| KG triples 持久化 | [IMPLEMENTED] | `backend/app/modules/kg/manager.py` |
| 会话 Checkpointer | [IMPLEMENTED] | `backend/app/services/checkpoint.py` |
| ReportStore (版本追踪) | [IMPLEMENTED] | `backend/app/services/report_store.py` |
| GeoJSON / GDB 输出 | [IMPLEMENTED] | Data 层 / Agent gis 层 |
| 散落 GeoJSON 运行时读取 | [DEPRECATED] | 迁移完成, 仅归档 |

---

## 6. 参考

- `backend/app/database/models.py` — 数据库模型
- `backend/app/database/operations.py` — async 操作
- `backend/app/services/report_store.py` — ReportStore
- `backend/app/services/checkpoint.py` — 会话 Checkpointer
- `backend/app/modules/kg/manager.py` — KG 3-layer cache + 持久化
- `docs/design/01_LAYERED_ARCHITECTURE.md` — 五层架构
- `docs/design/03_KG_SEMANTIC_BRIDGE.md` — KG 语义桥接
