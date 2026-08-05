# 数据、上下文与规划产物持久化

## 1. 持久化目标

持久化的核心对象不是“所有中间字段”，而是可恢复、可审计的版本化产物：

```text
Session
  └── PlanningContext(version)
      ├── VillageBundleRef
      ├── KGSnapshotRef
      ├── EvidenceBundleRef
      ├── L1SnapshotRef
      ├── L2StrategyRef
      ├── PlanningProgramRef
      ├── IntentCompilationResultRef
      ├── GroundingResultRef
      ├── SiteSelectionDecisionRef
      ├── PlannedStateRef
      └── ValidationReportRef
```

LangGraph checkpoint 只保存工作流恢复所需的状态和 artifact 引用；大体积 GeoJSON、报告和 KG 不塞进 State。

## 1.1 当前实现边界

上图是目标持久化模型。当前 `AgentState` 已显式保存 post-L3 的 delivery、validation、reconciliation
引用和 HITL 状态，但 L1Snapshot、L2Strategy、PlanningProgram、GroundingResult 和
SiteSelectionDecision 的引用仍主要由 aggregate 返回值、FilesystemArtifactStore 和 `run_id` 约定传递，
尚未全部成为主图 State 的强类型字段。`gis_agent_entry.py` 在引用缺失时仍可能重新执行 L3 aggregate。

因此当前 artifact store 已可用于恢复和审查，但尚未达到“所有阶段只通过显式 artifact ref 消费”的目标。

## 2. 数据分类

| 数据 | 权威存储 | 生命周期 | 版本要求 |
|---|---|---|---|
| 原始空间文件 | 文件对象 / Data Source | 长期 | hash、来源、坐标系 |
| `VillageBundle` | BundleStore + 文件缓存 | 会话/修订 | bundle version |
| `BaseFacts` | KG snapshot | 会话级 | source version |
| `DerivedRelations` | KG snapshot | 随 BaseFacts | relation version |
| 报告和证据 | ReportStore / EvidenceStore | 规划周期 | report revision |
| L1/L2/L3 artifact | ArtifactStore | 规划周期 | artifact version |
| `IntentGraph` | KG session graph | 规划周期 | intent revision |
| `PlannedState` | KG + GDB/export package | 长期 | plan revision |
| 渲染和诊断 | OutputStore | 可重建 | input artifact hash |

## 3. `PlanningContext` 一致性

任何子图开始前必须校验：

- Bundle、KG snapshot、报告 snapshot 属于同一 session。
- KG 的 `base_facts_version` 与 Bundle version 相匹配。
- 当前 artifact 的父版本仍是 active revision。
- 外部锚点已经过期时，返回 `EvidenceGap`，不得在读取期间偷偷刷新。

## 4. 外部数据与缓存

外部锚点、POI、行政编码和地图服务属于 Data 层的摄取行为：

```text
refresh_external_sources
  → normalize / dedup / provenance
  → write Bundle revision
  → rebuild BaseFacts / DerivedRelations
```

`load_village_bundle()` 只读取已生成的版本。探索过程中如果需要刷新，必须创建显式 `ExplorationRequest`，由 Data Adapter 执行并产生新版本。

## 5. 报告与结构化意图

报告分为两种：

1. `AnalysisReport`：供人阅读的分析结果，由 `content + instruction + provenance` 组成。
2. `Typed PlanningArtifact`：供后续节点消费的结构化结果，例如 `L1DimensionFragment`、
   `L1Snapshot`、`PlanningProgram` 和 `IntentCompilationResult`。

Markdown 不能作为 PARSE 的唯一输入；PARSE 必须优先消费带 revision 和 provenance 的报告 artifact。

### 5.1 当前 `DimensionReport.summary` 的兼容边界

当前 summary generator 不执行语义抽取，只按维度选择 Pydantic schema 并写入：

- `dimension_key`、`layer`
- 实际为字符数的 `word_count`
- 正文前 200 字符的 `text_summary`
- 空的 `key_points` 和 `metrics`
- 维度专属字段的默认空值

因此 `DimensionReport.summary` 是 **legacy / non-authoritative** 的兼容性预览，只能用于 UI 轻量
展示或迁移期回退，不能作为事实、指标、证据或 `L1Snapshot` 的来源。EXPLORE 的
`report_summary_index` 是另一套从报告正文构建的规则索引，也不等同于该字段。

持久化必须区分：

| 对象 | 用途 | 权威性 |
|---|---|---|
| `content` | 完整人类可读报告 | 报告表达权威 |
| `instruction` | 从 `【INSTRUCTION】` 剥离的机器提示 | 待验证输入 |
| legacy `summary` | 兼容预览 | 非权威 |
| typed artifact | fragment、snapshot、program、compilation result | 阶段机器消费权威 |

编译字段冲突时采用固定优先级：明确证据与 provenance → 报告正文 → `instruction` 中可验证的
结构信息 → legacy summary。后续消费者不得绕过 typed artifact 直接把 legacy summary 当事实。

## 6. 读取接口

目标接口：

```python
class PlanningContextProvider(Protocol):
    async def open(self, session_id: str) -> PlanningContext: ...
    async def refresh(self, session_id: str, reason: str) -> PlanningContext: ...
    async def commit_artifact(self, artifact: ArtifactEnvelope) -> None: ...
    async def get_artifact(self, ref: ArtifactRef) -> ArtifactEnvelope: ...
```

业务节点不直接调用 `DataCatalog`、`ReportStore` 或 KG manager；它们通过 Context Provider 和领域 ports 访问数据。

## 7. 验收条件

- 同一 session 的任意 checkpoint 可以恢复到明确的 context version。
- 重跑同一 artifact 不会隐式重新抓取外部数据。
- 每个成果图层都能追溯到 `SiteSelectionDecision`、`IntentCompilationResult`、
  `PlanningProgram` 和原始证据。
- 删除或刷新数据时不会产生无来源的孤立 KG 节点。
