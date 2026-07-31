# KG 语义桥接：贯穿全管线的语义中枢

> **Status: [CURRENT] | Type: 语义设计 (合并文档)**
> **来源**: 本文档合并自旧版 `00_SYSTEM_DESIGN.md` §3（KG 总体）与 `KG_SPATIAL_COGNITION_DESIGN.md`（现归档至 `docs/design/03-kg-spatial-cognition-supplement.md`）。
> **定位**: KG 是 PARSE 与 EXECUTE 之间的**唯一语义桥接**（原则 4），同时也是全管线各阶段的语义查询中枢。
> **关联**: `01_LAYERED_ARCHITECTURE.md` §2.4、`03-kg-spatial-cognition-supplement.md`（谓词/命名空间详细设计）。

---

## 1. KG 四层语义模型

KG 采用四层语义模型，按"稳定度"分层：L1 最稳定（现状实体）、L4 最易变（规划产物）。

| 层 | 名称 | 内容 | 稳定度 | 状态 |
|---|---|---|---|---|
| **L1** | 静态层 | ontology + 带 geometry 的实体 | 最稳定 | [IMPLEMENTED] |
| **L2** | 语义关系层 | 空间关系（GeoSPARQL 谓词） | 中（派生可重算） | [PLANNED] |
| **L3** | 意图层 | Intent 虚拟实体 | 易变（每轮对话） | [IMPLEMENTED] 写 / [PLANNED] 查 |
| **L4** | 规划状态层 | `PlannedParcel` / `PlannedZone` / `PlannedFacility` | 易变（每版规划） | [IMPLEMENTED] |

### 1.1 L1 静态层 [IMPLEMENTED]

- 存储 ontology + 现状空间实体（BSM 现状图斑）。
- **关键约束**：KG **只存储带 geometry 的空间实体**。
- **已移出 KG 的要素**：`ThreeZone` / `ThreeLine` / `FarmlandProtection` / `EcologicalRedline` → 下沉至 `spatial_ops/bridge.py` 的 `ConstraintIndex`。理由：这些是约束类要素，其职责是空间索引与约束判定，非语义建模；放 KG 会让 KG 承担几何索引职责（违反五层架构，见 `01_LAYERED_ARCHITECTURE.md` §2.3）。

### 1.2 L2 语义关系层 [PLANNED]

- 存储实体间空间关系，使用 GeoSPARQL 谓词：
  - `sfTouches` — 相接
  - `sfWithin` — 包含于
  - `sfIntersects` — 相交
  - `sfContains` — 包含
- 关系的**定量属性**（如 `shared_boundary_m`、`centroid_distance_m`）存于 `SemanticMemoryStore`（`backend/app/modules/kg/memory.py`），与 RDF 三元组分离。
- **阻塞**：L2/L3 查询当前被 `node.py:667` 阻塞，待解封。

### 1.3 L3 意图层 [IMPLEMENTED 写 / PLANNED 查]

- 存储 Intent 虚拟实体 —— PARSE 子代理解析出的空间意图。
- **写入**：PARSE 阶段写入 L3。[IMPLEMENTED]
- **查询**：L3 查询当前阻塞。[PLANNED]

### 1.4 L4 规划状态层 [IMPLEMENTED]

- 存储 EXECUTE 产出的规划实体：`PlannedParcel` / `PlannedZone` / `PlannedFacility`。
- **写入**：EXECUTE 阶段写入 L4（`backend/app/agent/gis/agent.py:374`）。[IMPLEMENTED]
- **溯源（Provenance）**：L4 实体携带以下溯源属性：
  - `derived_from` → L1 BSM（来源现状图斑）
  - `source_spec` — 来源规范
  - `decided_by` — 决策依据
  - `operation` — 执行操作
  - `area_change_ha` — 面积变化（公顷）
  - `in_version` — 所属版本

---

## 2. KGBuilder 组合模式 [IMPLEMENTED]

KG 构建采用**组合模式** + 装饰器注册表：

```python
# backend/app/modules/kg/builder/
@kg_builder("current_landuse")
def build_current_landuse(bundle, graph):
    ...  # 从 VillageBundle 抽取实体, 写入 RDF graph
```

- `@kg_builder` 注册器按图层名注册构建函数。
- 每个构建函数只负责一种实体的 KG 写入，职责单一。
- `manager.py` 协调调用，配合 3-layer cache 避免重复构建。
- 新增图层只需新增一个 `@kg_builder` 函数，无需改 manager —— 开闭原则。

---

## 3. 各管线阶段的 KG 角色

KG 在管线各阶段扮演不同角色：现状阶段读 L1、PARSE 写 L3、EXECUTE 读 L3 写 L4。

| 阶段 | KG 操作 | 层 | 状态 | 代码位置 |
|---|---|---|---|---|
| **L1 现状分析** | 查询现状实体 | L1 | [IMPLEMENTED] | `node.py:670-680` |
| **L2/L3 文本规划** | 查询空间关系 + 意图 | L2, L3 | [PLANNED] | 阻塞于 `node.py:667` |
| **EXPLORE 桥接** | 交互式 KG 查询 | L1-L3 | [PLANNED] | — |
| **PARSE 空间意图** | 写入 Intent 虚拟实体 | L3 | [IMPLEMENTED] | PARSE 子代理 |
| **EXECUTE 布局生成** | 读 L3 意图 → 写 L4 规划实体 | L3→L4 | [IMPLEMENTED] | `execute/agent.py:374` |
| **L4 成果回写** | L4 实体 + provenance | L4 | [IMPLEMENTED] | EXECUTE |

