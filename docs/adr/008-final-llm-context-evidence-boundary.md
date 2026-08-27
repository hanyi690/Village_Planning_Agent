# ADR 008：LLM 上下文、证据检索与结构化调用的最终边界

## 状态

Accepted — final boundary for the current implementation

本 ADR 取代 ADR 007 中关于 `FactRegistry`、`ProjectCognitionView`、
`FactProjection`、旧报告正文兼容读取和 `grounded_anchors` 的目标描述。代码只
保留本 ADR 列出的当前契约；不再为旧调用方增加适配器、别名或双写路径。

## 1. 目标与硬约束

系统要解决的不是简单地把 prompt 截短，而是让每一次调用都只看自己负责的
数据投影，并且让结构化输出在模型不支持 native tool/schema 时仍然能够稳定
完成本地校验。

硬约束如下：

1. L1、L2、L3、GROUND、SELECT 的检索输入和分析输入分离；检索计划、查询轨迹、
   原始返回、完整 KG/Bundle 行和 provider 响应不得进入分析 prompt。
2. 所有检索请求先绑定当前 `PlanningContext`，再构造
   `ProjectCognitionSnapshot`；检索请求只携带 snapshot digest 与 scope，不携带
   snapshot 原文。
3. 文本、KG、Bundle 和合规的外部结果都进入已有 `EvidenceBundle` 的
   `EvidenceFact`/`EvidenceSource`；跨来源去重必须保留来源族、权威性、定位、
   快照和 lineage，冲突值不能被静默覆盖。
4. L2 仍然是高度抽象的决策层。L3 所需的细节来自规范化 L1 facts、L2 typed
   decision、直接依赖 artifact 和当前任务的定向证据，不依赖 L2 携带完整细节。
5. 结构化调用只有一个生产入口 `run_structured_output`。严格协议是第一路径；
   对显式允许的阶段，只有在 provider 明确不支持工具/schema 协议时才降级到
   JSON content，并且返回值仍必须经过本地 Pydantic 校验。
6. 报告正文是 display projection，报告摘要是独立的异步 LLM projection。摘要
   使用完整的 typed artifact 与正文源，不使用字符截断；摘要失败不能污染语义
   依赖，也不能阻塞语义 artifact 提交。
7. 不保留旧兼容：不接受旧的字符串 prompt adapter、旧 report-body 依赖、旧
   `GroundedAnchor`/`grounded_anchors` 产物、旧村庄聚类映射作为生产输入，也不
   通过兼容 wrapper 把旧字段伪装成新契约。

## 2. 当前契约边界：只保留必要的对象

### 2.1 证据与检索对象

| 对象 | 所有权 | 用途 | 是否直接给分析 LLM |
| --- | --- | --- | --- |
| `PlanningContext` | workflow/context | 当前 session 的项目数据、KG、Bundle、L1 snapshot 引用 | 否 |
| `ProjectCognitionSnapshot` | retrieval preflight | 项目身份、快照、空间/时间范围、可用数据能力、digest | 否，仅 digest/scope 进入检索请求 |
| `ExplorationRequest` | `evidence_service` | 一次需求/缺口/空间查询的最小请求 | 否 |
| `EvidenceSource` | evidence contracts | 来源类型、引用、权威级别、snapshot | 通过安全 projection 间接进入 |
| `EvidenceFact` | evidence contracts | 一个来源支持的事实及 lineage | 通过安全 projection 进入 |
| `EvidenceBundle` | evidence contracts | 一次检索的 facts、sources、冲突和未解决项 | 不直接传对象，投影后进入 |
| `EvidencePacket` | evidence packet contracts | 候选、空间关系、分页、缺口、查询审计 | 候选/关系投影后进入；trace 不进入 |
| `EvidenceCoverage` | requirement contracts | 每项 requirement 的 supported/ambiguous/unresolved 状态 | coverage/gap 投影后进入 |
| `ExplorationResult` | evidence service | `EvidenceBundle` 与可选 packet/coverage 的真实返回值 | 作为唯一 projection 输入 |

不新增 `EvidencePacket` 的平行版本，也不新增 `EvidenceBundle` 的包装类型。
事实统一存在 `EvidenceBundle.facts`；packet 里的候选和关系只在投影阶段转换为
事实行，不能另建一套公共 `FactProjection` 契约。

### 2.2 语义 artifact 与显示 artifact

