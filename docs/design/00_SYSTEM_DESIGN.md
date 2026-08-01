# 村庄规划智能系统 - 总体设计文档

> **Status: [CURRENT] | Type: North-Star Design | 覆盖文本+空间一条闭环**
> **Archived**: 旧版 `00_SYSTEM_DESIGN_v4.8.md` 已迁入 `_archive/gis-archive/`，本文档为重构版。

---

## 第零部分：设计总纲

### 0.1 系统定位

**一句话定义**：

> 给定村庄现状资料（三调数据、三区三线、DEM/DOM、上位规划、村民需求），系统产出
> **可解释、可汇交**的村庄规划成果包（一图一表一规则 + 数据库），过程中文本规划与
> 空间分析双向闭环。

系统由**一条闭环管线**组成，而非两条平行线：

```
NL输入 -> L1现状分析(12维)                              -> L2规划定位(4维) -> L3详细规划(12维)
    │  ↑ EXPLORE提供KG空间认知L1产出优化对应实体的语义注解    │  ↑ EXPLORE提供约束校核  │  ↑ EXPLORE提供现状结构认知
    │  (替代_optimize_semantics)  │  (治断点②)             │  (治断点②)
    -> EXPLORE桥接(读L1+L2+L3 + KG交互 + 产出概要索引)
    -> PARSE空间意图（读取L1，L3末端的结构内容来执行优化KG/生成intent） -> EXECUTE布局生成 -> L4成果回写
    -> EXPLORE校核(读L4 PlannedState + L3文本对账)
    -> 文本/几何一致输出
    │           │                │              │                │              │
    │           └── KG认知 ──────┴──────────────┘              └── KG桥接 ─────┘
    │                    (EXPLORE贯穿全阶段)                       (PARSE写/EXECUTE读/L4回写)
    └── provenance 贯通
```

> **核心约束**：系统是规划助手，不做规划决策。不确定性由人消除。

### 0.2 设计原则

| # | 原则                           | 含义                                                                                                                                                                                           |
| - | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 | **Schema-First**         | 所有空间要素先定义类型再编码，下游只消费类型化模型，禁止 raw dict                                                                                                                              |
| 2 | **单向依赖**             | 依赖方向：Schema ← Data ← SpatialOps ← KG ← Agent，Schema 不依赖任何层                                                                                                                     |
| 3 | **单一入口**             | 数据进入系统只有一个入口（Data 层），KG 不直接读 GeoJSON 文件                                                                                                                                  |
| 4 | **语义中间态**           | KG 是 PARSE 与 EXECUTE 之间的唯一语义桥接，PARSE 写入、EXECUTE 读取                                                                                                                            |
| 5 | **闭环反馈**             | 校验失败 -> 约束调整 -> 重新执行，文本分析结果可回灌空间修订                                                                                                                                   |
| 6 | **可解释溯源**           | 每个图斑变更可追溯到来源文本，每条管制规则可追溯到上位依据                                                                                                                                     |
| 7 | **Explore 空间认知引擎** | EXPLORE 是贯穿规划全周期的可复用能力：为 L1/L2/L3 维度分析动态提供 KG 空间认知（替代静态 DIM_KG_MAP），L3 完成后作为桥接节点产出 ExplorationInstruction + ReportSummaryIndex，校核轮读 L4 对账 |

### 0.3 官方标准对齐

| 标准                  | 全称                                         | 系统对齐                           |
| --------------------- | -------------------------------------------- | ---------------------------------- |
| 自然资发〔2023〕234号 | 国土空间调查、规划、用途管制用地用海分类指南 | 用地分类编码体系（YDYHFL）         |
| GB/T 21010-2017       | 土地利用现状分类                             | 三调国标编码体系                   |
| GB/T 13923-2022       | 基础地理信息要素分类与代码                   | 10位数字层次码                     |
| DB14/T 2979-2024      | 村庄规划数据库规范                           | 数据库内容、要素分类代码、数据分层 |
| 广东省住建厅 (2018)   | 广东省村庄规划编制指引（试行）               | 四阶段工作流、一图一表一规则成果   |
| DB4407/T 105-2023     | 村庄建设规划管制规则                         | 6大类管制规则模板                  |
| 住建部 (2014)         | 村庄规划用地分类指南                         | V/N/E 三分类                       |
| 三区三线              | 全国国土空间规划                             | 生态/农业/城镇空间 + 三线边界      |

### 0.4 文档说明与权威链

```
代码 (backend/app/**)                     ← 最终事实源
  ↑
design/00_SYSTEM_DESIGN.md                ← North Star（本文档）
  ↑
design/01-10_*.md                         ← 设计问题展开
  ↑
architecture/*.md                         ← 技术实现映射（引用 design/ 章节号）
  ↑
根 README.md                              ← 对外门面（只链接不重复）
```

