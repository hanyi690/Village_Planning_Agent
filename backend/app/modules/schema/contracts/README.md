# Schema Contracts — 跨层数据契约索引

> 村庄规划系统**所有阶段 artifact 与共享事实的类型化契约**。目录内每个文件对应一个阶段或一个共享领域，供 PARSE / GROUND / SELECT / EXECUTE / VALIDATE / RECONCILE / DELIVER 与共享层消费。
> **Updated: 2026-08-10**（`layout_contracts.py` 已在前序批次删除，勿再引用）

---

## 职责边界

**负责**：定义类型化契约（Pydantic `BaseModel` + `Enum`），作为跨层数据交换的唯一事实来源。契约只描述结构，不含任何计算/IO。

**不负责**：
- 不做任何读取（数据库 / 文件 / KG / LLM）—— 契约是纯类型
- 不包含实现逻辑（映射 / 编译由 `modules/parsing`、`spatial_ops` 等消费方完成）
- 不代替 `schema/types/`（类型契约 ≠ 空间要素类型定义）

---

## 输入/输出契约（按阶段分组）

**索引约定**：文件 → 主要契约类 → 生产阶段 → 消费阶段。

### L1 现状

| 文件 | 主要契约类 | 生产 | 消费 |
|---|---|---|---|
| `l1_contracts.py` | `L1Snapshot` / `L1DimensionFragment` / `EvidenceGap` | L1 现状分析 | EXPLORE / L2 汇总 |

### L2 策略

| 文件 | 主要契约类 | 生产 | 消费 |
|---|---|---|---|
| `l2_contracts.py` | `L2Strategy` / `L2StrategyFragment` / `StrategyConflict` / `StrategyIssue` | L2 策略 | L3 编制 / 对账 |

### L3 项目

| 文件 | 主要契约类 | 生产 | 消费 |
|---|---|---|---|
| `l3_contracts.py` | `PlanningProgram` / `L3ProgramFragment` / `PlanningIntervention` / `InterventionDependency` / `ProgramIssue` | L3 详细规划 | EXECUTE / RECONCILE |

### PARSE 解析

| 文件 | 主要契约类 | 生产 | 消费 |
|---|---|---|---|
| `parse_contracts.py` | `SpatialPlanningIntent` / `ZoneTarget` / `FacilityTarget` / `AxisTarget` / `RoadTarget` / `ProjectTarget` / `SpatialOperation` / `SpatialConstraint` / `ThreeZonesThreeLines` / `PlanningIndicatorTable` | PARSE | EXECUTE / GROUND / KG L3 |
| `parse_result_contracts.py` | `IntentCompilationResult` / `CompilationError` / `CompilationPatch` / `ParseDiagnostic` / `ParseTrace` / `ParseRevisionRequest` | PARSE 编译器 | agent/parse 编排 |
| `spatial_reference_contracts.py` | `SpatialReferenceSpec` / `CandidateSet` / `ResolvedSpatialRef` / `GeometryRef` / `RefObject` | PARSE / GROUND | spatial_ops / kg 适配器 |

### GROUND 空间接地

| 文件 | 主要契约类 | 生产 | 消费 |
|---|---|---|---|
| `grounding_contracts.py` | `GroundingResult` / `CandidateSite` / `HardConstraintResult` / `SpatialQueryEvidence` | GROUND | SELECT / EXECUTE |

### SELECT 选址

| 文件 | 主要契约类 | 生产 | 消费 |
|---|---|---|---|
| `selection_contracts.py` | `SiteSelectionDecision` / `RankedCandidate` / `EliminatedCandidate` / `LandDesignBrief` | SELECT | EXECUTE 落地 |

### EXECUTE 执行

| 文件 | 主要契约类 | 生产 | 消费 |
|---|---|---|---|
| `execution_plan_contracts.py` | `ExecutionPlan` / `WorkerTask` / `WorkerResult` / `ZoneAssignmentEntry` / `ParcelAllocationProblem` / `ZoneAllocationSolution` / `RoadPlanResult` | EXECUTE 规划 | EXECUTE workers（zone / road / parcel） |
| `parcel_change_contracts.py` | `ParcelChangeSet` / `ParcelChange` / `FacilityChange` / `RoadChange` / `SettlementChange` | EXECUTE 落地 | planned_state / 导出 |
| `planned_state_contracts.py` | `PlannedState` / `PlannedParcel` / `PlannedZone` / `PlannedFacility` / `PlannedRoad` / `PlannedAxis` | EXECUTE 成果 | KG L4 / 导出 / 对账 |

### VALIDATE 校验

