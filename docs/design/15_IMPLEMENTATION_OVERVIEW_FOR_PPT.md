# 村庄规划智能系统总体实现说明（PPT 版）

> 本文将 `00_SYSTEM_DESIGN`、`01_LAYERED_ARCHITECTURE`、`02_DATA_PERSISTENCE`、
> `04_PLANNING_PIPELINE`、`07_VALIDATION_FEEDBACK`、`12_PLACE_NAME_RESOLUTION`、
> `13_AUTOREPAIR_MULTIMODAL` 和 `14_BACKEND_MODULE_BLUEPRINT` 整合为一套目标架构汇报叙事。
>
> 本文只描述最终目标设计、模块职责、接口边界和迁移实现顺序，不作为当前完成度报告。

## 一句话定位

这是一个“证据驱动、空间求解、可恢复、可审计”的村庄规划智能系统：

```text
多源资料与 GIS
  → 结构化事实与规划目标
  → 证据约束下的空间候选与组合求解
  → 确定性空间执行
  → 校验、定向修复、对账与可视化交付
```

LLM 负责理解、提议和排序；KG、空间算法、约束求解器和交付闸门负责事实、几何、规划决定和最终
可用性。系统不把一次 LLM 输出当成规划成果。

## PPT 建议结构

建议使用 12 页：

1. 项目定位与要解决的问题
2. 总体架构与权威边界
3. 从输入到交付的端到端闭环
4. 数据、状态与 Artifact 持久化
5. L1/L2/L3 与新业务主干的关系
6. 证据中心、KG 和地点反向解析
7. LLM 智能调度与 EXPLORE/Exa
8. 空间决策与确定性执行
9. VALIDATE 驱动的自动修复
10. 多模态证据链
11. 目标实施路线与模块完成定义
12. 目标验收标准与建设原则

---

## 第 1 页：项目定位与问题

### 要表达的核心观点

传统“文本解析 → 直接生成地图”的方式有四个结构性问题：

- 文本建议、KG 事实、空间候选和规划决定混在一起，无法判断谁是权威；
- LLM 可以生成看似合理但没有空间依据的名称、坐标、分类和布局；
- 失败往往只能整体重试，无法定位到受影响阶段；
- 图片、扫描图、规划图和遥感资料没有进入同一条可追溯证据链。

### 本系统的回答

将系统拆为四条清晰链路：

```text
事实链：数据 / KG / 报告 / 图片 → Evidence
决策链：Evidence → Claim → Program → Solver Decision
执行链：Decision → ExecutionPlan → Worker → ParcelChangeSet
审计链：Artifact → Event → Validation → Reconcile → Delivery
```

### 讲解重点

系统的目标不是“让 LLM 自己画图”，而是让 LLM 参与一个有边界的规划生产系统。

---

## 第 2 页：总体架构与权威边界

### 分层架构

```text
API / SSE
  → Application Use Cases
    → Workflow Orchestration
      → Planning Domain
        → Data / Spatial / Evidence Ports
          ← Infrastructure Adapters
```

### 六类权威状态

| 状态 | Owner | 作用 |
|---|---|---|
| `SessionDataSnapshot` | Data | 原始资料、GIS 输入、来源、CRS、BSM、质量信息 |
| `WorkflowState` | LangGraph checkpoint | 阶段控制、分支、gate 和 artifact refs |
| `StageArtifact` | CAS Artifact Store | L1/L2/L3、规划程序、候选、决策、执行和校验结果 |
| `RunEvent` | Event Repository | 运行过程、审计和 SSE replay |
| `PublicProjection` | Application query service | 面向前端的状态、HUMAN 和交付查询 |
| `DeliverySpatialSnapshot` | DELIVER | 最终 current/planned/overlay/土地平衡/渲染/导出的统一空间事实 |

### 关键边界

- API 不直接读取 AgentState、GIS 原始字典或文件夹中的“最新文件”；
- Workflow 只编排，不承载规划业务逻辑；
- KG 只返回事实、关系、证据、置信度和 provenance；
- EXECUTE 只执行已经批准的 `SiteSelectionDecision + ExecutionPlan`；
- 渲染、导出、土地平衡和地图 API 只读取同一个 `DeliverySpatialSnapshot`。

