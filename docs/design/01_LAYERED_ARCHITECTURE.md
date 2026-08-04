# 五层架构设计：Schema ← Data ← SpatialOps ← KG ← Agent

> **Status: [CURRENT] | Type: 架构骨架设计**
> **权威链**: 本文档取代旧版架构表述（含 `00_SYSTEM_DESIGN.md` §0.2 与 `backend/app/modules/schema/README.md:3` 中的"四层架构"说法）。
> **关键修正**: 旧文档称"四层"是因将 SpatialOps 隐式并入 KG。实测 `spatial_ops` 层独立于 KG，故修正为**五层**。详见 §6。

---

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Agent 层 (5)                                 │
│   graph.py(5-node) / routing.py / state.py                          │
│   conversation/  analysis/  completion/  tools/  gis/(parse+exec)    │
│        │                                  │                          │
│        └───────── consumes ───────────────┘                          │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ depends on
┌───────────────────────────▼──────────────────────────────────────────┐
│                         KG 层 (4)                                    │
│   rdflib RDF graph  ·  builder/@kg_builder  ·  queries/(SPARQL)      │
│   ontology.py  ·  manager.py(3-layer cache)  ·  memory.py            │
│   L1 static / L2 spatial-rel / L3 intent / L4 planned                │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ depends on
┌───────────────────────────▼──────────────────────────────────────────┐
│                     SpatialOps 层 (3)  [独立几何层]                  │
│   geometry ops  ·  spatial index  ·  relation computation            │
│   bridge.py: ConstraintIndex + cross-type relations                  │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ depends on
┌───────────────────────────▼──────────────────────────────────────────┐
│                         Data 层 (2)                                  │
│   lifecycle: fetch -> validate -> typify -> cache -> persist         │
│   catalog/  ·  sources.yaml + DataCatalog  ·  VillageBundle          │
│   connections/  ·  adapters/  ·  documents/                          │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ depends on
┌───────────────────────────▼──────────────────────────────────────────┐
│                       Schema 层 (1)  [零依赖]                        │
│   types/  ·  encodings/  ·  contracts/  ·  output/  ·  utils/        │
│   Vector(Point/Line/Polygon) · Raster · Table · Document             │
│   Pydantic v2 BaseModel                                              │
└──────────────────────────────────────────────────────────────────────┘
        ▲ Schema imports nothing. All layers import Schema (directly or transitively).
        ▲ 依赖方向严格单向: 上层 → 下层, 禁止反向。
```

---

## 2. 各层职责

### 2.1 Schema 层（1）— 类型契约层 [IMPLEMENTED]

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/modules/schema/` |
| **实现状态** | v4.8.1 落地完成（见 `backend/app/modules/schema/README.md:7`） |
| **依赖** | **零依赖**。不 import Data / SpatialOps / KG / Agent / Tools 中的任何模块。 |
| **技术栈** | Pydantic v2 `BaseModel` |
| **5 个子包** | `types/` · `encodings/` · `contracts/` · `output/` · `utils/` |

**职责**：定义空间要素的类型、编码体系、契约、输出规范。四种数据形态优先于语义角色：

- **Vector** — `PointFeature` / `LineFeature` / `PolygonFeature`
- **Raster** — `RasterDataset`
- **Table** — `TableDataset`
- **Document** — `Document`

> 设计哲学：**形态优先容器**（见 `schema/README.md:5`）。`VillageBundle` 按形态 `LayerGroup` 组织，`bundle.add()` 经 `_bundle_key_for()` 路由至 `GIS_LAYER_REGISTRY`（YAML-driven）。

### 2.2 Data 层（2）— 数据生命周期层 [IMPLEMENTED]

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/modules/data/` |
| **依赖** | → Schema |
| **核心抽象** | `DataCatalog` + `sources.yaml` + `VillageBundle` |
| **子包** | `catalog/` · `sources/` · `connections/` · `adapters/` · `documents/` |

**职责**：数据的**操作**生命周期 —— `fetch -> validate -> typify -> cache -> persist`。系统唯一数据入口（原则 3：单一入口）。KG 不直接读 GeoJSON，所有原始数据经 Data 层接入并转化为 Schema 类型化模型。

### 2.3 SpatialOps 层（3）— 独立几何运算层 [IMPLEMENTED]

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/modules/spatial_ops/` |
| **依赖** | → Schema, Data |
| **核心文件** | `bridge.py` — `ConstraintIndex` + 跨类型关系 |
| **能力** | geometry ops · spatial index · relation computation |

**职责**：纯几何运算与空间索引。**关键设计决策**：将 `ThreeZone` / `ThreeLine` / `FarmlandProtection` / `EcologicalRedline` 等**约束类要素**移出 KG，下沉至 `ConstraintIndex`（空间索引）。KG 仅存储**带几何的空间实体**。详见 `03_KG_SEMANTIC_BRIDGE.md` §3。

> 这是"四层→五层"修正的根源：SpatialOps 独立于 KG，不能被并入 KG 层。

