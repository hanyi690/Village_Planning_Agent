# 06 SELECT、EXECUTE 与目标代码架构

## 1. SELECT

```text
GroundedPlanningProblem → candidate validation → deterministic solver
→ scenario evaluation → evidence gap completion → rerun if inputs changed
→ ScenarioSet → approval → ApprovedExecutionInput
```

SELECT 只在 GROUND 闭集上求解。LLM 只能在 formal scenarios 中解释或推荐，不能创造候选、修改 geometry 或放宽约束。

当 GROUND 已经形成 typed problem、但当前证据无法形成可执行候选域时，SELECT
保留具体 target 的恢复信息并进入 `diagnostic_only`，不制造 ScenarioSet，也不
绕过审批进入 EXECUTE。存在可执行方案但缺少审批时，仍然进入明确的 HUMAN 审批边界。

## 2. EXECUTE

```text
ApprovedExecutionInput → approval validation → ExecutionPlan
→ scope/coverage validation → bounded workers → result reconciliation
→ staged changeset → PlannedState → ExecutionResult
```

EXECUTE 只能决定如何物化，不能改变执行什么。需要替换候选、修改数量/面积/约束时返回 SELECT、GROUND 或 HUMAN。

## 3. 后处理

`VALIDATE` 生成 `ValidationCertificate`；`RECONCILE` 生成 `FinalManifest`；`DELIVER` 生成 `DeliveryManifest`。三者不重新产生上游权威决策，必须诚实表达 complete、partial、diagnostic_only 和 failed。

## 4. 目标代码树

```text
backend/app/
├── modules/
│   ├── l1/               # application/context/retrieval/reasoning/facts/validation/aggregation
│   ├── l2/               # problem/objectives/demand/suitability/strategy/reasoning/aggregation
│   ├── l3/               # claim generation/normalization/validation/reasoning/aggregation
│   ├── evidence/         # semantic requirements, gaps, packet and facade only
│   ├── target_projection/  # application.py + stage.py + typed compiler
│   ├── ground/             # application.py + stage.py + grounding internals
│   ├── select/             # application.py + stage.py + solver internals
│   └── execute/            # application.py + stage.py + workers/
│       # 业务模块均有 application.py、projections.py、ports.py、README.md
├── workflow/            # graph/state/routing/recovery；终端闭环适配器
├── contracts/           # 按阶段 owner 的跨边界契约
│   ├── l1/ l2/ l3/ evidence/
│   ├── target_projection/ ground/ select/ execute/
│   └── validation/ delivery/
├── data/                # 输入、摄取、快照
├── spatial/             # 几何、查询、拓扑、网络、地形
├── infrastructure/     # Context/Evidence/Structured runtime、LLM、RAG、KG、search、GIS、storage
├── database/
├── config/
└── core/
```

依赖只能向下：`api → application/workflow → modules → contracts/ports → data/spatial/infrastructure`。

## 5. 集中式运行能力

上下文管理、检索执行、结构化输出解析和预算管理是集中式平台能力，不属于任何一个单独业务阶段：

```text
backend/app/infrastructure/
├── context_runtime/
│   ├── manager.py
│   ├── projection_builder.py
│   ├── table_renderer.py
│   └── budgets.py
├── evidence_runtime/
│   ├── facade.py
│   ├── query_planner.py
│   ├── retriever_router.py
│   ├── fusion.py
│   ├── provenance.py
│   └── sufficiency.py
└── structured_runtime/
    ├── parser.py
    ├── validator.py
    └── assembler.py
```

业务阶段只提供阶段策略、业务语义和 projection 定义：

```text
L1/L2/L3/GROUND/SELECT
    → 声明 requirement
    → 请求 named projection
    → 调用统一 runtime
    → 消费 typed result
```

阶段不得自行实现完整 context 拼接、retriever 路由、provider 调用、表格渲染、schema 重试或 artifact assembly。

## 6. 业务模块与集中能力的关系

`modules/evidence/` 是证据领域的业务 facade 和 contract owner；`infrastructure/evidence_runtime/` 是检索执行平台。`modules/l1/` 可以定义“什么算现状事实”，但不能复制检索器；`modules/ground/` 可以定义“什么算有效空间绑定”，但不能复制空间检索 runtime。

## 7. SELECT/EXECUTE 目标目录与迁移出口

```text
backend/app/modules/select/
├── application.py
├── stage.py
├── candidate_validation.py
├── solver.py
├── scenario_builder.py
├── ranking.py
├── evidence_completion.py
└── approval.py

backend/app/modules/execute/
├── application.py
├── stage.py
├── approval_boundary.py
├── plan_builder.py
├── task_scheduler.py
├── workers/
├── result_reconciliation.py
├── materialize.py
└── execution_evidence.py
```

当前 SELECT 与 EXECUTE 的生产实现分别集中在 `modules/select/`、`modules/execute/`，workflow 只负责编排；关系评估位于 `spatial/relations/`，交付聚合位于 `workflow/delivery/`。SELECT 的迁移出口是可重载的 `ScenarioSet` 与 `ApprovedExecutionInput`；EXECUTE 的迁移出口是可重载的 `ExecutionResult` 与 `PlannedState`，并能被 VALIDATE 消费。

## 8. 共享运行能力

```text
backend/app/infrastructure/context_runtime/
├── manager.py
├── projection_builder.py
├── table_renderer.py
├── budgets.py
└── runtime.py
```

结构化解析和 artifact assembly 的实现位于 `backend/app/infrastructure/structured_runtime/`；所有阶段共享 Context Runtime、Evidence Runtime、Structured Runtime，各阶段只定义自己的字段白名单与小事务 schema。`modules/evidence/` 不拥有 retriever；`infrastructure/evidence_runtime/` 才是唯一检索执行平台。