---

## 第 3 页：端到端实现闭环

### 目标业务主干

```text
INGEST
  → ASSESS
  → OBJECTIVES
  → HUMAN OBJECTIVE GATE
  → DEMAND
  → SUITABILITY
  → PORTFOLIO ALLOCATION
  → HUMAN PORTFOLIO GATE
  → MATERIALIZE
  → VALIDATE
  → SCENARIO EVALUATE
  → DELIVER
```

### 认知视图与业务主干的关系

```text
SessionDataSnapshot / KG / 报告
  → L1 / L2 / L3
  → PlanningProgram
  → TARGET_PROJECTION
  → GROUND
  → SELECT
  → EXECUTE
  → VALIDATE
  → RECONCILE
  → DELIVER
```

### 必须说明的关系

L1/L2/L3 保留为认知、报告和审查视图；最终业务主干不依赖“报告正文逐层传递后直接执行”。目标
转换关系是：

```text
L1/L2/L3 认知产物
  → typed claims / objectives / demand / program
  → 确定性空间阶段
```

---

## 第 4 页：数据、状态与 Artifact 持久化

### 输入边界

所有资料先进入数据层并冻结为 `SessionDataSnapshot`，空间数据再由数据层提供
`SpatialWorkspace`。Agent/Workflow 不接收裸 `gis_data`、完整 GeoJSON 或可变上传对象。

### Artifact 链

```text
CAS blob:       blobs/sha256/{digest}
Descriptor:     descriptors/{digest}.json
Run reference:  runs/{run_id}/branches/{branch_id}/refs/{artifact_key}.json
```

每个 Artifact 至少有 schema/version、digest、parents、producer stage、run/branch、时间和 provenance。

### Resume 与分支

- checkpoint 只保存控制字段和 descriptor refs；
- 普通历史续接创建新 `branch_id`；
- HUMAN resume 使用当前 pending interrupt 和官方 resume 协议；
- 重放必须幂等，旧 blob 和旧 revision 永不覆盖；
- 父 digest 不一致时从最早失效阶段重跑。

### PPT 结论

持久化不是“保存一份 JSON”，而是保存一条可验证的规划因果链。

---

## 第 5 页：L1/L2/L3 如何进入新的架构

### L1：观察与事实

产出报告事实、问题、位置提及、类型、来源页码、文本 span 和初步证据引用。

### L2：策略与约束

将观察事实组织为服务缺口、发展策略、空间约束、优先级和干预方向。

### L3：规划程序候选

LLM 只产生 `PlanningClaimSet` 或 `ProgramProposal`；确定性 `ProgramAssembler` 将其组装为权威
`PlanningProgram`。分类闭集、空间目标和决策状态缺失时必须产生显式 HUMAN 请求。

### 新架构中的转换

```text
L1 Observation
  → AssessmentSnapshot
L2 Strategy
  → ObjectivePortfolio / DemandPortfolio
L3 Proposal
  → PlanningProgram
PlanningProgram
  → Target Projection / GROUND / SELECT
```

### 关键原则

报告摘要不是权威事实；Markdown 不是规划状态；JSON Schema 只约束传输，不替代规划正确性。

---

## 第 6 页：证据中心、KG 与地点反向解析

### EXPLORE 的定位

EXPLORE 是横向证据服务，不是固定主阶段。任何阶段发现缺证据时，都必须提交：

```text
ExplorationRequest
  = stage + query_purpose + required_facts
    + entity_scope + parent_artifact_refs
```

EXPLORE 返回 `EvidenceBundle / ExplorationResult`，包含来源、版本、冲突和未决状态。

### L1 语义增强与反向定位

```text
报告：祠堂@社前村
  → L1LocationFact：祠堂，role=facility
  → RelationEvidence：祠堂 located_in 社前村
  → 反向关系索引：社前村 ← 祠堂
  → 社前村 geometry / centroid / BSM
  → PlaceResolutionResult
  → GROUND candidate refs
```