| 阶段 | 权威语义 artifact | 显示 projection |
| --- | --- | --- |
| L1 | `L1Snapshot`（`L1Fact`、`L1LocationFact`、evidence gaps） | L1 `report_body` |
| L2 | `L2DecisionSet` | L2 `report_body` |
| L3 | `PlanningClaimSet` / provider claim output | L3 `report_body` |
| GROUND | `GroundingResult` / `GroundedPlanningProblem` | 阶段诊断与候选展示 |
| SELECT | `ScenarioSet` 及 solver certificate | 场景展示与 approval 信息 |

显示正文不能反向成为下游语义输入。下游只能读取 artifact 中声明的 typed
字段和已绑定的来源引用。

## 3. 一次检索的完整数据流

```text
session state
    │
    ▼
PlanningContext（当前 project/session 数据认知）
    │
    ▼
ProjectCognitionSnapshot
  - project_ref / session_id / revision
  - spatial_scope / time_scope
  - bundle、KG、L1 的 snapshot metadata
  - available_data / quality / cognition_digest
    │
    ▼
ExplorationRequest
  - query / stage / dimension_key / purpose
  - entity_scope / requirements / project_scope
  - project_cognition_digest
    │
    ▼
retrieve_evidence()
  ├─ local L1 facts
  ├─ KG canonical facts / relations
  ├─ Bundle feature identity / attributes / geometry refs
  ├─ local text/RAG（只在 request 允许时）
  └─ external（显式开启且本地证据不足时）
    │
    ▼
ExplorationResult
  ├─ EvidenceBundle：facts/sources/conflicts/unresolved
  ├─ EvidencePacket：candidate_refs/relation_evidence/pagination
  └─ EvidenceCoverage：requirement coverage / gaps / stop reason
    │
    ├─ retrieval/audit plane：保留 query_trace、raw rows、完整 locator
    │
    └─ render_analysis_evidence(result)
          ├─ semantic dedup
          ├─ conflict grouping
          ├─ source/lineage preservation
          └─ bounded JSON projection
                │
                ▼
          analysis LLM prompt
```

`render_analysis_evidence` 只接受真实 `ExplorationResult`。它输出固定的五个根
字段：`facts`、`sources`、`conflicts`、`coverage`、`gap`。其中：

- `facts` 是按 subject/predicate/normalized value/scope/valid time/qualifier
  去重后的语义行；同一语义但不同值保留为 conflict variants；
- `sources` 只保留引用和元数据，不序列化完整文档、几何或 provider 返回；
- `facts` 的 `geometry_ref`、`snapshot_refs`、`source_refs`、`evidence_refs`、
  `lineage_refs` 分开保留，不能互相冒充；
- `coverage` 和 `gap` 只说明支持度和缺口，不携带 query plan/query trace；
- 超出 projection budget 时只减少分析投影行数并留下计数/offset，不能回退到
  报告正文截断或全量返回。

## 4. L1/L2/L3 的输入与输出

### 4.1 L1：分段观察，缺口再检索

L1 的输入由四部分构成：

1. `L1SourceIndex` 的当前 source segments。分段是传输和 checkpoint 边界，
   不是把原文截短成一个不完整的事实源；所有 segments 会按 cursor 分页处理。
2. 当前 dimension 的语义契约与闭集 fact types。
3. 一次 `run_rag` 的安全 evidence projection，其中可以包含 KG/Bundle/L1
   facts；投影不含检索 trace。
4. 当前 session 的项目/任务范围，不直接传完整 `PlanningContext`。

L1 observe pass 只输出 typed observations。应用验证 `source_segment_ids` 与
`source_quote` 后再合并去重。若 observation 标记证据不足，应用根据 gap 构造
新的 `ExplorationRequest`，通过同一个 `retrieve_evidence` 检索 KG/Bundle/L1
事实，再把新增的安全 facts 作为下一次有限 pass 的输入。检索结果不通过原始
`query_trace` 回灌。

L1 report pass 只读取通过来源校验的 observations，生成 `report_body`；它不新
增事实。`L1Snapshot` 是 L2/L3/GROUND 的权威输入，L1 正文只用于 display。

### 4.2 L2：高度抽象，事实闭集独立传递

L2 输入按依赖树拆开：

```text
L2-B
  ├─ current L1Snapshot.fact_records（规范化、去重、当前快照）
  ├─ current L1FactCatalog（source_fact_refs 的唯一闭集）
  ├─ direct dependency artifacts
  │    ├─ typed instruction
  │    └─ summary/status metadata
  ├─ run_rag 的 KG/Bundle/Evidence projection
  └─ 本维度的 abstract task/constraints
```

