# agent/l2_strategize 子包（L2 策略推导）

> L2 阶段：`L1Snapshot` + EvidenceBundle → 逐维度编译 `L2StrategyFragment` → 合并 `L2Strategy` → G2 Strategy Gate。
> 在上游三层（L1/L2/L3）中处于中间层，把 L1 现状事实上升为发展目标与空间结构判断。

---

## 职责边界

**做**：编排 L2 策略分析（`analyze_l2_dimension`，独立 worker，由 `bootstrap/layer_router` 以 `Send` 分发）；复用 `common/dimension_runtime` 的 RAG / 依赖报告加载 / SSE / 落库辅助；层完成后由 `l2_aggregate` 用共享 parse-compiler 逐维度编译 `L2StrategyFragment`（`CompilationProfile.L2_STRATEGY`），`merge_strategy_fragments` 合并去重、拼装 `development_goals` / `spatial_structure` / `implementation_priorities`，产出权威 `L2Strategy` 并持久化；用 `evaluate_l2_gate` 出 G2 门；用 `build_l2_review_package` 生成审查包。

**不做**：不直接重解析报告正文（提取委托 `app/modules/parsing/compiler/profiles/l2_strategy.py`）；不产出干预方案（那是 L3 `PlanningProgram`）；不做任何空间计算/选址；不得 import L1 的 `analysis_node` 实现（见下"禁止行为"）。

### 目录文件

| 文件 | 职责 |
|---|---|
| `worker.py` | `analyze_l2_dimension`：L2 维度分析 worker（LLM + RAG + 证据注入 + SSE + 落库） |
| `aggregate.py` | `l2_aggregate` / `merge_strategy_fragments`：编译片段 → 合并 `L2Strategy` → 持久化 + 门 + 审查包 |
| `gate.py` | `evaluate_l2_gate`：G2 门（纯函数，无 I/O） |
| `review.py` | `build_l2_review_package`：构造审查包 |

### 流程图

```
   L1Snapshot / L1 约束
        │
        ▼
   layer_router (Send) ──► analyze_l2_dimension（多维并行，worker.py）
        │                        LLM 报告 → ReportStore（layer=2）
        ▼
   layer_completion_check → layer_aggregate_node
        │
        ▼
   l2_aggregate: 逐维 compile_dimension_report(L2_STRATEGY)
        │         → L2StrategyFragment[]
        ▼
   merge_strategy_fragments: 合并/去重 → L2Strategy（persist l2-{run}-v1）
        │
        ▼
   evaluate_l2_gate ──┬─ PASS    → L3 PLAN
                      ├─ EXPLORE → 缺证据/缺来源
                      ├─ L2      → strategy_contradiction 策略冲突重做
                      └─ HUMAN   → 空策略/审查检查点
```

## 输入/输出契约

`l2_aggregate(state)` 输入：`state.run_id` / `session_id` + `ReportStore.get_layer_reports_with_sources(layer=2)`；G2 门可选 `l1_constraints`（来自 L1）。

| 契约 | 文件 | 关键类型 |
|---|---|---|
| L2 策略（根产物） | `app/modules/schema/contracts/l2_contracts.py` | `L2Strategy`（`development_goals`/`spatial_structure`/`implementation_priorities`/`strategy_conflicts`/`evidence_gaps`/`strategy_issues`） |
| 单维片段 | 同上 | `L2StrategyFragment`、`StrategyConflict`、`StrategyIssue` |
| L1 门依赖 | `app/modules/schema/contracts/l1_contracts.py` | `EvidenceGap` |
| 门决定 | `app/modules/schema/contracts/workflow_contracts.py` | `GateDecision`、`PendingRequest` |
| 审查包 | `app/modules/schema/contracts/review_contracts.py` | `ReviewPackage`、`ReviewStatus` |
| 元数据 | `contract_meta.py`、`evidence_contracts.py`、`provenance.py` | `StageIssue`、`EvidenceSource`、`Provenance` |

`l2_aggregate` 返回 `l2_strategy_ref`、`l2_gate_decision`、`l2_review_id`。

## 依赖方向

**可导入**：`app/modules/parsing/compiler/core`（`compile_dimension_report` + `CompilationProfile.L2_STRATEGY`）、`app/modules/schema/contracts/*`、`app/services/report_store`、`app/services/artifact_store`、`app/services/review_package`、`app/agent/common/dimension_runtime`、`app/agent/explore/service`（证据注入）。

**禁止导入**：`app/agent/l1_observe/analysis_node`（L1 实现细节，L2 worker 只允许用 `common/dimension_runtime`）、`app/agent/l3_plan` 及所有 post-L3 stage（`parse`/`ground`/`select`/`execute`/…）。

## 禁止行为

- 不得 import `l1_observe.analysis_node` 来复用 L1 分析逻辑（架构规定 L2/L3 只依赖 `common/dimension_runtime`）。
- 不得在 `l2_aggregate` 内重解析报告正文或调用 LLM。
- 不得虚构 `spatial_structure`（只取维度片段提供的值，`merge_strategy_fragments` 取首个非空）。
- 不得跳过 G2 门直接放行到 L3。
- 不得把 `L2Strategy` 退化成裸 dict；根产物必须继承 `ContractMeta`。

---

## 相关文档

- `../README.md` — agent 编排层总览
- `../bootstrap/layer_aggregate_node.py` — aggregate 调用方
- `../common/dimension_runtime.py` — 共享维度运行时
- `app/modules/parsing/compiler/profiles/l2_strategy.py` — L2 提取 profile