同样支持：

```text
设施 / 地标 / 道路 / 水体
  ↔ 位于 / 服务 / 邻近 / 连接
  ↔ 自然村
```

`PlaceResolutionResult` 必须保留 `resolved / ambiguous / unresolved`、候选 refs、geometry/BSM
refs、evidence refs、relation refs、query trace、context/KG/index version。解析不得直接写
`SiteSelectionDecision`。

### 决策证据如何获得

优先级为：

1. session KG canonical name / alias；
2. L1 typed location facts；
3. directed/inverse relation、实体类型和拓扑一致性；
4. VillageBundle 几何与 BSM；
5. 外部 gazetteer / search；
6. 模糊匹配仅用于产生候选，不得自动选第一个。

---

## 第 7 页：LLM 智能调度、EXPLORE 与 Exa

### 智能调度不是取消确定性流程

```text
WorkflowState + GateDecision + EvidenceGap
  → LLM DispatchProposal
  → DispatchPolicy
  → DispatchCommand / LangGraph Send
  → EXPLORE / Worker / Domain Solver
```

LLM 可以提出查询计划、工具选择、并行 worker 和下一阶段候选；不能直接修改 WorkflowState，
不能越过 Gate、solver、HUMAN 或触发 EXECUTE。

### Exa 的放置方式

```text
EXPLORE
  → local KG / Bundle / reports / typed artifacts
  → ExternalSearchPort
    → ExaSearchAdapter
  → ExternalSearchResult
  → claim normalization + conflict check
  → EvidenceBundle
```

Exa 是可替换的外部证据 provider，不是事实 owner。请求需要记录查询目的、实体别名、来源策略、
域名白名单、freshness、search mode、内容预算、父 refs 和幂等键。结果需要记录 request ID、URL/ID、
highlights 或 full-text ref、来源元数据、抓取状态、成本、延迟和 provenance。

### Exa 结果的使用边界

- 优先使用 highlights 控制上下文和成本；
- full text 只在 typed evidence gap 要求时获取；
- structured output 只能作为带来源的 claim draft；
- 不得由搜索结果直接创建坐标、BSM、分类、地块变化或选址决定；
- 无 key、超时、空结果、来源冲突和超预算都进入 typed unresolved / HUMAN。

### PPT 结论

新架构仍然可以实现 LLM 智能调度，但调度的是“下一步可执行命令”，不是“最终规划事实”。

---

## 第 8 页：空间决策与确定性执行

### 规划形成

```text
ObservedNeed
  → PlanningObjective
  → Evidence-backed Claim
  → Intervention Candidate
  → Spatial Feasibility
  → Portfolio Decision
  → Approved PlanningTarget
```

### 空间决策分层

- `SUITABILITY`：按空间需求准备数据、硬排除、指标统一、候选定位和逐项评分；不做最终分配；
- `PORTFOLIO ALLOCATION`：构造容量、需求、约束和目标，调用 MIP/CP/规则求解器；
- `GROUND`：把地点、实体和证据绑定为空间候选；
- `SELECT`：在候选之间做最终分配并返回 solver/decision status；
- `MATERIALIZE/EXECUTE`：按 `ExecutionPlan` 生成 geometry operation、`ParcelChangeSet` 和
  `PlannedState`。

### EXECUTE worker 边界

```text
ExecutionPlan
  → Project / Zone / Facility / Road / Axis Workers
  → WorkerResult
  → fan-in + 冲突检测
  → ExecutionResult
    ├── ParcelChangeSet
    ├── PlannedState
    └── DeferralLedger
```

Worker 不重新分类、不按名称猜地点、不直接发事件、不从 KG POI 自行选址。

---

## 第 9 页：VALIDATE 驱动的有界自动修复

### 反馈闭环

```text
EXECUTE
  → VALIDATE
  → diagnose issue / responsible stage
  → ValidationReport.adjustments
  → ValidationAdjustmentExecutor
  → earliest affected stage replay
  → VALIDATE
  → RECONCILE / DELIVER
```

### 修复契约

