# 金田村真实 Session 人类可读审计报告

## 先说结论

这次运行确实完成了七个阶段的离线闭环：

`PARSE → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER`

但必须准确区分两件事：

1. 报告、10 个 GIS 文件、SQLite、KG、ArtifactStore 和七阶段节点是真实执行的。
2. 本次七阶段回归为了稳定性使用了确定性 stage adapter；仓库配置的真实 LLM 已单独通过 `qwen3.7-plus` 连通性测试，但没有把真实远程 LLM 结果冒充为本次七阶段结果。

因此，本报告适合检查阶段契约、ref、checksum 和渲染层结果；不适合作为真实 LLM 质量评估报告。

## Session

- Session ID：`8f086e9b-1a27-41ef-8815-26c5eae6de04`
- Context version：`1`
- 最终 Gate：`DELIVER = PASS`
- 阶段数量：7 个主阶段，每阶段 `stage_started + stage_completed`
- KG：25,693 triples；road intersects 365；sfTouches 1,691；water touches 0

## 阶段输入/输出摘要

| 阶段 | 实际输入 | 实际输出 | Gate | 用途 |
|---|---|---|---|---|
| PARSE | `current_report.md` + 10 个 GeoJSON + context_ref | `IntentCompilationResult` | PASS | 将规划程序编译为结构化意图 |
| GROUND | `intent_compilation` + GIS/KG context | `GroundingResult` | PASS | 产生空间证据和候选 |
| SELECT | `intent_compilation` + `grounding_result` | `SiteSelectionDecision`、`ExecutionPlan` | PASS | 选址并生成执行计划 |
| EXECUTE | `ExecutionPlan` + `SiteSelectionDecision` + context_ref | `ParcelChangeSet`、`PlannedState`、`AllocatedGeoJSON` | 无独立 Gate | 生成地块变更和规划状态 |
| VALIDATE | `PlannedState` + `ParcelChangeSet` | `ValidationReport` | PASS | 校验规划结果 |
| RECONCILE | 上游 refs + `PlanningProgram` | `ReconciliationReport` | PASS | 对齐规划程序与执行结果 |
| DELIVER | `PlannedState` + validation/reconciliation refs | `DeliveryManifest`、`RenderLayers` | PASS | 交付和前端图层渲染 |

完整机器审计数据在：[完整阶段输入输出报告](F:\project\Village_Planning_Agent\docs\audits\real-session-stage-report-sample.md)。

## 最终渲染结果

本次没有生成 PNG；DELIVER 输出的是前端可消费的 GeoJSON 图层。

### 图层清单

| layerType | layerName | geometry | 要素数 | 关键属性 |
|---|---|---|---:|---|
| `function_zone` | 功能分区 | Polygon | 1 | `bsm=REAL-P1`、`planning_land_use=0701`、`zone_type=0701`、`operation=reclassify`、`area_ha=0.0` |

### 图层文件

[打开渲染 GeoJSON](F:\project\Village_Planning_Agent\docs\audits\real-session-render-layers-sample.geojson)

其几何坐标是：

`POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))`

### ArtifactStore 引用

`render_layers-8f086e9b-1a27-41ef-8815-26c5eae6de04-40f673a05601e08a`

运行时 API：

`GET /api/sessions/8f086e9b-1a27-41ef-8815-26c5eae6de04/stage-report.md`

定位 API：

`GET /api/sessions/8f086e9b-1a27-41ef-8815-26c5eae6de04/positioning-trace`

## 如何用于优化

当前最值得修复的真实断点不是“报告没有记录”，而是：

- GROUND 的 `candidates` 为空，说明真实候选生成尚未证明有效；
- SELECT 仍由确定性 adapter 选出 `REAL-P1`，不能代表真实模型选址质量；
- RenderLayers 只有 1 个 `function_zone`，没有真实 `planned_project`、`facility_point` 或 `planned_road` 图层；
- `DeliveryManifest.statutory_complete=false`，虽然业务 Gate 被测试 adapter 强制设为 PASS；
- 因此不能把本次运行称为真实 LLM 规划质量通过。