> **PARSE 写、EXECUTE 读** 是 KG 作为语义桥接的核心闭环（原则 4）。PARSE 将文本意图物化为 L3 虚拟实体，EXECUTE 消费 L3 并产出 L4 规划实体，全程经 KG 语义化，而非直接传 raw dict。

---

## 4. KG 实例统一问题 [PLANNED]

**现状（不一致）**：
- L1 查询路径使用 `get_any_kg()` —— 取任意可用 KG 实例。
- GIS 子代理路径使用 `get_session_kg()` —— 取会话级 KG 实例。

**问题**：两条路径可能取到不同 KG 实例，导致 L1 实体与 L4 写入落在不同图上，provenance 链断裂。

**计划**：统一为 `get_session_kg()`，确保同会话内所有 KG 读写指向同一实例。L1 静态层可从全局 cache 加载入会话图，但写入与查询统一走会话实例。

**状态**：[PLANNED] 待重构。

---

## 5. GeoSPARQL 谓词与命名空间

KG 使用 GeoSPARQL 标准谓词表达空间关系：

| 谓词 | 语义 | 用途 |
|---|---|---|
| `sfTouches` | 相接（共享边界，内部不相交） | 图斑邻接关系 |
| `sfWithin` | 包含于 | 实体位于某区域内 |
| `sfIntersects` | 相交 | 通用空间相交 |
| `sfContains` | 包含 | 区域包含某实体 |

> **详细命名空间定义、谓词扩展、自定义语义谓词** 见补充文档：`docs/design/03-kg-spatial-cognition-supplement.md`。本文档仅列核心谓词，不再重复。

---

## 6. SemanticMemoryStore [IMPLEMENTED]

**位置**：`backend/app/modules/kg/memory.py`

**职责**：存储空间关系的**定量属性**，与 RDF 三元组（定性关系）分离。

| 属性 | 含义 |
|---|---|
| `shared_boundary_m` | 共享边界长度（米） |
| `centroid_distance_m` | 质心距离（米） |

**设计理由**：RDF 三元组表达"A 相接 B"是定性的；但规划决策需要"相接多长"。把定量值塞进 RDF literal 会破坏 SPARQL 查询的简洁性。故定性关系进 RDF，定量属性进 `SemanticMemoryStore`，两者以实体对为 key 关联。

---

## 7. 与 ConstraintIndex 的分工

| 职责 | 归属 | 位置 |
|---|---|---|
| 带几何空间实体的语义建模 | KG (L1-L4) | `backend/app/modules/kg/` |
| 约束类要素（三区三线等）的空间索引 | ConstraintIndex | `backend/app/modules/spatial_ops/bridge.py` |
| 空间关系定量属性 | SemanticMemoryStore | `backend/app/modules/kg/memory.py` |
| 纯几何运算 | SpatialOps | `backend/app/modules/spatial_ops/` |

> KG 不做几何索引，SpatialOps 不做语义建模。两者经 `bridge.py` 协作：SpatialOps 算关系 → KG 存语义 → MemoryStore 存定量。

---

## 8. 实现状态汇总

| 组件 | 状态 | 位置 |
|---|---|---|
| L1 静态实体 + ontology | [IMPLEMENTED] | `kg/ontology.py` |
| L1 查询 | [IMPLEMENTED] | `node.py:670-680` |
| L2 语义关系（GeoSPARQL） | [PLANNED] | 阻塞于 `node.py:667` |
| L3 意图层写入 (PARSE) | [IMPLEMENTED] | PARSE 子代理 |
| L3 查询 | [PLANNED] | 阻塞于 `node.py:667` |
| L4 规划状态写入 (EXECUTE) | [IMPLEMENTED] | `agent/gis/agent.py:374` |
| L4 provenance 溯源 | [IMPLEMENTED] | EXECUTE |
| KGBuilder @kg_builder 注册 | [IMPLEMENTED] | `kg/builder/` |
| SemanticMemoryStore | [IMPLEMENTED] | `kg/memory.py` |
| 3-layer cache | [IMPLEMENTED] | `kg/manager.py` |
| KG 实例统一 (get_any vs get_session) | [PLANNED] | 待重构 |
| EXPLORE KG 交互查询 | [PLANNED] | — |

---

## 9. 参考

- `docs/design/03-kg-spatial-cognition-supplement.md` — 谓词/命名空间详细设计
- `docs/design/01_LAYERED_ARCHITECTURE.md` §2.3, §2.4 — SpatialOps 与 KG 分层
- `backend/app/modules/kg/README.md`（如存在）— KG 模块说明
- `backend/app/modules/kg/ontology.py` — 本体定义
- `backend/app/modules/kg/manager.py` — 3-layer cache
- `backend/app/modules/kg/memory.py` — SemanticMemoryStore
- `backend/app/agent/gis/agent.py:374` — EXECUTE 写 L4