`ValidationAdjustment` 包含 responsible stage、affected target refs、input/evidence refs、有限参数、
parent digests、issue fingerprint、幂等键和 provenance。

每轮产生 `IterationRecord`：轮次、fingerprint、父 checksum、调整、受影响目标、前后检查、空间 diff
和新 checksum。

### 安全边界

允许：面积/硬约束参数、合法候选范围、分类缺口、设施缓冲/面积、道路/轴线合法性。

禁止：猜坐标、扩大无证据候选池、修改源图层、跨系统映射、LLM 自由覆盖 PlannedState、直接触发
EXECUTE。

### 收敛规则

- 最多两轮；
- 相同 fingerprint + 输入 checksum 立即停止；
- 发生振荡时回滚稳定 revision；
- 证据不足、预算耗尽或仍失败时进入 HUMAN、partial 或 diagnostic_only；
- 只有产生新的 typed artifact refs 且父链完整，才能继续后续阶段。

---

## 第 10 页：多模态证据链

### 统一媒体链

```text
上传图片 / 扫描图 / 规划图 / 遥感 / 现场照片
  → ImageArtifact
  → OCR / layout / legend / vision
  → ImageEvidence / VisualFact
  → L1/L2/L3 或 GROUND
  → EXECUTE
  → VisualReview
  → VALIDATE.adjustments
  → RECONCILE / DELIVER
```

### 四类核心产物

| 产物 | 责任 |
|---|---|
| `ImageArtifact` | 媒体存储、sha256、MIME、尺寸、来源、页码、CRS、bbox、预处理引用 |
| `ImageEvidence` | OCR、版面、图例、标签、区域、置信度、空间/时间状态和 provenance |
| `VisualFact` | 带 evidence refs 的 typed 观察事实 |
| `VisualReview` | 目标绑定、规划图问题、证据 refs 和 ValidationAdjustment 关联 |

### 使用规则

- root checkpoint 只保存媒体 refs/checksum，不保存完整图片或 base64；
- 可靠 CRS/bbox/map reference 才能辅助 GROUND；
- 视觉模型只能提供证据和评分，确定性 GIS 仍是空间权威；
- exact、ambiguous、unresolved 必须分开；
- 视觉失败时降级到 OCR、文本、KG、Bundle 或 HUMAN；
- MiniMax vision、OCR 和媒体存储都通过 adapter/port 接入。

---

## 第 11 页：目标实施路线与模块完成定义

### 推荐迁移顺序

| 阶段 | 主要工作 | 迁移出口 |
|---|---|---|
| 1 | CAS Artifact Repository、Event Repository | 不可覆盖、可审计、可恢复 |
| 2 | Application commands/queries/UoW | API 不再直读 runtime/store |
| 3 | `WorkflowState`、stage adapter、DispatchPolicy | 根图只编排，LLM 调度受策略控制 |
| 4 | Claims、ProgramAssembler、分类闭集、solver | LLM 提案与权威规划决定分离 |
| 5 | EvidenceBundle、L1LocationFact、PlaceEvidenceIndex、Exa port | L1 → KG → 反向关系 → GROUND 闭环 |
| 6 | SelectionProblem、ExecutionPlan、WorkerResult | 空间执行只消费批准决策 |
| 7 | ValidationAdjustment、媒体 artifact、VisualReview | 自动修复与多模态接口先冻结再接线 |
| 8 | DeliverySpatialSnapshot、API/SSE 投影 | 统一交付输入，删除旧入口 |

每个阶段遵循：

```text
新接口冻结
  → fake/contract/integration tests
  → 唯一调用点切换
  → 删除旧实现
  → 真实数据验收
```

不建立长期双写和兼容 facade。

### 每个模块的目标完成定义

