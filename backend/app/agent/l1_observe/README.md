# agent/l1_observe 子包（L1 现状观察）

> L1 阶段：12 维度并行分析 → 逐维度编译 `L1DimensionFragment` → 合并 `L1Snapshot` → G1 Evidence Gate。
> 属于上游分析三层（L1/L2/L3）的第一层，产出基线"事实 + 约束 + 问题 + 证据缺口"快照。

---

## 职责边界

**做**：编排 L1 现状分析（`analyze_dimension`，被 `bootstrap/layer_router` 以 LangGraph `Send` 并行分发到 12 个维度）；对每个维度调用共享数据管线 `DataPipeline` 拉取专业数据、组 Prompt、调用 LLM 生成报告；将报告落 `ReportStore`；层完成后由 `l1_aggregate` 用共享 parse-compiler 逐维度编译出 `L1DimensionFragment`，`merge_fragments` 合并去重、做 `fact_contradiction` 冲突检测，产出权威 `L1Snapshot` 并持久化；用 `evaluate_l1_gate` 出 G1 门决定；用 `build_l1_review_package` 生成审查包。

**不做**：不直接重解析报告正文（提取全部委托给 `app/modules/parsing/compiler/profiles/l1_observation.py`）；不做任何空间接地/选址/执行（那是 GROUND/SELECT/EXECUTE）；不消费 L2/L3 产物（它是下游依赖的源头，只依赖 L1 层自身报告）。

### 目录文件

| 文件 | 职责 |
|---|---|
| `analysis_node.py` | `analyze_dimension`：维度分析节点（LLM + RAG + 证据注入 + SSE + ReportStore 落库） |
| `pipeline.py` | `DataPipeline`：按维度配置串行执行 `TOOL_REGISTRY` 中已实现的工具，聚合 `professional_data` |
| `formatters.py` | `generate_professional_data_section`：把 `professional_data` 格式化为 Prompt 可注入文本 |
| `aggregate.py` | `l1_aggregate` / `merge_fragments`：编译片段 → 合并 `L1Snapshot` → 持久化 + 门 + 审查包 |
| `gate.py` | `evaluate_l1_gate`：G1 门（纯函数，无 I/O） |
| `review.py` | `build_l1_review_package`：构造 5 段式 `ReviewPackage` |

### 流程图（12-worker → fragment → snapshot → gate）

```
              ┌─────────── layer_router (Send 并行分发 12 维) ───────────┐
              │                                                          │
   dimension_1 ... dimension_12   (analyze_dimension / analysis_node.py)
              │        LLM 报告 → ReportStore（layer=1）                 │
              ▼                                                          │
   layer_completion_check（层完成检测 → layer_aggregate_node）            │
              │                                                          │
              ▼                                                          │
   l1_aggregate: 逐维 compile_dimension_report(L1_OBSERVATION)            │
              │         → L1DimensionFragment[]                          │
              ▼                                                          │
   merge_fragments: 合并/去重/冲突检测 → L1Snapshot（persist l1-{run}-v1）│
              │                                                          │
              ▼                                                          │
   evaluate_l1_gate ──┬─ PASS    → L2 STRATEGIZE                        │
                      ├─ EXPLORE → 缺证据/缺来源 → retrieve_evidence     │
                      ├─ L1      → fact_contradiction 事实冲突重做       │
                      └─ HUMAN   → 空快照/审查检查点                      │
```

## 输入/输出契约

`analyze_dimension(state)` 输入：`AgentState`（`config.village_data` / `completed_dimensions` / RAG 开关）；输出写入 `ReportStore` 并更新 `completed_dimensions` / `pending_reports`。

`l1_aggregate(state)` 输入：`state.run_id` / `session_id` + `ReportStore.get_layer_reports_with_sources(layer=1)`；输出：

| 契约 | 文件 | 关键类型 |
|---|---|---|
| L1 快照（根产物） | `app/modules/schema/contracts/l1_contracts.py` | `L1Snapshot`（`facts`/`constraints`/`issues`/`evidence_gaps`/`classification_refs`/`dimension_provenance`） |
| 单维片段 | 同上 | `L1DimensionFragment`、`EvidenceGap` |
| 门决定 | `app/modules/schema/contracts/workflow_contracts.py` | `GateDecision`、`PendingRequest` |
| 审查包 | `app/modules/schema/contracts/review_contracts.py` | `ReviewPackage`、`ReviewStatus` |
| 共享元数据 | `app/modules/schema/contracts/contract_meta.py`、`evidence_contracts.py`、`provenance.py` | `StageIssue`、`EvidenceSource`、`Provenance` |

`l1_aggregate` 返回 `l1_snapshot_ref`（artifact ref）、`l1_gate_decision`、`l1_review_id`。

## 依赖方向

**可导入**：`app/modules/parsing/compiler/core`（`compile_dimension_report` + `CompilationProfile.L1_OBSERVATION`）、`app/modules/schema/contracts/*`、`app/services/report_store`、`app/services/artifact_store`、`app/services/review_package`、`app/agent/common/dimension_runtime`（`run_rag` / `generate_summary` / SSE 辅助）、`app/agent/explore/service`（证据注入，下游同层横向依赖）。

**禁止导入**：`app/agent/l2_strategize` / `l3_plan` / `parse` / `ground` / `select` / `execute` 等下游 stage（依赖方向只能自上游向下游，禁止反向）。

## 禁止行为

- 不得在 `l1_aggregate` 内重新解析报告正文或调用 LLM（提取已收敛到共享 parse-compiler，双解析会产生不一致）。
- 不得直接 import `app.agent.l1_observe.analysis_node` 的私有实现细节到 L2/L3 worker（L2/L3 应只复用 `common/dimension_runtime`，见其 README）。
- 不得把 `L1Snapshot` 存成"大 dict"绕过 typed 契约；根产物必须继承 `ContractMeta` 并带 `artifact_id`。
- 门决定必须走 `evaluate_l1_gate` 纯函数，禁止在 aggregate 里内联"我猜没问题"式跳过门。
- 不得在 `review.py` 里做 I/O（写盘统一委托 `services/review_package.write_review_package`）。

---

## 相关文档

- `../README.md` — agent 编排层总览（L1/L2/L3 三层数据流）
- `../bootstrap/layer_aggregate_node.py` — 层完成后的 aggregate 调用方
- `../common/dimension_runtime.py` — 共享维度运行时（RAG/SSE/落库辅助）
- `app/modules/parsing/compiler/profiles/l1_observation.py` — L1 提取 profile
- `docs/architecture/agent-graph.md` — 迁移目录归属