L2 不接收 L1 原始 report body，也不接收同层之外的完整报告。直接依赖由
`DependencyContext` 读取 `ReportStore` 的 `dimension_key/layer/version/report_id/
summary/instruction`，分析 prompt 只渲染这些 metadata 和 typed instruction；
`DimensionReport.content` 永远不被依赖读取器加载。

L2 的结构化输出是 `L2DecisionSet`，只保留目标、指标、策略、优先级、抽象空间
意图、冲突和 evidence gaps。每个引用必须来自本次 `L1FactCatalog`；闭集失败只
允许一次携带 validator feedback 的 reask，失败则阻止正文生成。L2 report pass
只把已校验的 `L2DecisionSet` 转成人读正文。

L2 证据不足时的流程是：

```text
L2 typed decision
    └─ evidence_gaps
        └─ deterministic requirement extraction
            └─ retrieve_evidence(PlanningContext + cognition digest/scope)
                └─ safe facts/coverage projection
                    └─ bounded L2 recompile
```

新增证据只能支持或标记缺口，不能让 L2 生成坐标、BSM、WKT、GeoJSON 或具体
选址。

### 4.3 L3：从事实与抽象决策补足细节

L3 输入不是“L2 携带所有细节”，而是四个互不重复的投影：

- 当前 L1 snapshot 中与本维度及其配置 `layer_depends_on` 相关的 facts；
- L2 直接依赖的 typed `instruction` 与 summary metadata；
- 当前任务的安全 evidence projection；
- 由 relation catalog 和 fact catalog 生成的闭集 options。

L3 provider schema 使用稳定的 `L3ProviderClaimOutput`。运行时的 fact IDs、关系
选项和可用候选不动态展开到 Pydantic JSON Schema，而是在解析后用当前 catalog
做精确闭集校验。这避免每次 catalog 变化都生成一个新 schema，同时仍保证：

- 非空间 claim 的 `source_fact_refs` 只能引用当前 fact catalog；
- 空间 claim 可以不带 source fact，交给 GROUND 通过 EvidenceGraph 解析；
- L3 不写几何、不生成 BSM、不决定最终候选；
- claim 通过校验后才进入独立 L3 report synthesis。

## 5. GROUND 与 SELECT 的调用边界

### 5.1 GROUND

GROUND 接收 `TARGET_PROJECTION` 的 `SpatialReferenceSpec`/`GroundingRequest`，
并在入口重新校验当前 `L1Snapshot` 的 fact references。每个 target 的证据请求
只生成一个或有限分页的 `EvidencePacket`：候选是 `FeatureEvidenceRef`，空间
关系是 `SpatialRelationEvidence`，几何仍只存在 Bundle/KG。

GROUND 的确定性部分负责：

- EvidenceGraph 查询、candidate domain、geometry/BSM authority；
- scope、snapshot、lineage、candidate completeness 校验；
- `GroundingResult` 和 `GroundedPlanningProblem` 持久化。

需要语义判断时，LLM 只看到一个 target 的短描述、候选卡片、候选 ID、来源/置信
度/关系摘要和闭集约束，输出 `CandidateSelectionProposal` 或批量 proposal。
模型不能返回新 ID、坐标、几何或自由 SQL；输出必须通过 `run_structured_output`
与本地闭集验证。无足够证据时输出 unresolved/pending，不能按候选顺序猜测。

旧的 `GroundedAnchor`、`grounded_anchors`、报告正文重解析、
`village_cluster_mapper` 生产映射和 `ResidentialCluster` 静态闭集不属于当前
GROUND 边界。

### 5.2 SELECT

SELECT 的输入是 GROUND 产出的 `GroundedPlanningProblem`、候选 domain、约束
因子、solver readiness 和相关 evidence refs。SELECT 的 LLM 推理（若当前
选择任务需要语义排序/权衡）只接收闭集 candidate cards 和当前目标/约束摘要，
输出只能引用已提供的 candidate IDs、target IDs 和受支持的 rationale code。

确定性 solver 仍负责可行性、硬约束、容量、拓扑和 scenario certificate；LLM
不能直接替代 solver，也不能改变 solver 的几何事实。LLM proposal 经过闭集校验
后才可成为 solver 的排序/偏好输入；拒绝或缺证据时保留 deterministic baseline
并由 SELECT gate 决定继续、人工确认或局部重规划。

本 ADR 不为 SELECT 增加第二套候选/场景公共契约：正式产物仍是现有
`ScenarioSet`、`PlanningScenario` 与 certificate。SELECT 的 LLM 调用必须复用
统一结构化 runner 和同一 provider/stage gate。