### 2.4 KG 层（4）— 语义知识图层 [IMPLEMENTED + PLANNED]

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/modules/kg/` |
| **依赖** | → Schema, Data, SpatialOps |
| **技术栈** | rdflib RDF graph + SQLite backend |
| **核心文件** | `ontology.py` · `manager.py`(3-layer cache) · `memory.py`(`SemanticMemoryStore`) · `builder/`(@kg_builder) · `queries/`(SPARQL+semantic+cognition) |

**职责**：四层语义模型 ——
- **L1** 静态实体（ontology + 带 geometry 的实体）
- **L2** 空间关系（GeoSPARQL `sfTouches` / `sfWithin` / `sfIntersects`）
- **L3** 意图层（Intent 虚拟实体，PARSE 写入）
- **L4** 规划状态层（`PlannedParcel` / `PlannedZone` / `PlannedFacility`，EXECUTE 写入）

> KG 是 PARSE 与 EXECUTE 之间的**唯一语义桥接**（原则 4）。详见 `03_KG_SEMANTIC_BRIDGE.md`。

### 2.5 Agent 层（5）— 编排与对话层 [IMPLEMENTED + PLANNED]

| 项 | 内容 |
|---|---|
| **位置** | `backend/app/agent/` |
| **依赖** | → Schema, Data, SpatialOps, KG |
| **主图** | `graph.py` — 6-node main graph |
| **支撑** | `routing.py` · `state.py` |
| **子模块** | `conversation/` · `analysis/` · `explore/` · `completion/` · `tools/` · `gis/`(parse+execute 子代理) |

**职责**：6 节点主图编排、路由、状态管理。`gis/` 下含 PARSE 与 EXECUTE 两个子代理，分别向 KG 写入 L3 与 L4。

---

## 3. Schema 与 Data 为何不是冗余

这是最常见的误解。两者职责正交：

| 维度 | Schema 层 | Data 层 |
|---|---|---|
| **本质** | **定义**（Definition） | **操作**（Operation） |
| **回答什么** | "数据是什么形状、什么类型、如何编码" | "数据从哪来、如何校验、如何缓存、如何落盘" |
| **含逻辑** | 类型约束、字段契约、编码映射 | fetch / validate / typify / cache / persist |
| **是否变** | 类型稳定，极少变动 | 数据频繁流入流出 |
| **类比** | 数据库 Schema (DDL) | ETL Pipeline + Catalog |

**反例验证**：若合并两层，则"一个 SpatialFeature 类型定义"会耦合"它从 GeoJSON 还是 WFS 加载"——这违反单一职责。Schema 描述**形状**，Data 描述**流程**，两者必须分离。

---

## 4. 依赖规则

```
规则 1 (单向):  Agent → KG → SpatialOps → Data → Schema
规则 2 (零依赖): Schema 不 import 任何其他层。仅依赖 Pydantic / stdlib。
规则 3 (无反向): 下层禁止 import 上层。
                例: KG 不得 import agent.*；Data 不得 import kg.*。
规则 4 (跨层禁跳): 理论上 Agent 不应直接读 Data 层文件
                   （经 KG / SpatialOps 间接消费），但当前 gis 子代理
                   存在直读 —— 标记 [PLANNED] 收敛。
规则 5 (Schema-only 共享): 跨层传递的数据结构必须是 Schema 层定义的类型，
                          禁止 raw dict 跨层流转（原则 1: Schema-First）。
```

> 违反检测：CI 应加入 `import-linter` 契约，断言依赖方向。`backend/app/modules/schema/` 的 `__init__.py` 可加 `__all__` 白名单以防止意外引入依赖。

---

## 5. 实现状态矩阵

| 层 | 状态 | 备注 |
|---|---|---|
| Schema | [IMPLEMENTED] | v4.8.1 落地，四形态 + VillageBundle |
| Data | [IMPLEMENTED] | lifecycle + DataCatalog + VillageBundle |
| SpatialOps | [IMPLEMENTED] | bridge.py / ConstraintIndex 独立 |
| KG | [IMPLEMENTED] + [PLANNED] | L1/L4 已实现；L2/L3 查询待补（见 `03_KG_SEMANTIC_BRIDGE.md`） |
| Agent | [IMPLEMENTED] + [PLANNED] | 主图已实现；跨层直读待收敛 |

---

## 6. "四层" vs "五层" 争议澄清

**争议来源**：
- `00_SYSTEM_DESIGN.md` §0.2 原则 2 写"Schema ← Data ← KG ← Agent"（四层）。
- `backend/app/modules/schema/README.md:3` 写"四层架构"。
- 但 `backend/app/modules/spatial_ops/` 作为独立模块存在，`bridge.py` 的 `ConstraintIndex` 与 KG 解耦。

**结论**：**五层正确**。

**理由**：
1. SpatialOps 是纯几何运算层，不依赖 rdflib / KG 语义。
2. KG 将约束类要素下沉至 `ConstraintIndex`，证明两者职责正交。
3. 若强行并入 KG，则 KG 同时承担"语义建模"与"几何索引"双重职责，违反单一职责。
4. 旧文档写"四层"是因早期 SpatialOps 隐式存在于 KG 内部，重构后已独立但文档未同步。

**勘误**：`schema/README.md:3` 与 `00_SYSTEM_DESIGN.md` §0.2 的"四层"表述 [DEPRECATED]，以本文档为准。

---

## 7. 参考

- `backend/app/modules/schema/README.md` — Schema 层类型契约
- `docs/design/00_SYSTEM_DESIGN.md` §0.2 — 设计原则（依赖方向表述需勘误）
- `docs/design/02_DATA_PERSISTENCE.md` — 各层持久化策略
- `docs/design/03_KG_SEMANTIC_BRIDGE.md` — KG 跨阶段语义桥接
- `docs/design/03-kg-spatial-cognition-supplement.md` — KG 谓词/命名空间补充
