# agent/l3_plan 子包（L3 详细规划）

> L3 阶段：`L2Strategy` → 逐维度编译 `L3ProgramFragment` → 合并 `PlanningProgram` → G3 Program Gate。
> 上游三层（L1/L2/L3）的最后一层，产出规划干预方案集（interventions + dependencies），是 post-L3 链（PARSE…DELIVER）的唯一入口产物。

---

## 职责边界

**做**：编排 L3 详细规划分析（`analyze_l3_dimension`，独立 worker，由 `bootstrap/layer_router` 以 `Send` 分发）；复用 `common/dimension_runtime`；层完成后由 `l3_aggregate` 用共享 parse-compiler 逐维度编译 `L3ProgramFragment`（`CompilationProfile.L3_PLANNING`），`merge_program_fragments` 合并去重（intervention 按 `intervention_id`、dependency 按 `(from,to)` 对去重），产出权威 `PlanningProgram`；`enrich_program_from_upstream` 从 `l1-{run}-v1` / `l2-{run}-v1` artifact 回填 `l1_snapshot_ref` / `l2_strategy_ref`、补 `derives_from_strategy`、追加跨层告警（`l1_constraint_unaddressed` / `strategy_orphan`）；用 `evaluate_l3_gate` 出 G3 门；用 `build_l3_review_package` 生成审查包。

**不做**：不直接重解析报告正文（提取委托 `app/modules/parsing/compiler/profiles/l3_planning.py`）；不做意图编译（那是 PARSE 的 `IntentCompilationResult`）；不做任何空间计算 / 选址 / 执行。

### 目录文件

| 文件 | 职责 |
|---|---|
| `worker.py` | `analyze_l3_dimension`：L3 维度分析 worker（LLM + RAG + 分层依赖报告 + SSE + 落库） |
| `aggregate.py` | `l3_aggregate` / `merge_program_fragments` / `enrich_program_from_upstream` |
| `gate.py` | `evaluate_l3_gate`：G3 门（纯函数，无 I/O） |
| `review.py` | `build_l3_review_package`：构造审查包 |

### 流程图

```
   L2Strategy（spatial_structure / implementation_priorities）
        │
        ▼
   layer_router (Send) ──► analyze_l3_dimension（多维并行，worker.py）
        │                        LLM 报告 → ReportStore（layer=3）
        ▼
   layer_completion_check → layer_aggregate_node
        │
        ▼
   l3_aggregate: 逐维 compile_dimension_report(L3_PLANNING)
        │         → L3ProgramFragment[]
        ▼
   merge_program_fragments: 合并/去重 → PlanningProgram
        │
        ▼
   enrich_program_from_upstream（回填 L1/L2 ref + derives_from_strategy + 跨层告警）
        │
        ▼
   evaluate_l3_gate ──┬─ PASS    → PARSE
                      ├─ EXPLORE → 缺证据/缺来源
                      ├─ L3      → program_contradiction / strategy_orphan 重做
                      └─ HUMAN   → 空程序/审查检查点
```

## 输入/输出契约

`l3_aggregate(state)` 输入：`state.run_id` / `session_id` + `ReportStore.get_layer_reports_with_sources(layer=3)`；G3 门依赖 `enrich_program_from_upstream` 返回的 `(l1_constraints, l2_strategy)`。

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 规划程序（根产物） | `app/modules/schema/contracts/l3_contracts.py` | `PlanningProgram`（`interventions`/`dependencies`/`omissions`/`evidence_gaps`/`program_issues`/`l1_snapshot_ref`/`l2_strategy_ref`） |
| 单维片段 | 同上 | `L3ProgramFragment`、`PlanningIntervention`、`InterventionDependency`、`ProgramIssue` |
| 上游契约 | `l2_contracts.py` / `l1_contracts.py` | `L2Strategy`、`L1Snapshot`、`EvidenceGap` |
| 门决定 | `app/modules/schema/contracts/workflow_contracts.py` | `GateDecision`、`PendingRequest` |
| 审查包 | `app/modules/schema/contracts/review_contracts.py` | `ReviewPackage`、`ReviewStatus` |

`l3_aggregate` 返回 `l3_program_ref`、`l3_gate_decision`、`l3_review_id`。下游 PARSE 通过 `l3_program_ref`（`FilesystemArtifactStore`）取 `PlanningProgram`。

## 依赖方向

**可导入**：`app/modules/parsing/compiler/core`（`compile_dimension_report` + `CompilationProfile.L3_PLANNING`）、`app/modules/schema/contracts/*`、`app/services/report_store`、`app/services/artifact_store`、`app/services/review_package`、`app/agent/common/dimension_runtime`、`app/agent/explore/service`。

**禁止导入**：`app/agent/l1_observe/analysis_node`、`app/agent/l2_strategize` 的 worker/内部实现（只允许经 artifact store 读取 L1/L2 产物）、所有 post-L3 stage（`parse`/`ground`/`select`/`execute`/`validate`/`reconcile`/`deliver`）。

## 禁止行为

- 不得 import `l1_observe.analysis_node` / `l2_strategize.worker` 复用分析实现（只能经 `common/dimension_runtime` 与 artifact store）。
- 不得在 `l3_aggregate` 内重解析报告正文或调用 LLM。
- 不得把 L1/L2 回填做成强耦合（`enrich_program_from_upstream` 对缺失 artifact 必须容错跳过并记日志）。
- 不得跳过 G3 门；`strategy_orphan`（L2 有空间结构但 L3 零干预）必须走 `L3` 重做路由。
- 根产物 `PlanningProgram` 必须继承 `ContractMeta`；intervention 必须带 `intervention_id`（去重键）。

---

## 相关文档

- `../README.md` — agent 编排层总览
- `../bootstrap/graph.py` — aggregate 调用方与阶段路由
- `../bootstrap/post_l3_main_nodes.py` — post-L3 入口（从 L3 产物加载 PlanningProgram）
- `../parse/README.md` — PARSE（下游消费者）
- `app/modules/parsing/compiler/profiles/l3_planning.py` — L3 提取 profile
