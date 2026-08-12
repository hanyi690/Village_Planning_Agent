# agent/deliver 子包（DELIVER 交付清单）

> DELIVER 阶段：`SpatialWorkspace` + validated `ParcelChangeSet` + `DeliverySpatialSnapshot`（以及 Validation/Reconciliation）→ `RenderLayers` / `ExportResult` / `DeliveryManifest` → Deliver gate。
> post-L3 链的出口：组装可交付物清单、全链溯源、待人工项，并用硬门槛决定是否产出"完整法定成果"。

---

状态模型说明：历史 `gis_pipeline_state.py` 已删除，当前交付仅使用
`DeliverySpatialSnapshot`、`DeliveryManifest` 与 artifact refs。`PlannedState` 只在快照构建边界转成 planned overlay source，不再直接传给 renderer/exporter。

## 职责边界

**做**：编排交付清单（`deliver_aggregate`）：`build_traceability_from_coverage` 把 RECONCILE 的 `CoverageMatrix` 映射为 `TraceabilityEntry[]`；`build_deliverables_from_export` 把 `export_delivery_package` 的 `exported_files` 映射为 `Deliverable[]`；3 项交付检查（`check_statutory_layers_complete` / `check_traceability_complete` / `check_classification_for_statutory`）+ `collect_upstream_human_items` 汇总 HUMAN 门待决项为 `HumanItem[]`；经 `spatial_ops/land_balance.check_delivery_gate` 算 `DeliveryGate`（用地平衡闭合 / 三线冲突 / 保护侵入 / 变更比例 / 分区齐全）；`evaluate_deliver_gate` 出 Deliver gate（PASS / RETRY_VALIDATE / HUMAN）；`statutory_complete` 阻断"完整法定成果"（缺规划分类等 blocking 项时不出成品）。

**不做**：不重新规划/校验（只聚合上游产物）；不调用 LLM；不修改 KG。`export_delivery_package` 失败不影响 manifest 生成（`export_result=None` 时 `Deliverable[]` 为空，门经 `hi-layers-none-*` 转 HUMAN）。

### 目录文件

| 文件 | 职责 |
|---|---|
| `aggregate.py` | `deliver_aggregate` / `build_traceability_from_coverage` / `build_deliverables_from_export` / `collect_upstream_human_items` |
| `checks.py` | 3 项交付检查（含 `REQUIRED_STATUTORY_LAYERS` 常量） |
| `gate.py` | `evaluate_deliver_gate` / `deliver_gate_route`：3 路门（纯函数） |
| `review.py` | `build_deliver_review_package`：构造审查包 |
| `delivery_snapshot_builder.py` | 从 `SpatialWorkspace` 构建唯一 `DeliverySpatialSnapshot`，并编排同一 snapshot 的 render/export |
| `delivery_exporter.py` | 只消费 snapshot 和 render layers，写出交付包 |
| `delivery_validator.py` | 检查 current/planned 图层和几何可渲染性 |

### 流程图

```
   PlannedState + ValidationReport + ReconciliationReport + upstream_gates + export_result
        │
        ▼
   deliver_aggregate ──► coverage → TraceabilityEntry[]（RECONCILE 桥）
        │               export  → Deliverable[]
        │               checks  → HumanItem[]（blocking / non-blocking）
        │               land_balance.check_delivery_gate → DeliveryGate
        ▼
   DeliveryManifest（deliverables / traceability / pending_human_items / delivery_gate / statutory_complete）
        │
        ▼
   evaluate_deliver_gate ──┬─ PASS          → END（完整法定成果）
                           ├─ RETRY_VALIDATE → 唯一 blocking 类为 classification（回 validate）
                           └─ HUMAN         → 导出缺层 / 上游未决 / 平局 / 门槛失败
```

## 输入/输出契约

| 契约 | 文件 | 关键类型 |
|---|---|---|
| 交付清单（根产物） | `app/modules/schema/contracts/delivery_manifest_contracts.py` | `DeliveryManifest`、`DeliveryGate`、`Deliverable`、`TraceabilityEntry`、`HumanItem` |
| 输入溯源 | `app/modules/schema/contracts/reconciliation_contracts.py` | `CoverageMatrix` |
| 输入校验 | `app/modules/schema/contracts/validation_report_contracts.py` | `ValidationReport` |
| 门决定 | `app/modules/schema/contracts/workflow_contracts.py` | `GateDecision`、`PendingRequest`、`StageId` |

`deliver_aggregate(...)` 返回 `DeliveryManifest`。`DeliveryGate.failures` / `summary()` 提供可读诊断；`statutory_complete_breakdown` 记录门槛/阻断项/分类完整性三因。

门槛语义：`DeliveryGate.passed` 需同时满足用地平衡表闭合（±0.5%）、三线冲突数 = 0、保护侵入数 = 0、变更比例 ≤ 阈值（阈值未注入则视为通过）、必备分区齐全；`statutory_complete` = 门槛通过 + 无 blocking 人工项 + 规划分类完整（缺分类时 `check_classification_for_statutory` 产出 `hi-class-*` blocking 项，门路由 `RETRY_VALIDATE`）。`REQUIRED_STATUTORY_LAYERS` 为法定图层清单（`admin_area` / `current_landuse` / `planned_landuse` / `ecological_redline` / `farmland_protection` / `construction_zone`）。

## 依赖方向

**可导入**：`app/modules/spatial_ops/land_balance`（`check_delivery_gate`）、`app/modules/spatial_ops/output/export_package`（`export_delivery_package`，post-L3 `deliver_node` 内调用）、`app/modules/schema/contracts/*`。

**禁止导入**：任何 LLM 层；上游 stage 实现（只经 typed 契约交互）。历史 GIS 全量状态模型已删除。

## 禁止行为

- 不得在 DELIVER 内调用 VALIDATE/RECONCILE 的实现（只消费其报告）。
- 不得把 blocking 项静默降级（`statutory_complete` 必须受 blocking 与分类完整性约束）。
- 不得在 `checks.py` / `gate.py` 内做 I/O 或调 LLM（确定性纯函数）。
- `DeliveryGate` 阈值（`changed_parcels_threshold`）由交付策略注入，schema 不固化默认规则。

---

## 相关文档

- `../README.md` — agent 编排层总览
- `../../workflow/stages/deliver.py` — DELIVER 阶段入口；主图只负责注册和审计该入口
- `../reconcile/README.md` — RECONCILE（上游：`CoverageMatrix`）
- `../validate/README.md` — VALIDATE（上游：`ValidationReport`）
- `app/modules/spatial_ops/land_balance.py` — `check_delivery_gate`
- `app/modules/spatial_ops/output/export_package.py` — GDB 导出包
