# 规划形成域边界

本文件记录重构分支当前已经接入主图的规划形成边界。它解决的不是“把输出换成 JSON”，而是把需求、空间可行性、组合分配和空间落地拆成不可互相越权的域。

## 主链

```text
PlanningClaimSet / typed intent projection
        |
        v
DemandPortfolio        只回答需要什么、多少、何时
        |
        v
SuitabilitySurface     只回答哪些候选可行、依据是什么
        |
        v
PortfolioDecision      只接受显式 SELECT 绑定，决定分配或未满足
        |
        v
ExecutionPlan          只保存任务、依赖、输入 artifact refs
        |
        v
ParcelChangeSet        唯一空间变更事实
```

## 模块职责

| 模块 | 生产者 | 允许读取 | 禁止行为 | 失败结果 |
|---|---|---|---|---|
| `app/domain/demand` | `derive_demand_portfolio` | typed intent 的目标字段 | 读取地块、候选、排名；推导规划编码 | 空需求或诊断 |
| `app/domain/suitability` | `build_suitability_surface` | `GroundingResult` | 选最终地点、修改需求量 | 候选排除原因、未解决项 |
| `app/domain/allocation` | `build_portfolio_decision` | Demand、Suitability、显式 SELECT | 发明候选、绕过硬约束、把 `ready` 当已落位 | `INFEASIBLE` / `unmet_demand` |
| `app/agent/execute` | `build_execution_plan` + workers | `ExecutionPlan` task binding、空间 workspace | 重分类、重选址、直接读报告文本 | typed task failure / deferral |

## 不变量

1. `DemandPortfolio` 不含 `source_parcels` 或候选排名。
2. `SuitabilitySurface` 不产生 `assigned`，只记录候选及证据。
3. `PortfolioDecision` 只接受 `TargetAssignment.status == "placed"` 的显式选择；`ready`、`unplaced`、缺候选和硬约束不通过均为未满足。
4. SELECT gate 只有 `OPTIMAL` 或明确允许的 `FEASIBLE` 才能放行；`INFEASIBLE`、`MODEL_INVALID`、`UNKNOWN` 转 HUMAN。
5. `ExecutionPlan` 不再嵌入 `intent` 或 `site_selection` 副本；worker 从 task 的 target binding 和独立 artifact refs 工作。
6. GIS 内容仍由 Data/Spatial 层持有。Agent checkpoint 只保存 `SpatialWorkspace` 的上下文引用和 artifact descriptor，不把完整地块集合塞进 AgentState。

## 当前边界与未完成项

L3 已改为 `PlanningClaimSet` structured output；`l3_aggregate` 不再调用 L3 Markdown/compiler，Demand 会保留 claim/evidence/location provenance。主图仍有一个 post-L3 typed-intent projection 过渡节点，下一步要把它替换为 domain stage command，并补齐 assessment/objectives、authoritative classification、真实 portfolio solver 和 scenario evaluation。真实 LLM + 真实 checkpoint + 实际规划变化 PNG/HTML 读取验收完成前，不得将整体规划链标为稳定或法定完成。
