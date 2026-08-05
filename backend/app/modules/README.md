# Domain Modules（app.modules）— 领域层

> 村庄规划系统**业务逻辑与数据模型的唯一领域层**。所有规划算法、类型契约、数据获取、空间计算与知识图谱语义都以领域模块承载于此。
> 核心铁律：**领域层禁止反向导入 `app.agent` / `app.services` / `app.api` / `app.tools`**（见 `docs/design/01_LAYERED_ARCHITECTURE.md` §5 迁移规则）。

---

## 职责边界

**负责**：领域能力本身 —— 类型契约（schema）、统一数据获取（data）、空间计算（spatial_ops）、语义图谱（kg）、确定性+LLM 文本提取（parsing）、规划文本成果生成（planning_text）、外部知识检索（rag）、Prompt 模板（prompts）、会话事实上下文（context）与依赖倒置端口（ports）。

**不负责**：
- 不编排 LangGraph 节点 / 会话生命周期 / SSE 事件分发（那是 `app.agent` / `app.services` 的职责）
- 不暴露 HTTP 路由与请求/响应组装（那是 `app.api` 的职责）
- 不作为规划算法的第二实现（那是 `app.tools` 禁止越过的边界 —— `tools` 只能是外部能力适配器）

### 子目录角色

| 子目录 | 角色 | 核心入口 / 契约 |
|---|---|---|
| `schema/` | 类型契约 + 编码体系（最底层，零外部依赖） | `VillageBundle` / `contracts/*` |
| `data/` | 统一数据获取层（唯一数据入口） | `DataCatalog.load_village_bundle()` |
| `spatial_ops/` | 全部空间计算的唯一发生地 | `compute_context_blocks` / `build_spatial_index` |
| `kg/` | 空间语义引擎（RDF 图 + SemanticMemoryStore） | `KGBuilder.build()` |
| `parsing/` | 确定性 + LLM 文本提取工具层 | `compile_dimension_report` |
| `planning_text/` | 规划文本成果生成 | S-COPY / S-ASSEMBLE / S-TEMPLATE / S-GENERATE |
| `rag/` | 外部知识检索与知识库管理 | `RagService` |
| `prompts/` | 全部分层 Prompt 模板库 | 模板 + 组装函数（不执行逻辑） |
| `context/` | 会话事实权威（纯数据容器） | `PlanningContext` |
| `ports/` | 依赖倒置 Protocol 端口 | `PlanningPorts`（9 个端口） |

---

## 输入/输出契约

- **类型事实**：`app.modules.schema.types.canonical.VillageBundle`（形态优先的 typed 数据束）
- **阶段契约**：`app.modules.schema.contracts/*` —— `L1Snapshot` / `L2Strategy` / `PlanningProgram` / `IntentCompilationResult` / `SpatialReferenceSpec` / `GroundingResult` / `SiteSelectionDecision` / `ExecutionPlan` / `ValidationReport` / `ReconciliationReport` / `DeliveryManifest`
- **会话上下文**：`app.modules.context.planning_context.PlanningContext`（版本化事实容器，见 `context/README.md`）
- **端口注入**：`app.modules.ports.planning_ports.PlanningPorts`（9 个注入式 Protocol，见 `ports/README.md`）

---

## 依赖方向

```
app.agent / app.services / app.api / app.tools      （编排层，可向下调用）
        │
        ▼
app.modules  ──►  app.utils（跨层纯工具，如 crs_engine / area_engine）
   │
   ├── schema  ←── data ←── spatial_ops ←── kg
   └── ports（领域定义端口，实现由上层/数据层注入）
```

- 模块内部允许的依赖：`data → schema`、`spatial_ops → schema`、`kg → schema`、`kg → spatial_ops`（消费 ParcelRelations / ContextBlock）、`parsing → schema.contracts`
- 模块之间通过**契约**（`schema/contracts/`）通信，而非直接 import 对方的内部实现；跨模块对象注入一律走 `ports/`

---

## 禁止行为

- `modules → agent / services / api / tools`（向上导入）—— 违反分层，发现即架构缺陷（设计文档迁移规则 §3）
- `schema` 读数据库 / 文件 / KG / LLM —— schema 只定义类型（设计文档 §2.1）
- 在 `parsing/` 内做任何空间计算（BBox / 距离 / 面积 / 过滤）—— 空间计算只允许在 `spatial_ops/`
- 在 `kg/` 内做多边形精确几何计算 —— KG 只存结果，算力在 spatial_ops
- 新业务代码从 `schema/contracts/__init__.py` 走 wildcard 导入 —— 应从具体契约文件导入（设计文档迁移规则 §7）
- 在同一能力上保留两个正式入口 —— 旧入口只能转发并标记 `[DEPRECATED]`（迁移规则 §2）

---

## 相关文档

- `docs/design/01_LAYERED_ARCHITECTURE.md` — 分层架构与模块边界（唯一权威）
- `docs/design/00_SYSTEM_DESIGN.md` — 系统总体设计（工具层边界：tools 只能是外部能力适配器）
- 各子目录 `README.md`（`schema/`、`data/`、`kg/`、`parsing/`、`spatial_ops/` 等均有独立文档）
