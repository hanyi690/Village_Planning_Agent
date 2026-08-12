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

当前实现已引入 `context_ref`、统一 `artifact_refs` 及
`infrastructure/artifacts/runtime.py` 的 session、run、context version、类型和 checksum 校验。
阶段 payload 已从根状态移入 CAS artifact；`AgentState` 仍保留较多 L1-L3 控制、HUMAN 和重试
channels，因此 checkpoint 尚未达到本节定义的最小 `WorkflowState` 运行 schema。`layout_configs`
只作为 EXECUTE artifact，不得重新加入父图状态。

此外，默认 ArtifactStore 仍依赖相对 `.run-tmp` 路径；测试和运行器必须显式隔离 store、session 与 run。
PARSE 必须在产物写入前获得稳定 context version，否则后续阶段的严格引用校验会拒绝该产物。

## 1.2 Checkpoint resume planner（目标契约）

LangGraph checkpoint 只回答“图从哪里继续”，不回答“哪些业务产物仍可复用”。因此系统必须在 checkpoint API 和恢复执行之间增加一个纯函数 `ResumePlan`：

```json
{
  "session_id": "session-1",
  "checkpoint_id": "checkpoint-1",
  "mode": "resume_checkpoint | resume_interrupt | rerun_from_stage | completed | blocked",
  "resume_from": "SELECT",
  "checkpoint_kind": "layer | revision | human | completed | intermediate",
  "reuse": ["l1_snapshot", "l2_strategy", "planning_program", "grounding_result"],
  "rerun": ["SELECT", "EXECUTE", "VALIDATE", "RECONCILE", "DELIVER"],
  "reason": "new SELECT-level deferral revision",
  "context_version": "...",
  "context_fingerprint": "...",
  "input_checksums": {},
  "output_checksums": {},
  "graph_next": ["select"]
}
```

恢复判定必须遵循以下优先级：

1. **pending interrupt 优先**：有真实 `PregelTask.interrupts` 时，只能使用对应 channel 的 `Command(resume=...)`；不能把 `snapshot.next` 当成普通继续执行。
2. **context 身份优先**：`context_version`、`context_fingerprint` 或 artifact ref 不一致时，禁止混用旧产物，生成新的 revision 或从最早受影响阶段重跑。
3. **artifact 依赖优先**：`completed_dimensions` 只证明报告维度完成，不能证明 L1Snapshot、PlanningProgram、GroundingResult、SiteSelectionDecision、ExecutionPlan、PlannedState 和校验报告仍然有效。
4. **最小下游重跑**：保持上游不可变 artifact，按依赖边界从最早失效阶段生成新 artifact revision；不得从 `START` 重新调用所有 LLM。
5. **终态不可恢复**：`delivery_status` 已终态或 `diagnostic_terminal` 已写入时，必须明确新输入/新 revision，不能返回一个看似成功的空 resume。

当前实现新增 `backend/app/modules/schema/contracts/resume_contracts.py`，并由 checkpoint 列表/恢复 API 输出 `resume_plan`。这是恢复决策的统一入口；它还没有替代 LangGraph 的执行 cursor，也不会伪装成完整端到端保证。

这套设计直接采用官方对照结果：LangGraph 将 `thread_id` 定义为线程级持久化游标，`checkpoint_id` 可定位历史 checkpoint；`interrupt()` 恢复时节点从头重放，前置副作用必须幂等；默认子图只能在父图粒度进行 time travel，想在子图内部恢复必须明确配置子图 checkpoint。参考 [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)、[LangGraph subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs) 和 [LangGraph time travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel)。这些结论同时由本次 Exa 检索的官方 LangChain 文档交叉验证。

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
- 每个可恢复 checkpoint 都能生成 `ResumePlan`，明确 `reuse/rerun/reason`，并能区分普通继续、HUMAN 恢复、下游重跑和阻断。
- 从任意稳定阶段恢复时，验证不会重复执行已确认且 checksum 未变化的上游 LLM/artifact 节点。
- SELECT 修订、EXECUTE、VALIDATE、RECONCILE、DELIVER 必须在同一主 session 状态和 artifact revision 上闭合。
