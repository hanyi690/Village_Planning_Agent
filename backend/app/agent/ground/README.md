# agent/ground 子包（GROUND 空间接地）

> GROUND 阶段：`SpatialReferenceSpec[]` + `PlanningContext`（+ EXPLORE 证据）→ `GroundingResult` + `CandidateSite[]` → Ground gate。
> 把 PARSE 的闭集空间引用 DSL 解析为具体候选地块（BSM 级），是"意图 → 空间候选"的确定性接地层。

---

## 职责边界

**做**：编排确定性接地（`ground_aggregate`）：对每个 `SpatialReferenceSpec` 调 `app/modules/spatial_ops/grounding/resolver.SpatialResolver.resolve_spec` 解析出最终 BSM 集，产出 `CandidateSite`（每个成功 spec 一个）、`SpatialQueryEvidence`（每个 spec 一行）、未解析则记 `StageIssue`；`evaluate_ground_gate` 出 Ground gate（PASS / EXPLORE / HUMAN）；`retrieve_evidence` 在 EXPLORE 重试时对 `PlanningContext` 做轻量证据复查（bundle 图层/地块计数、村锚点、gazetteer 覆盖）。`format_bound_intent.py` 提供把 EXPLORE/Binder 产物严格转为意图的工具（无 GIS 查询/无坐标推断，供其他路径复用）。

**不做**：**不**对候选做排名 / 评分 / 选优（那是 SELECT 的职责，`SELECT` 消费 `GroundingResult.candidates`）；不调用 LLM；不产生最终几何落图（那是 EXECUTE）。同一 spec + context 重复运行产出完全一致（确定性），`build_candidate_site` 用 1-based index + first_bsm 保证 `site_id` 稳定。

### 目录文件

| 文件 | 职责 |
|---|---|
| `aggregate.py` | `ground_aggregate` / `build_candidate_site` / `retrieve_evidence`：确定性接地编排 |
| `gate.py` | `evaluate_ground_gate` / `ground_gate_route`：3 路门（纯函数） |
| `review.py` | `build_ground_review_package`：构造审查包 |
| `format_bound_intent.py` | `format_bound_spatial_intent`：Binder/EXPLORE 产物 → typed intent（无坐标推断） |

### 流程图

```
   SpatialReferenceSpec[]（PARSE 产物）
        │   + PlanningContext（bundle / constraint_index / anchors / gazetteer）
        ▼
   ground_aggregate ──► SpatialResolver.resolve_spec（逐 spec）
        │                   ├─ 成功 → CandidateSite（site_{i}_{bsm}）
        │                   └─ 失败 → StageIssue（spatial_reference_unresolved）
        ▼
   GroundingResult（candidates / unresolved / spatial_query_evidence）
        │
        ▼
   evaluate_ground_gate ──┬─ PASS    → SELECT
                          ├─ EXPLORE → 有未解析 spec 或零候选 → retrieve_evidence 复查
                          └─ HUMAN   → 多源候选且置信度 < 0.6（歧义）
```

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 接地结果（根产物） | `app/modules/schema/contracts/grounding_contracts.py` | `GroundingResult`、`CandidateSite`、`HardConstraintResult`、`SpatialQueryEvidence` |
| 空间引用 DSL | `app/modules/schema/contracts/spatial_reference_contracts.py` | `SpatialReferenceSpec`、`ResolvedSpatialRef` |
| 上下文 | `app/modules/context/planning_context.py` | `PlanningContext`（bundle / constraint_index / village_anchors / gazetteer） |
| 门决定 | `app/modules/schema/contracts/workflow_contracts.py` | `GateDecision`、`PendingRequest` |
| 元数据 | `contract_meta.py` / `provenance.py` | `StageIssue`、`Provenance` |

`ground_aggregate(specs, context)` 返回 `GroundingResult`。post-L3 链中 `ground_node`（`bootstrap/post_l3_nodes.py`）在 EXPLORE 重试时先 `retrieve_evidence` 再重跑 aggregate，并把证据行并入结果。

候选语义：`CandidateSite.site_id` 采用确定性命名（`site_{i+1}_{first_bsm}`，无 BSM 时 `site_{i+1}`）；`metrics.confidence` 取 `ResolvedSpatialRef.confidence`；`target_ref` / `project_ref` 由 spec 携带，供 SELECT 关联；`available_area_ha` 在此阶段保持 `0.0`（面积校准不在 GROUND 职责内）。

门判定依据：`unresolved` 非空或 `candidates` 为空 → `EXPLORE`；存在多源候选且置信度 < `ambiguity_threshold`（默认 0.6）→ `HUMAN`；其余 → `PASS`。`ambiguity_threshold` 可注入，门为纯函数。

## 依赖方向

**可导入**：`app/modules/spatial_ops/grounding/resolver`（`SpatialResolver`）、`app/modules/context/planning_context`、`app/modules/schema/contracts/*`。

**禁止导入**：`app/agent/select`（排名/选优是 SELECT，GROUND 不得越界）、`app/agent/execute` 及下游 stage、任何 LLM 层（`app/core/instructor_client` / `llm`）。

## 禁止行为

- 不得在 GROUND 内对候选做排名或评分——`GroundingResult` 不含排序字段，排序只能发生在 `SELECT`。
- 不得调用 LLM / 修改 KG 状态（`SpatialResolver` 只读查询）。
- 不得静默跳过未解析 spec（必须记 `StageIssue`，否则门无法正确路由 EXPLORE）。
- `retrieve_evidence` 不得抛异常打断链（任何基础设施缺失只应减少行数或返回 `[]`）。
- `format_bound_intent.py` 不得做坐标推断 / GIS 查询（多候选只作为语义 hint，绝不能成为道路端点等硬输入）。

---

## 相关文档

- `../README.md` — agent 编排层总览
- `../bootstrap/graph.py` / `post_l3_main_nodes.py` — GROUND 在 post-L3 主图中的 EXPLORE 重试
- `../select/README.md` — SELECT（下游消费者：`GroundingResult` → `SiteSelectionDecision`）
- `app/modules/spatial_ops/grounding/resolver.py` — 空间解析器