## 6. 统一 LLM Manager 与上下文管理

代码中的统一管理边界由以下现有模块组成：

| 能力 | 现有入口 | 责任 |
| --- | --- | --- |
| provider/settings | `app.core.llm_config` | provider、typed mode、stage policy、timeout、token/concurrency |
| connection/cache | `app.infrastructure.llm.instructor_client` / `factory` | provider client、连接复用、semaphore |
| typed call | `app.infrastructure.llm.structured.run_structured_output` | message、协议选择、超时、transport retry、Pydantic 校验、诊断 |
| contract metadata | `app.contracts.registry` | contract key、schema/version、stage 归属 |
| evidence retrieval | `app.evidence.retrieval.evidence_service.retrieve_evidence` | request routing、source plane、packet/coverage |
| analysis projection | `app.infrastructure.context.project_cognition.render_analysis_evidence` | dedup、conflict、safe bounded JSON |
| dependency projection | `app.infrastructure.llm.dependency_context` | DAG direct dependencies 的 metadata-only prompt projection |
| async summary | `ReportStore.schedule_summary` → `dimension_runtime.generate_summary` | complete source artifact、独立 summary call、CAS update |

业务 worker 不应直接调用 provider client，也不应自行实现 JSON repair、字符串
截断、prompt retry 或第二套 semaphore。

### 6.1 输入预算

预算分成三类，不能混用：

1. `source page budget`：L1 source segments 的结构化分页，只改变一次 observe
   call 看到的 segment 数，不删除整个项目的事实；
2. `analysis projection budget`：facts/candidates 的条数或字段范围，只投影
   当前 requirement 所需内容，并返回 over-budget 元数据；
3. `output token budget`：每个 stage 的输出上限和 incomplete-output retry，
   只限制响应，不用来切 prompt。

每次调用日志只记录 safe shape：stage、contract、model、message count、输入
字符/估算 token、输出字符、queue/provider latency、retry/failure code、source
family counts。不得记录完整 prompt、正文、key 或 provider response body。

### 6.2 输出状态机

```text
typed call
  ├─ native tools / native json_schema
  │     └─ local Pydantic validation
  ├─ protocol unsupported and contract opt-in
  │     └─ json content / json mode
  │           └─ decode JSON container
  │                 └─ local Pydantic validation
  └─ any other failure
        └─ typed failure / gate / bounded retry
```

严格协议失败只在明确的协议不支持或 tool/schema 缺失场景触发一次 JSON fallback；
普通 quota、鉴权、语义校验和网络失败不能被伪装成 schema fallback。所有调用都
共享 provider gate 与 stage gate；同一次真实调用不会先尝试字符串 adapter 再
重复调用。

## 7. 报告与摘要的异步生命周期

```text
typed semantic artifact
    │
    ├─ immediate ReportStore save
    │     ├─ content = display report body
    │     ├─ instruction = typed artifact JSON
    │     └─ summary = pending projection metadata
    │
    └─ TaskSupervisor deduplicated summary task
          ├─ read complete content + instruction inside worker
          ├─ one independent `display.summary` typed LLM call
          ├─ no report[:N] and no dependency reuse
          └─ report/version/report_id guarded update
```

summary 的输入允许完整，但它只在独立的 summary task 内读取，不进入其他维度的
依赖上下文。`get_latest_dependency_records` 只查询
`dimension_key/layer/version/report_id/summary/instruction`，因此 L2/L3 不会因为
读取依赖而加载正文。

## 8. 验收指标

必须同时满足以下条件才算完成：

- 任意 L1/L2/L3/GROUND 检索请求都能证明绑定了当前 cognition digest/scope；
- 分析消息中不存在 `query_trace`、`retrieval_plan`、raw rows、完整 report body；
- 同语义事实跨来源去重后只保留一行，冲突值有独立 variant 与 conflict group；
- L2/L3 的 source fact refs 在当前 L1 catalog 闭集内，非法引用不能到达 report；
- 不支持严格 schema 的模型可以走 JSON content，但 JSON 仍必须本地验证；
- typed artifact 保存不等待 summary；summary 使用完整源并能被 stale version guard
  拒绝；
- 生产代码中没有旧的字符串 prompt adapter、旧 report-body dependency loader、
  `GroundedAnchor`/`grounded_anchors` 读写或旧村庄聚类生产路径；
- 通过 focused contract tests、context isolation tests、structured runner tests、
  async summary tests、GROUND/SELECT closed-set tests，以及一次真实 provider smoke
  或重复外部阻塞记录。