- `design/` 回答"为什么这么设计"
- `architecture/` 回答"代码在哪里、怎么跑"
- `audits/` 和 `proposals/` 为诊断参考和未落地提案，不参与权威链

### 0.5 实现状态标记

本文档体系使用三态标记区分实现与计划：

| 标记              | 含义                                     |
| ----------------- | ---------------------------------------- |
| `[IMPLEMENTED]` | 代码已实现且可用，引用`file:path:line` |
| `[PLANNED]`     | 有设计但未实现/部分实现，标注缺口        |
| `[DEPRECATED]`  | 已废弃或待清理                           |

详见 `design/10_IMPLEMENTATION_STATUS.md`。

---

## 第一部分：分层架构（-> 详见 01_LAYERED_ARCHITECTURE）

### 1.1 五层架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│  Agent Layer (理解 + 执行)                                        │
│  ┌──────────────┐  ┌──────────────────┐  ┌────────────────────┐ │
│  │ EXPLORE Agent│  │ PARSE Agent      │  │ EXECUTE Agent      │ │
│  │ 文本探索+KG  │  │ 意图结构化       │  │ 布局生成+KG回写 语义注解   │ │
│  │ 顶层桥接节点 │  │ gis_agent内      │  │ gis_agent内        │ │
│  └──────┬───────┘  └────────┬─────────┘  └─────────┬──────────┘ │
│         │ writes             │ reads                │ reads/writes│
├─────────┼────────────────────┼──────────────────────┼────────────┤
│         ▼                    ▼                      ▼            │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ KG Layer (语义桥接)                                        │ │
│  │ L1 静态(Ontology+编码) | L2 语义(关系+约束)                │ │
│  │ L3 易失(Intent) | L4 规划成果(PlannedState)                │ │
│  │ RDFLib Graph + SPARQL + SemanticMemoryStore                │ │
│  └──────────────────────────┬─────────────────────────────────┘ │
│         ┌───────────────────┼───────────────────┐               │
│         ▼                   ▼                   ▼               │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐      │
│  │ Schema Layer │  │ Data Layer       │  │ Spatial Ops  │      │
│  │ 类型契约     │  │ 数据生命周期     │  │ 空间计算     │      │
│  │ 编码体系     │  │ 获取->类型化     │  │ 几何运算     │      │
│  │ 输出规范     │  │ ->缓存->持久化   │  │ 关系计算     │      │
│  │ 零依赖       │  │ depends: Schema  │  │ depends:     │      │
│  │              │  │                  │  │ Schema+Data  │      │
│  └──────────────┘  └──────────────────┘  └──────────────┘      │
└──────────────────────────────────────────────────────────────────┘
```

> **口径统一**：五层 `Schema ← Data ← SpatialOps ← KG ← Agent`。
> 旧文档中"四层"（缺 SpatialOps）已修正，SpatialOps 是独立层（`backend/app/modules/spatial_ops/`）。

### 1.2 各层职责摘要

| 层         | 位置                     | 职责                                        | 依赖                |
| ---------- | ------------------------ | ------------------------------------------- | ------------------- |
| Schema     | `modules/schema/`      | 类型契约、编码体系、输出规范                | 零依赖              |
| Data       | `modules/data/`        | 数据获取、校验、类型化、缓存、持久化        | Schema              |
| SpatialOps | `modules/spatial_ops/` | 几何运算、空间索引、关系计算                | Schema + Data       |
| KG         | `modules/kg/`          | 空间语义引擎、RDF图、SPARQL查询             | Schema + SpatialOps |
| Agent      | `agent/`               | 文本理解(EXPLORE+PARSE) + 空间执行(EXECUTE) | KG + Data           |

详见 `design/01_LAYERED_ARCHITECTURE.md`。

---

## 第二部分：闭环规划管线（-> 详见 04_PLANNING_PIPELINE）

### 2.1 一条闭环管线

系统不是"文本规划+空间规划"两条平行线，而是**一条集成的闭环管线**。当前实现为开环（6 断点），目标是闭环。

**设计目标（闭环）**：

```
NL -> L1(28维) -> L2(4维) -> L3(12维) -> EXPLORE -> PARSE -> EXECUTE -> L4回写 -> L3校核轮 -> 输出
     │              │           │           │          │         │          │          │
     └── KG认知 ────┴───────────┘           └── KG候选 ┘         └── KG读 ──┘          │
                                                                                          │
     provenance 贯通 NL -> L1 -> L2 -> L3 -> EXPLORE -> PARSE -> EXECUTE -> L4 <─────────┘
```

**当前实现（开环）**：

```
NL -> L1 -> L2 -> L3 -> phase="completed" -> END  [断点⑦: 不自动触发EXPLORE/GIS]
     │KG浅查    │不查KG                    [断点②: L2/L3不查KG]
                                          [断点⑤: L4已回写, 但L3校核轮未实现]
