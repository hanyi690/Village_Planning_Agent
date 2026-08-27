# 06 SELECT、EXECUTE 与目标代码架构

## 1. SELECT

```text
GroundedPlanningProblem → candidate validation → deterministic solver
→ scenario evaluation → evidence gap completion → rerun if inputs changed
→ ScenarioSet → approval → ApprovedExecutionInput
```

SELECT 只在 GROUND 闭集上求解。LLM 只能在 formal scenarios 中解释或推荐，不能创造候选、修改 geometry 或放宽约束。

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
├── modules/{l1,l2,l3,evidence,target_projection,ground,select,execute}/
│   ├── application.py   # 唯一 facade
│   ├── domain/          # 本阶段子图和业务规则
│   ├── projections.py   # 给 LLM 的表格 projection
│   ├── ports.py
│   └── README.md
├── workflow/            # graph/state/routing/recovery，只编排
├── contracts/           # 按阶段 owner 的跨边界契约
├── data/                # 输入、摄取、快照
├── spatial/             # 几何、查询、拓扑、网络、地形
├── infrastructure/     # LLM、RAG、KG、search、GIS、storage
├── database/
├── config/
└── core/
```

依赖只能向下：`api → application/workflow → modules → contracts/ports → data/spatial/infrastructure`。Context manager、table renderer、structured parser、budget manager 和 artifact assembler 由公共基础能力集中提供；业务模块不得自行拼接完整 context。

