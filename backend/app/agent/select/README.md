# agent/select 子包（SELECT 选址决策）

> SELECT 阶段：`GroundingResult` + 意图需求 → `SiteSelectionDecision` → Select gate（PASS / RETRY_GROUND / HUMAN）。
> 对 GROUND 产出的候选做**排名、冲突分配与选优**，产出每个项目/设施落定的地块组合（BSM 级）与 `LandDesignBrief`。

---

## 职责边界

**做**：编排确定性选址（`select_aggregate`）：经 `adapter.grounding_to_candidate_parcels` 把 `GroundingResult.candidates` 桥接为 `CandidateParcel[]`；对每个 `ProjectTarget` 调 `spatial_ops/selection.select_parcel` 做**优先级顺序 + 冲突分配**（已占锚点累积，先占先得，后到者被拒）；空间项目只允许消费 `target_ref == target_id` 的候选，未绑定候选不会再回退给所有项目；设施用 `spatial_ops/selection/facility_location.solve_maximal_covering`（MCLP，已知服务半径时），但前提仍是已有目标专属 `candidate_bsms`；缺少目标专属候选时会直接以 `no_target_specific_candidates` 标记为 `unplaced`；`build_site_selection_decision` 聚合成 `SiteSelectionDecision`（`selected_combination` / `full_ranking` / `eliminated` / `decision_factors`）；`build_land_design_brief` 产出 `LandDesignBrief`；`evaluate_select_gate` 出 Select gate。

**不做**：不重新解析空间引用（那是 PARSE/GROUND）；不做任何地块几何变更（那是 EXECUTE）；不直接改 `GroundingResult` 排序——SELECT 的排名只存在于 `SiteSelectionDecision.full_ranking`。同一输入重复运行完全确定（`occupied` 锚点按输入顺序累积、`placement` 按项目顺序处理）。

### 目录文件

| 文件 | 职责 |
|---|---|
| `adapter.py` | `grounding_to_candidate_parcels` / `filter_parcels_for_target` / `candidate_site_to_parcels`：GroundingResult → CandidateParcel 桥接 |
| `aggregate.py` | `select_aggregate` / `build_site_selection_decision` / `build_land_design_brief`：确定性选址编排 |
| `gate.py` | `evaluate_select_gate` / `select_gate_route`：3 路门（纯函数） |
| `review.py` | `build_select_review_package`：构造审查包 |

### 流程图

```
   GroundingResult（candidates）+ SpatialPlanningIntent（project/facility targets）
        │                              + PlanningContext（constraint_index / anchors / bundle）
        ▼
   select_aggregate ──► adapter.grounding_to_candidate_parcels → CandidateParcel[]
        │                  ┌─ project: select_parcel（优先级顺序 + occupied 冲突分配）
        │                  └─ facility: solve_maximal_covering（MCLP）或 select_parcel
        ▼
   build_site_selection_decision → SiteSelectionDecision（selected_combination / full_ranking / eliminated）
        │        + build_land_design_brief → LandDesignBrief[]
        ▼
   evaluate_select_gate ──┬─ PASS        → EXECUTE
                          ├─ RETRY_GROUND → 目标数 > 已落位数（缺候选 → 回 GROUND 补候选）
                          └─ HUMAN       → 全落位但最高分 < 0.4（低置信度人工复核）
```

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 选址决策（根产物） | `app/modules/schema/contracts/selection_contracts.py` | `SiteSelectionDecision`、`RankedCandidate`、`EliminatedCandidate`、`LandDesignBrief` |
| 输入接地 | `app/modules/schema/contracts/grounding_contracts.py` | `GroundingResult`、`CandidateSite` |
| 输入意图 | `app/modules/schema/contracts/parse_contracts.py` | `SpatialPlanningIntent`、`ProjectTarget` |
| 门决定 | `app/modules/schema/contracts/workflow_contracts.py` | `GateDecision`、`PendingRequest` |
| 元数据 | `provenance.py` | `Provenance` |

`select_aggregate(result, intent, context)` 返回 `(SiteSelectionDecision, list[LandDesignBrief])`。post-L3 链中 `select_node` 用 `evaluate_select_gate(decision, target_count=len(project_targets))` 出 `select_gate`。

排名语义：`RankedCandidate.rank` 从 1 递增（先项目后设施）；`score_breakdown` 取 `ScoredCandidate.reasons` 的 5 维（proximity / construction / area_fit / road_access / service_coverage），后两维在外部网络/设施数据接入前保持 `0.0` 桩；`eliminated` 记录硬过滤原因（`allocated_to_higher_priority` 用于已占锚点冲突）。

设施选址：服务半径已知时走 `solve_maximal_covering`（MCLP，需求点取村锚点、回退 settlement 质心），并**就地写回** `facility.anchor_point`，使返回意图携带解析后的位置；否则走 `select_parcel`。

## 依赖方向

**可导入**：`app/modules/spatial_ops/selection`（`select_parcel` / `CandidateParcel` / `PlacementDecision` / `ScoredCandidate` / `SelectionTarget`）、`app/modules/spatial_ops/selection/facility_location`（`solve_maximal_covering` / `DemandPoint` / `FacilityCandidate`）、`app/modules/context/planning_context`、`app/modules/schema/contracts/*`。

**禁止导入**：`app/agent/ground` 的实现（只经 `GroundingResult` 契约交互）、`app/agent/execute` 及下游 stage、任何 LLM 层。

## 禁止行为

- **不得**在无安全依据时回退到全候选池；空间项目和设施都必须使用目标绑定候选，空 `target_ref` 不是有效的空间项目匹配。
- 不得修改 `GroundingResult` / 重跑 GROUND 逻辑（候选不足应走 `RETRY_GROUND` 路由，由 post-L3 链回 `ground` 节点）。
- 不得在 SELECT 内调用 LLM 或写 KG。
- 门路由必须纯函数化（`select_gate_route`），禁止在 aggregate 内内联放行。
- `decision_factors.best_score_by_target` 的 0.0 桩字段（road_access / service_coverage）不得被当作真实得分误用。

---

## 相关文档

- `../README.md` — agent 编排层总览
- `../bootstrap/graph.py` / `post_l3_main_nodes.py` — SELECT 的 RETRY_GROUND 回退路由
- `../ground/README.md` — GROUND（上游：`GroundingResult`）
- `../execute/README.md` — EXECUTE（下游消费者：`SiteSelectionDecision` + `LandDesignBrief`）
- `app/modules/spatial_ops/selection/` — 选址核心算法