| 文件 | 主要契约类 | 生产 | 消费 |
|---|---|---|---|
| `validation_report_contracts.py` | `ValidationReport` / `ValidationCheck` / `ValidationIssue` / `ConstraintAdjustment` | VALIDATE | 反馈 / 人工审核 |

### RECONCILE 对账

| 文件 | 主要契约类 | 生产 | 消费 |
|---|---|---|---|
| `reconciliation_contracts.py` | `ReconciliationReport` / `CoverageMatrix` / `CoverageMatrixRow` / `ReconciliationInconsistency` | RECONCILE | DELIVER / 反馈 |

### DELIVER 交付

| 文件 | 主要契约类 | 生产 | 消费 |
|---|---|---|---|
| `delivery_manifest_contracts.py` | `DeliveryManifest` / `DeliveryGate` / `Deliverable` / `TraceabilityEntry` / `HumanItem` | DELIVER | 导出 / API |

### 共享 / 跨阶段

| 文件 | 主要契约类 | 说明 |
|---|---|---|
| `contract_meta.py` | `ContractMeta` / `StageStatus` / `StageIssue` | 所有 `ContractMeta` 的基类 |
| `provenance.py` | `Provenance` / `SemanticMetadata` | 溯源与语义元数据 |
| `classification_ref.py` | `ClassificationRef` | L1 现状地类分类引用 |
| `context_contracts.py` | `ContextBlock` / `ContextBlockType` / `SpatialCognitiveUnit` / `FacilityAnchor` / `TerrainSample` / `ResidentialClusterAnchor` / `ConstraintZoneAnchor` / `SpatialRelation` / `TerrainProfile` | 空间认知卡片（spatial_ops 产出，prompts/agent 消费） |
| `context_ref_contracts.py` | `PlanningContextRef` / `DatasetRef` / `ContextVersion` | 运行/数据集上下文引用 |
| `evidence_contracts.py` | `EvidenceBundle` / `EvidenceFact` / `EvidenceSource` / `ExplorationRequest` / `ExplorationResult` / `SpatialCognitionEvidence` / `EvidenceGapResolution` | EXPLORE 证据探索 |
| `constraint_contracts.py` | `PlanningConstraint` / `ConstraintSet` / `CompiledConstraint` / `CompilationReport` / `ConflictRecord` / `DroppedItem` | 约束模型（PARSE / EXECUTE 共享） |
| `workflow_contracts.py` | `GateDecision` / `RoutingDecision` / `FeedbackRoute` / `PlanningRunRequest` / `PendingRequest` | 工作流控制 / Gate |
| `resume_contracts.py` | `ResumePlan` / `ResumeMode` | checkpoint 恢复计划：区分 interrupt resume、checkpoint continue、下游重跑和阻断 |
| `human_interrupt_contracts.py` | `HumanInterrupt` / `HumanInterruptItem` / `HumanInterruptChannel` | step-mode 与 post-L3 共用的 HUMAN interrupt payload |
| `review_contracts.py` | `ReviewPackage` / `ReviewDecision` / `HumanReviewRequest` / `ReviewComment` / `ReviewStatus` | 人工审核包与决策 |
| `gazetteer_contracts.py` | `GazetteerEntryLike` | 村名→空间实体解析的端口类型 |
| `land_balance_contracts.py` | `LandBalanceTable` / `LandBalanceRow` | 用地平衡表（EXECUTE / 导出） |
| `custom_zone_contracts.py` | `CustomZoneTarget` / `TypingRule` / `Vocabulary` / `VocabularyCategory` | 词汇驱动自定义功能区语义（仅保留词汇/功能区语义，不承载第二套执行目标模型） |
| `parsing_contracts.py` | `CompilationProfile` / `CompilerTrace` | 编译 profile 枚举与编译痕迹 |

---

## 依赖方向

```
agent 编排层 / services / tools
        │
        ▼
schema/contracts/*（纯类型，无 IO 无计算）
   ▲  modules/spatial_ops、modules/parsing、modules/kg 均依赖本目录
```

- 允许：标准库 + `pydantic`；`contract_meta.py` / `provenance.py` 等被其余契约文件继承
- 禁止：契约文件 import `data` / `kg` / `spatial_ops` / `agent` / `tools`

---

## 禁止行为

- **引用已删除的 `layout_contracts.py`**（前序批次已删除；与 `execution_plan_contracts` 的遗留重叠不再存在）
- 从 `__init__.py` 走 wildcard 再导出作为**新业务代码**的导入入口 —— `contracts/__init__.py` 仍保留 `from .* import *`（legacy 兼容），新代码必须从具体契约文件导入（设计文档迁移规则 §7）
- 在契约文件里放置可执行逻辑 / 计算 / IO
- 新增与既有契约语义重叠的第二套模型（`custom_zone_contracts.py` 只保留词汇/功能区语义）