```

### 2.2 六个阶段

| 阶段          | 职责                                   | 实现状态                               |
| ------------- | -------------------------------------- | -------------------------------------- |
| L1 现状分析   | 12维度并行，KG认知查询+RAG             | `[IMPLEMENTED]`                      |
| L2 规划定位   | 4维度波次，策略性定位                  | `[PARTIAL]` L2不查KG                 |
| L3 详细规划   | 12维度波次，布局意图                   | `[PARTIAL]` L3不查KG                 |
| EXPLORE 桥接  | 读L1+L2+L3，KG交互，产出概要索引       | `[PLANNED]` 源码在25e24847分支待合入 |
| PARSE+EXECUTE | 意图结构化->布局生成->L4回写           | `[IMPLEMENTED]` L4已回写             |
| L3 校核轮     | 读L4 PlannedState做文本/几何一致性校核 | `[PLANNED]`                          |

详见 `design/04_PLANNING_PIPELINE.md`。

---

## 第三部分：KG 语义桥接（-> 详见 03_KG_SEMANTIC_BRIDGE）

### 3.1 KG 全阶段角色

| 阶段     | KG 角色                                                | 实现状态                                                       |
| -------- | ------------------------------------------------------ | -------------------------------------------------------------- |
| L1       | 查认知（layer_cards/constraint_coverage/road_network） | `[IMPLEMENTED]` node.py:670-680                              |
| L2       | 查约束校核（策略定位需认知摘要）                       | `[PLANNED]` node.py:667 `dim_layer!=1 return ""`           |
| L3       | 查现状结构（布局校核）                                 | `[PLANNED]`                                                  |
| EXPLORE  | 查候选实体（BSM/几何/规划分区/建设许可）               | `[PLANNED]` SessionKGQuery已合入                             |
| PARSE    | 写 L3 intent（ZoneTarget/FacilityTarget）              | `[IMPLEMENTED]` layout_pipeline.py:190 `_write_kg_l3_node` |
| EXECUTE  | 写 L4 PlannedState（derived_from provenance）          | `[IMPLEMENTED]` execute/agent.py:374 + layer4.py             |
| L3校核轮 | 读 L4 PlannedState 对账                                | `[PLANNED]`                                                  |

### 3.2 KG 四层模型

| 层          | 内容                                                      | 生命周期   |
| ----------- | --------------------------------------------------------- | ---------- |
| L1 静态     | Ontology + 编码 + 现状实体（有几何）                      | 会话级缓存 |
| L2 语义     | 空间关系（邻接/包含/相交）+ 约束                          | 随L1构建   |
| L3 易失     | Intent 虚拟实体（ZoneTarget等）                           | 规划周期内 |
| L4 规划成果 | PlannedState（PlannedParcel/PlannedZone/PlannedFacility） | 持久化     |

详见 `design/03_KG_SEMANTIC_BRIDGE.md`。

---

## 第四部分：EXPLORE 桥接层（-> 详见 05_EXPLORE_BRIDGE）

### 4.1 为什么 EXPLORE 要提升为贯穿全周期的可复用能力

1. **L1/L3 维度分析需要动态 KG 空间认知** -- 当前 `_optimize_semantics`（node.py:670 静态 DIM_KG_MAP）不可扩展，L2/L3 被 `dim_layer!=1 return ""` 阻断。EXPLORE 作为可复用能力，为每个维度动态提供 KG 空间认知。
2. **文本生成的全部产物（L1+L2+L3）都在 EXPLORE 桥接模式的视野内** -- 当前 gis_agent 只取 L3（`graph.py:207`），L1/L2 的空间线索丢失。
3. **EXPLORE 是文本主线与空间主线的唯一桥接点** -- 不应埋在 gis_agent 内部（只能看到 L3），应在主图层直面全部文本产物。
4. **KG 交互前置** -- EXPLORE 查 KG 候选，PARSE 消费候选不直接查，职责清晰。
5. **产出概要索引** -- 参考 Claude Code 的代码库探索模式，EXPLORE 产出结构化概要/索引，供 GIS agent 按维度访问对应 L3 报告原文。
6. **校核轮也需 EXPLORE** -- L3 校核轮读 L4 PlannedState 做文本/几何一致性校核，也是 EXPLORE 的校核模式。

### 4.2 EXPLORE 的三种调用模式

| 模式                   | 时机                    | 输入                                                         | 产出                                                  | 替代                                        |
| ---------------------- | ----------------------- | ------------------------------------------------------------ | ----------------------------------------------------- | ------------------------------------------- |
| **维度认知模式** | L1/L2/L3 每个维度分析前 | dim_key + 维度报告 + KG                                      | SpatialCognitionSummary                               | 替代`_optimize_semantics` 静态 DIM_KG_MAP |
| **桥接模式**     | L3 完成后（自动/手动）  | L1+L2+L3 全量报告 + KG（非全量应该是输入任务自动调工具查询） | ExplorationInstructionCollection + ReportSummaryIndex | 新增                                        |
| **校核模式**     | L3 校核轮               | L4 PlannedState + L3 文本 + KG                               | ConsistencyReport                                     | 新增（I5改造）                              |

```
EXPLORE Agent (主图顶层节点)
├── 输入: DB读L1+L2+L3 (ReportStore, 按需读取)
├── KG交互: require_session_kg + query_session_template
├── 产出:
│   ├── ExplorationInstructionCollection (证据+候选BSM+域分类+约束)
│   └── ReportSummaryIndex (概要索引, 供GIS按维度访问L3原文)
├── 触发: L3完成后自动触发 + 支持手动触发
└── 路由: -> gis_agent
```

详见 `design/05_EXPLORE_BRIDGE.md`。

---

## 第五部分：成果合规（-> 详见 08_DELIVERABLES_COMPLIANCE）

### 5.1 一图一表一规则

| 成果   | 内容                                | 实现                             |
| ------ | ----------------------------------- | -------------------------------- |
| 一图   | 规划总图（分区着色+设施+轴线+道路） | `[IMPLEMENTED]` render_map节点 |
| 一表   | 用地平衡表+指标表                   | `[PARTIAL]` export_gdb节点     |
| 一规则 | 管制规则模板                        | `[PLANNED]`                    |

### 5.2 GDB 汇交

`[IMPLEMENTED]` `modules/schema/output/gdb.py` 定义 GDB_LAYER_REGISTRY 12 层。

详见 `design/08_DELIVERABLES_COMPLIANCE.md`。

---

## 第六部分：实现状态（-> 详见 10_IMPLEMENTATION_STATUS）

### 6.1 关键实现状态

| 项目               | 状态                     | 证据                                     |
| ------------------ | ------------------------ | ---------------------------------------- |
| 主图 5 节点        | `[IMPLEMENTED]`        | graph.py:159-183                         |
| execute_tools      | `[DEPRECATED?]`        | 过渡态，仅承接闲聊检索                   |
| EXPLORE 节点       | `[PLANNED]`            | 源码在25e24847分支待合入                 |
| L1 KG查询          | `[IMPLEMENTED]`        | node.py:670-680                          |
| L2/L3 KG查询       | `[PLANNED]`            | node.py:667 仍 return ""                 |
| write_kg_l4        | `[IMPLEMENTED]`        | execute/agent.py:374 + layer4.py         |
| L3 校核轮          | `[PLANNED]`            | 无L4读取机制                             |
| PARSE grounding    | `[PARTIAL]`            | 契约+KG查询就绪，agent不产spec           |
| ConstraintCompiler | `[DEPRECATED]`         | 代码已清理                               |
| DataPipeline       | `[IMPLEMENTED]` 但空跑 | 27/28维度 tools:[]                       |
| explore agent      | `[PLANNED]`            | 源码在25e24847分支, SessionKGQuery已合入 |

详见 `design/10_IMPLEMENTATION_STATUS.md`。

---

## 相关文档

| 文档                                                       | 内容                                  |
| ---------------------------------------------------------- | ------------------------------------- |
| [01_LAYERED_ARCHITECTURE](01_LAYERED_ARCHITECTURE.md)       | Q1: 五层分层架构详解                  |
| [02_DATA_PERSISTENCE](02_DATA_PERSISTENCE.md)               | Q2: 数据持久化策略                    |
| [03_KG_SEMANTIC_BRIDGE](03_KG_SEMANTIC_BRIDGE.md)           | Q3: KG 全阶段语义桥接                 |
| [04_PLANNING_PIPELINE](04_PLANNING_PIPELINE.md)             | Q4: 闭环管线六阶段                    |
| [05_EXPLORE_BRIDGE](05_EXPLORE_BRIDGE.md)                   | Q5: EXPLORE 桥接层设计                |
| [06_PARSE_EXECUTE](06_PARSE_EXECUTE.md)                     | Q6: PARSE 空间意图 + EXECUTE 布局生成 |
| [07_VALIDATION_FEEDBACK](07_VALIDATION_FEEDBACK.md)         | Q7: 校验闭环+级联修复+人工审批        |
| [08_DELIVERABLES_COMPLIANCE](08_DELIVERABLES_COMPLIANCE.md) | Q8: 成果合规与汇交                    |
| [09_INTEGRATION_BREAKPOINTS](09_INTEGRATION_BREAKPOINTS.md) | Q9: 11断点+6改造                      |
| [10_IMPLEMENTATION_STATUS](10_IMPLEMENTATION_STATUS.md)     | Q10: 实现状态台账                     |