- 输入/输出 contract 唯一，禁止 `Any`、legacy 分支和隐式默认值；
- owner、依赖方向和 provider 边界通过 architecture tests；
- 失败返回 typed result，不静默返回空集合或默认成功；
- Artifact 具备 schema、digest、parents、版本和 provenance；
- checkpoint replay 幂等，历史 artifact 和 revision 不覆盖；
- 有真实数据 integration 和端到端验收证据；
- 地点语义模块必须覆盖 L1 → PlaceEvidenceIndex → GROUND 及反向关系；
- 自动修复模块必须覆盖 adjustment、fingerprint、预算和 rollback；
- 多模态模块必须覆盖 media artifact、target binding、VisualReview 和失败降级；
- 外部搜索模块必须覆盖 source policy、allowlist、freshness、成本、幂等和冲突路由；
- 地图相关模块必须读取并检查最终 PNG/HTML/GeoJSON，而不是只检查文件存在。

---

## 第 12 页：验收标准与下一步

### 端到端验收

必须证明：

```text
现状报告 + VillageBundle + Session KG + 多模态输入
  → typed facts / claims / objectives / demand
  → PlanningProgram
  → target projection / GROUND / SELECT
  → ExecutionPlan
  → WorkerResult / ParcelChangeSet / PlannedState
  → VALIDATE / auto-repair or HUMAN
  → RECONCILE
  → DeliverySpatialSnapshot
  → PNG / HTML / GeoJSON / Manifest
```

### 重点目标验收用例

1. `祠堂@社前村` 能通过正向/逆向 KG 关系解析到社前村 geometry/BSM；
2. 自然村能反查其设施、地标、道路，且保留 relation refs、source refs 和 query trace；
3. 同名、冲突、无几何、模糊关系不会默认选第一个候选；
4. LLM `DispatchProposal` 必须经过 `DispatchPolicy` 才能成为 `DispatchCommand`；
5. Exa 结果可重放、可审计、可限预算，失败不突破 GROUND/SELECT/EXECUTE 边界；
6. 自动修复能从 ValidationReport 调整最早受影响阶段，并证明 fingerprint/rollback/预算规则；
7. 图片证据能绑定 target，进入 L1/L2/L3 或 GROUND，并在视觉问题时生成 VisualReview；
8. 当前地类、规划地类、项目、设施、道路、土地平衡和交付 manifest 都来自同一 snapshot；
9. 没有真实 `ParcelChange` 时，系统必须标记 `partial`，不能把现状复制图描述为完整规划成果；
10. 关闭并重开 checkpoint 后，已完成阶段不重复调用，新的分支不覆盖历史 artifact。

### 目标建设原则

1. 先冻结 contract 和 port，再实现 adapter，最后切换唯一调用点；
2. 先完成本地证据闭环，再接外部搜索和更强模型；
3. 先让 LLM 产生可审计提议，再由策略、规则和 solver 形成权威决定；
4. 先保证每个阶段可暂停、恢复、重放，再追求更高自动化程度；
5. 任何不确定性都显式保留为 ambiguous、unresolved、HUMAN 或 partial；
6. 只有 provenance、版本、空间结果和交付检查全部闭合，模块才算完成。

## 结尾页可使用的总结句

> 我们建设的不是一个“会生成地图的 LLM”，而是一条由 LLM 提议、证据约束、空间求解、确定性执行、
> 自动校验和人工兜底共同组成的村庄规划生产线。它的核心价值是：每个规划结论都能追溯到证据，
> 每次空间变化都能追溯到决策，每次失败都能定位到阶段，并且整个过程可以暂停、恢复、重放和审计。

## 参考文档

- [00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md)
- [01_LAYERED_ARCHITECTURE.md](01_LAYERED_ARCHITECTURE.md)
- [02_DATA_PERSISTENCE.md](02_DATA_PERSISTENCE.md)
- [04_PLANNING_PIPELINE.md](04_PLANNING_PIPELINE.md)
- [07_VALIDATION_FEEDBACK.md](07_VALIDATION_FEEDBACK.md)
- [12_PLACE_NAME_RESOLUTION.md](12_PLACE_NAME_RESOLUTION.md)
- [13_AUTOREPAIR_MULTIMODAL.md](13_AUTOREPAIR_MULTIMODAL.md)
- [14_BACKEND_MODULE_BLUEPRINT.md](14_BACKEND_MODULE_BLUEPRINT.md)
