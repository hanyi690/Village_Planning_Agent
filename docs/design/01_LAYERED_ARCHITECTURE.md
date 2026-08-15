# 分层架构与模块边界

> **目标：让目录结构、依赖方向和业务职责一致。** 目录名不是边界；契约和依赖规则才是边界。
> 目标目录以 [14_BACKEND_MODULE_BLUEPRINT.md](14_BACKEND_MODULE_BLUEPRINT.md) 为准；本文只保留分层规则和依赖约束。

## 1. 目标分层

```text
API / UI adapters
        ↓
Application workflow subgraphs
        ↓
Planning domain services
        ↓
Spatial query / KG services
        ↓
Data repositories and adapters
        ↓
Schema contracts and encodings
```

## 2. 各层职责

### 2.1 Schema contracts

位置：`backend/app/contracts/`

只定义类型、枚举、编码、规则描述和 provenance。典型契约包括：

- `PlanningContext`
- `L1Snapshot`
- `L2Strategy`
- `PlanningProgram`
- `IntentCompilationResult`
- `SpatialReferenceSpec`
- `GroundingResult`
- `SiteSelectionDecision`
- `ExecutionPlan`
- `ValidationReport`
- `DeliveryGate`

Schema 不读取数据库、文件、KG 或 LLM。

当前契约目录按阶段拆分是允许的，但并非每个文件都代表独立运行阶段。`contract_meta.py`、
`provenance.py`、`classification_ref.py`、evidence/context/workflow contracts 是稳定共性；
`l1/l2/l3`、`grounding`、`selection`、`execution_plan`、`planned_state`、`validation`、
`reconciliation`、`delivery` 和 `review` 是阶段 artifact。`parse_contracts.py` 当前仍同时承载
intent target、spatial operation、constraint 和指标模型；`layout_contracts.py` 与
`execution_plan_contracts.py` 存在遗留重叠，`custom_zone_contracts.py` 只应保留词汇/功能区语义，
不应成为第二套执行目标模型。契约合并应在调用方迁移和 EXECUTE 输入冻结后进行，当前先禁止新增旧模型依赖。

### 2.2 Data repositories

位置：`backend/app/data/` 与 `infrastructure/persistence/` 适配器。

负责数据摄取、类型化、缓存、版本和外部数据源。`DataCatalog` 只生产 `VillageBundle` 或其版本化引用；外部锚点不得在每次业务读取时隐式重新抓取。

### 2.3 Spatial query services

位置：`backend/app/spatial/`。

负责几何、空间索引、候选集精化、距离、拓扑和约束计算。它不解析自然语言，也不决定规划策略。

### 2.4 KG semantic services

位置：`backend/app/evidence/kg/` 与 `infrastructure/kg/`。

负责实体、语义关系、来源和可查询的空间认知。KG 不替代完整几何引擎；需要多边形精确计算时，通过 Spatial Query Service 组合完成。

### 2.5 Planning domain services

目标位置：`backend/app/domain/` 下的领域模块和 `contracts/ports/`。迁移期间能力仍可能分散在
`agent/`、`modules/spatial_ops/`、`modules/parsing/` 和历史 service 目录；这些目录不能因此被视为
已经完成了领域边界收敛。

包含：

- `intent_compiler`：报告/规划文本 → 类型化意图
- `grounding_service`：空间引用 → 候选及证据
- `selection_service`：候选 → 选址决定
- `execution_service`：决定 → 规划图层
- `reconciliation_service`：意图与成果对账

这些服务必须是可独立测试的纯领域入口，不能依赖 LangGraph State。

### 2.6 Application workflow subgraphs

目标位置：`backend/app/workflow/`；旧 `backend/app/agent/` 只作为迁移历史来源。

目标上只负责节点编排、并行调度、Gate、重试和人工中断。当前阶段节点应通过
`workflow/stages/` 调用 `domain/materialization/` 和 `spatial/`；实现偏差以状态台账标记。

### 2.7 Application services and adapters

位置：`backend/app/application/`、`backend/app/infrastructure/` 和 `backend/app/bootstrap/`。

应用编排位于 `backend/app/application/`，Context、artifact、报告、SSE、runtime 和 provider
适配位于 `backend/app/infrastructure/`；适配器可以调用领域服务，但不能反向把领域服务绑定到 Agent State。

## 3. 允许与禁止的依赖

| 来源 | 可依赖 | 禁止依赖 |
|---|---|---|
| Contracts | 标准库、Pydantic | Data、KG、Agent、Service、API |
| Data | Contracts、外部 Provider | Agent、LangGraph |
| Spatial | Contracts、Data read port | Agent、LLM、API |
| Evidence/KG | Contracts、Spatial port | Agent State、API |
| Planning domain | Contracts、Evidence port、Spatial port | LangGraph、SSE、ReportStore 实现 |
| Workflow | Planning domain、ports、adapters | 直接实现领域算法 |
| Infrastructure | ports、外部 SDK | 反向导入 Domain/Workflow 作为业务依赖 |

## 4. 单一上下文原则

所有子图接收同一个版本化的 `PlanningContext`：

```text
PlanningContext
├── session_id
├── village_bundle_ref + version
├── kg_snapshot_ref + version
├── report_snapshot_ref
├── evidence_bundle_ref
├── planning_artifacts
├── provenance
└── active_gate
```

子图之间传递 artifact 引用和版本，不复制完整 GIS 数据、报告文本和 KG 缓存。

## 5. 迁移规则

1. 先建立 contracts 和 ports，再移动实现。
2. 同一能力只保留一个正式入口；旧入口只能转发并标记 `[DEPRECATED]`。
3. 新增 import 边界检查，禁止出现 `modules → agent/services/api`。
4. 每迁移一个子图，保留输入/输出快照测试。
5. 目录重命名晚于职责切分，避免“换目录但耦合不变”。
6. `app/spatial/network/planner.py` 是道路规划唯一正式入口；任何新增局部 planner 只能显式标记为 degraded，不能成为第二正式入口。
   在收敛完成前必须明确 staged planner 是 canonical，local planner 只能显式标记为 degraded。
7. `schema/contracts/__init__.py` 不再使用 wildcard 作为业务代码的主要导入入口；业务代码应从具体契约文件导入。

## 6. 理想实现的运行时不变量

分层边界还必须覆盖运行时行为：

1. `schema/contracts` 定义跨 API、Agent、SSE 和前端的唯一数据形状。HUMAN interrupt 的两个业务频道只能通过 `channel` 区分，不得分别维护 `step_mode` 和 `post_l3` 的 payload 字段。
2. Workflow 层只负责 `interrupt`、恢复路由和幂等事件；人工决策的业务解释留在 domain/service 层，不能让前端猜测 `reason` 字符串。
3. LangGraph 的 checkpoint、`thread_id` 和恢复入口必须保持一致。EXECUTE 的独立编译调用是当前迁移缺口，不是目标架构。
4. 资源生命周期由应用层统一管理；数据库 session 不跨并发 worker 共享，流式响应的取消和清理必须可观测。

上述不变量以官方语义为验收依据：[LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)、[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) 和 [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)。
