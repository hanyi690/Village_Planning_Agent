# 05 业务阶段迁移验收

> 本文件只记录目标业务阶段到当前代码的迁移状态，不从当前目录反推目标设计。

## 推进顺序

```text
L1 → L2 → L3 → TARGET_PROJECTION → GROUND(planning target grounding)
→ SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER
```

L1 聚合后另行触发 GROUND 的地点定位 sidecar；它服务后续空间上下文，
不改变主业务阶段顺序，也不经过 TARGET_PROJECTION。

后一阶段必须以前一阶段真实产物可生成、可重载、可消费为前提。

## 每阶段状态

```text
CURRENT   边界、产物、适配和运行探针均已完成
PARTIAL   有实现但边界、真实产出或适配不完整
GAP       尚无满足目标的实现
RETIRE    旧路径无调用者，可清理
BLOCKED   有明确外部阻塞并已记录验证限制
```

## 每次迁移记录

```text
目标阶段
目标 facade 和目录
当前代码映射
权威 artifact
真实运行产出
contract、编译、导入和运行探针
下游适配结果
遗留风险
```

## 当前映射

| 目标阶段 | 当前主要实现 | 状态 |
|---|---|---|
| L1 | `modules/l1/`、L1 contracts、`infrastructure/evidence_runtime/`；facade/CAS reload 与 GROUND 地点解析旁路已落位，仍需按当前输入复核 exact/ambiguous/unresolved 分布 | PARTIAL |
| L2 | `modules/l2/`；L1 输入边界、facade、artifact reload 已落位，完整新会话下游消费仍待探针 | PARTIAL |
| L3 | `modules/l3/`、L3 contracts；PlanningProgram facade 已落位，需补完整非空 L3 运行产出 | PARTIAL |
| Evidence | `modules/evidence/` 业务语义 + `infrastructure/evidence_runtime/` 集中执行；L1/GROUND 已走当前输入边界，其他阶段适配仍需收口 | PARTIAL |
| TARGET_PROJECTION | `modules/target_projection/`，生产编排位于 `stage.py`；typed facade 与 CAS reload 已落位 | PARTIAL |
| GROUND | `modules/ground/`、`spatial/grounding/`，包含 L1 location resolution 与 post-L3 target grounding 两个入口；需按真实当前输入分别证明绑定/候选/缺口链 | PARTIAL |
| SELECT | `modules/select/`，生产编排位于 `stage.py`；求解器及审批输入已迁移，需完整新会话 artifact 消费证明 | PARTIAL |
| EXECUTE | `modules/execute/`，生产编排位于 `stage.py`；workers 已集中到 `modules/execute/workers/`，需完整提交/回滚探针 | PARTIAL |
| VALIDATE | `workflow/stages/validate.py`、validation contracts；读取 EXECUTE artifact 并生成 `ValidationReport`/`ValidationCertificate` | PARTIAL |
| RECONCILE | `workflow/stages/reconcile.py`、reconciliation contracts；汇总全链路状态并生成 `FinalManifest` | PARTIAL |
| DELIVER | `workflow/stages/deliver.py`、`workflow/delivery/`、delivery contracts；生成 `DeliverySpatialSnapshot`、`DeliveryManifest` 和 export artifacts | PARTIAL |

### 原 domain 能力的收敛去向

旧的物理目录不再作为运行时包保留，但其中的业务能力已按 owner 拆入下列权威位置；
这张表用于核对“删除目录”与“删除能力”不是一回事：

| 原能力 | 当前权威实现 |
|---|---|
| assessment / L1 facts | `modules/l1/`、`contracts/l1/`、`data/ingestion/compiler/profiles/l1_observation.py` |
| demand / objectives / suitability | `modules/l2/`、`contracts/l2/` |
| program / claims | `modules/l3/`、`contracts/l3/`、`contracts/l3/program.py` |
| target projection | `modules/target_projection/`、`contracts/target_projection/` |
| ground / spatial binding | `modules/ground/`、`spatial/grounding/`、`contracts/ground/` |
| allocation / selection | `modules/select/`、`contracts/select/` |
| materialization / workers | `modules/execute/`、`modules/execute/workers/`、`contracts/execute/` |
| relations / network | `spatial/relations/`、`spatial/network/` |
| validation / reconciliation / delivery | `workflow/validation/`、`workflow/delivery/`、`contracts/validation/`、`contracts/delivery/` |
| shared gate / execution evidence | `core/common/`、`contracts/artifacts/` |

生产代码已完成对这些旧包名的导入清零；后续删除只针对无调用的重复实现，不能以“旧
目录不存在”推断能力缺失。

## 集中 Runtime 边界

| Runtime | 权威位置 | 责任 |
|---|---|---|
| Context Runtime | `backend/app/infrastructure/context_runtime/` | 版本化上下文、projection、表格渲染、预算和当前运行输入裁剪 |
| Evidence Runtime | `backend/app/infrastructure/evidence_runtime/` | query planning、retriever routing、来源 adapter、融合、provenance、coverage、sufficiency、缓存和降级 |
| Structured Runtime | `backend/app/infrastructure/structured_runtime/` | 结构化解析、schema validation、artifact assembly |

`modules/evidence/` 只拥有 EvidenceRequirement、EvidenceGap、EvidencePacket
等业务语义和公开 facade；业务阶段不能直接选择 retriever 或访问 KG/Bundle。

## 迁移前基线（不是当前实现的验收证据）

以下结果来自迁移收口前的会话
`explore_kgenrich_292fb542`。它不是当前实现的验收证据，也不能被恢复逻辑当作当前输入；
这里只保留它用于解释“为何曾经没有最终产出”，没有读取其他历史会话，也没有运行已清理的测试套件：

| 边界 | 结果 |
|---|---|
| L3 → TARGET_PROJECTION | `PlanningProgram` 含 75 条 claims、28 条空间意图；没有复杂 typed parameter block，因此 intervention 数为 0；TARGET 仍产出 28 条 pending grounding specs 和 28 条 pending requests |
| TARGET_PROJECTION → GROUND | TARGET_PROJECTION 只接收 `PlanningProgram` 并登记具体 `GroundingRequest`；L1 地点绑定由前置 GROUND 旁路独立生成，规划目标再由 GROUND 依据当前请求重新检索和校验 |
| GROUND → SELECT | SELECT 没有生成 `ScenarioSet`，gate 为 `not_groundable`；当前代码按 target 生成恢复请求，并回指 `target_projection`、`grounding_result`、`planning_program` 和 `l1_snapshot` |

这组结果说明当前“没有最终产出”的原因是输入闭环未满足，而不是阶段文件夹没有迁移：L3 的粗意图没有权威来源提供的结构化参数、空间身份和候选几何，TARGET/GROUND/SELECT 按契约拒绝继续物化。后续补录必须从恢复请求所指向的具体 claim/target 和源工件输入开始，不能通过修改 L3 prompt 让 LLM 猜出复杂字段。

## 2026-08-28 边界复核与 Exa 方案对齐

本轮复核以本目录的目标设计、`architecture/CURRENT_RUNTIME.md` 的现状证据和
当前工作树为准；`graphify-out/` 的旧图谱包含已删除的测试文件，只作为历史导航，
不作为当前能力证据。Exa 检索得到的共同原则是：业务核心依赖以业务语言表达的
port，Bundle/KG/LLM/检索等技术实现作为外部 adapter；恢复必须回到保存了输入的
同一运行上下文，而不是从历史会话复制结果；产物还必须保留实体、活动、来源和
版本 lineage。这与本项目的 `modules`、集中 runtime、CAS artifact 和
`RecoveryPointer` 划分一致。

### 已经收口的边界

| 边界 | 当前证据 |
|---|---|
| Context Runtime → 阶段投影 | 各阶段只定义字段白名单；预算和表格由 `context_runtime.table_renderer.build_bounded_table()` 统一执行，且已有非测试边界探针实际调用 L3/TARGET/GROUND/SELECT/EXECUTE 投影。 |
| GROUND → Evidence Runtime | GROUND 主候选预取通过 `EvidenceApplication` 声明空间证据需求；candidate 分页和 `spatial_spec` 作为 facade 的受控参数传入，provider 路由仍留在 `infrastructure/evidence_runtime/`。 |
| L3 → TARGET_PROJECTION | L3 继续输出 rough claim；复杂参数、候选、几何和 source binding 不进入 LLM wire contract。rough provider schema 现在 `extra="forbid"`，证据引用只接受当前 Evidence Runtime 闭集；无真实 lineage 的 claim 被 quarantine 并回到 L3，而不是进入 TARGET。 |
| TARGET_PROJECTION → GROUND → SELECT | 每个未接地事项有独立的 target/claim recovery pointer；没有候选时保留 unresolved，而不是产生空的成功方案。 |

### 仍为 PARTIAL 的边界

### 2026-08-28 GROUND 双入口收口

此前 L1 聚合只写入了一个可选的 `l1_bindings` 旁路，完整的
`SpatialResolver` 迭代/闭集判别没有作为 GROUND 能力执行；因此不能把
“L1 已完成”描述成“地点已经完成空间定位”。当前收口为：

1. L1 只通过结构化 `spatial_mentions` 输出地点工作项。它们不含权威 ID、
   坐标、几何或 BSM；编译器生成 mention 记录，删除了从任意描述单元格切词
   的正则地点兜底。
2. L1 聚合完成后直接调用 `GroundApplication.materialize_l1_locations()`。
   GROUND 从当前输入构建 `l1_observations` 和 `l1_bindings`，执行候选召回、
   scope/关系辅助、有限轮次迭代和闭集 LLM 选择；LLM 只能复制 runtime 已给
   出的候选引用，不能生成 canonical ID 或 geometry。
3. L3 仍只负责规划语义。`TARGET_PROJECTION` 只编译 `PlanningProgram` 的
   目标和待定位请求；后续 GROUND 复用 L1 绑定完成规划目标接地。两条入口
   都允许部分 unresolved，并将缺口挂回具体 mention/target 与当前源输入，
   不因单个 gap 停止 L2/L3。

因此当前验收要分别报告：`L1 location resolution` 的 exact/feature-set/
inferred-scope/ambiguous/unresolved 数量，以及 post-L3 `GroundedPlanningProblem`
的候选和缺口数量；不能用 TARGET_PROJECTION 的 pending spec 数量冒充 L1
地点已经定位。

以下不是目录迁移问题，而是阶段编排仍直接依赖部分 runtime 辅助能力，必须作为
后续收口工作处理：

1. L1/L2/L3 的 dimension orchestration 仍复用
   `infrastructure.evidence_runtime.dimension_runtime` 的 provider/SSE/report 辅助函数和
   dependency-context 适配器；检索本身已经通过
   `modules.evidence.application.EvidenceFacade.retrieve_dimension_context()` 收口，
   LLM structured call 也已经通过 Structured Runtime。剩余工作是把非检索的
   维度编排辅助能力改成显式 typed port，不改变各阶段的业务 contract；旧的
   LLM 适配层维度 runtime 位置已删除，避免 LLM 适配层继续拥有证据编排。
2. EXECUTE 的部分词汇提取和旧 worker 仍需要继续审计其 runtime 依赖；它们不能把
   provider 返回值直接升级为执行字段，必须继续经过结构化 contract 和确定性校验。

因此当前集中 runtime 的结论应写成：`Evidence` 的检索执行已集中且阶段检索入口
已通过唯一业务 facade，`Context` 的预算/渲染已集中，`Structured` 的解析和
L3/阶段结构化调用入口已集中；仍有 provider/SSE/report/dependency 编排辅助调用
未完全通过 typed port，整体状态保持 `PARTIAL`，不能提前标成 `CURRENT`。

本轮对照的外部方案只用于校验架构原则，不作为本项目业务输入：闭世界字段目录和
schema-conditioned routing 可参考
[Executable Schema Contracts](https://arxiv.org/html/2606.05415v1)，claim-level
provenance、支持/矛盾/缺失关系和按步骤恢复可参考
[Evidence Tracing and Execution Provenance in LLM Agents](https://arxiv.org/html/2606.04990v1)。
本项目仍以本地 design contracts、当前 SessionDataSnapshot 和可重载 artifact 为
唯一事实来源。

### 2026-08-28 L3 输出边界复核

先前 `explore_kgenrich_292fb542` 的 PlanningProgram 曾统计出 75 条 claims，
其中一部分 `evidence_refs` 是自然语言片段。该产物只能说明旧链路确实生成过
PlanningProgram，不能把“非空字符串”当作有效 lineage。当前代码已经将
`fact_id/source_refs/evidence_refs` 从本次 Evidence Runtime projection 形成闭集；
旧产物不会被回写或冒充新验证结果。下一次新的当前会话运行后，只有闭集命中的
引用才能保留，完全没有真实 fact/evidence locator 的 claim 会被明确诊断并阻断
进入后续阶段。

### 2026-08-28 新会话 L1 真实验收结果

新建当前会话 `convergence_current_20260828_0423` 完成了 12 个 L1 维度的
observe/report 调用，但没有生成 `L1Snapshot`。质量门记录了每个维度的实际
结构/来源隔离数量，最高缺陷比例为 100%；因此 `PlanningProgram` 为零是下游
没有收到 L1 权威输入的结果，不是一个可以用历史会话或旧报告补齐的缺口。

其中 `location` 的定向恢复只重新派发了该维度，使用同一份
`L1SourceIndex` 和质量反馈；恢复后有 40 条 typed observation 被保留，88 条
因 `spatial_entity.entity_type` 等必需字段缺失而隔离，仍未达到质量门。这证明
恢复断点已经回到具体维度和原始 source input；在供应商真正补齐字段前，系统
不会伪造事实、坐标、候选或 L1Snapshot。后续验收必须从该质量断点继续，而不
得把任意旧会话当作当前输入。

### 2026-08-28 新会话 `explore_kgenrich_07102901` 复核结果

随后又创建了完全独立的当前输入会话 `explore_kgenrich_07102901`，没有读取或
复用任何历史会话结果。KG 预构建得到 35,511 triples；Context Runtime 生成了
当前快照和 source digest；12 个 L1 维度都完成了真实的 `l1.observe` 与
`l1.report` 调用。各维度最终保留的 typed observation 数如下：

| 维度 | 保留 observations | 隔离/拒绝 | 结果 |
|---|---:|---:|---|
| location | 48 | 50 | quality gate blocked |
| socio_economic | 6 | 28 | quality gate blocked |
| villager_wishes | 13 | 42 | quality gate blocked |
| superior_planning | 29 | 41 | quality gate blocked |
| natural_environment | 13 | 13 | quality gate blocked（比例达到 50%） |
| land_use | 19 | 31 | quality gate blocked |
| traffic | 8 | 24 | quality gate blocked |
| infrastructure | 24 | 37 | quality gate blocked |
| ecological_green | 14 | 9 | dimension pass |
| architecture | 27 | 24 | dimension pass |
| historical_culture | 13 | 12 | dimension pass |
| public_services | 45 | 37 | dimension pass |

因此运行结果是 `paused at layer1`、`planning_status=no_planning_output`、
`first_zero_stage=PlanningProgram`、`artifact_files=0`。这不是“没有调用”或
“文件没有迁移”：observe/report 已经执行并写入当前会话的步骤审计，但 L1 聚合
没有收到全部质量通过的维度，所以没有提交 `L1Snapshot`，下游没有被虚构启动。

本次结果还确认了两个修复效果和两个剩余真实缺口：

1. `entity_type` 等分支字段现在能按 provider schema 和本地 typed admission
   正常闭合，location、public_services 等维度已经产生大量真实观察；没有添加
   从名称猜类型的 fallback。
2. `mandatory_constraint/advisory/未说明` 等供应商枚举只通过确定性 alias 进入
   `hard/soft/unknown`，`location/demand_point/无空间要求` 只进入
   `place_binding/demand_points/none`；未知枚举仍隔离。
3. 来源 quote 只允许当前 source page 的 `source_segment_id`，新增的规范化仅去除
   HTML 表格标签、Unicode/空白差异和标点表现差异，仍要求规范化后的引文是来源片段
   的逐字子串，不接受语义相似或改写。
4. 剩余阻塞主要是供应商仍返回无法确定归一化的值、指标/约束分支缺失必要字段，
   以及部分 quote 不是当前片段中的逐字证据。当前 HUMAN 断点现已携带
   `dimension_key`、`source_digest`、`source_index_ref`、`input_digest` 和隔离字段；
   retry 只重派该维度并复用同一当前 source input，不会重放全层或读取历史会话。

结论保持 `PARTIAL/BLOCKED`，不能把四个通过维度拼成一个假的完整 `L1Snapshot`，
也不能因为已有 typed observations 就贸然进入 L2/L3。必须先从 HUMAN 断点列出的
具体维度和来源片段修复输入/产出闭合，再重新通过 L1 聚合门。

### 2026-08-28 新会话 `explore_kgenrich_fa451bd8` 恢复控制复核

又一次独立启动当前输入会话后，首轮仍因 6 个维度的提供方/结构化输出失败而
进入 L1 HUMAN，`L1Snapshot`、`PlanningProgram` 和交付文件均为零。审计日志确认
这里不是“没有调用”：真实 KG 为 35,511 triples，12 个 L1 worker 均被派发，已完成
维度仍写入了当前会话的 `l1.observe/l1.report` 步骤记录。

该运行暴露了恢复控制面的两个问题，已经在当前代码修正：

1. `provider_failures` 与可重试的 `provider_resume_dimensions` 同时存在时，旧路由
   先把提供方失败当作终态，导致本应回到同一维度的重试直接丢失；现在只要没有
   `fatal_error`，按维度的恢复信号优先进入 `provider_resume_dispatch`。
2. 恢复列表被完整复制进每个 `Send` payload，重试 worker 又把已消费列表写回父图，
   造成同一批维度重复派发；现在父图保留聚合列表，worker 只接收标量
   `provider_resume_dimension`，并按 `dimension_retry_limit` 限制一次自动重试。

这次会话在修复前已经停止，未把其不完整状态当作后续输入。修复后的验证顺序是：
先用静态路由/预算探针确认恢复列表只消费一次，再用全新会话确认失败维度能够回到
 同一 `source_digest/source_index_ref/input_digest`，成功后列表清空；质量门仍然拒绝
 没有逐字来源、分支必需字段缺失或提供方虚构的观察，不通过时继续保留 HUMAN 断点。

### 2026-08-28 新会话 `explore_kgenrich_4a379c93` 真实运行复核

在上述恢复控制修复后再次启动完全独立的新会话，预构建 KG 得到 35,511 triples，
12 个 L1 维度均实际执行了 typed `l1.observe` 与 `l1.report`。其中 3 个维度首轮
通过，其余 9 个维度按同一 source index/input digest 重试一次；重试没有产生同一批
维度的无限重派。最终 12 个维度都有步骤审计记录，但 9 个维度仍因当前 source page
逐字证据隔离和 provider 分支字段缺失超过质量门，运行在 L1 HUMAN 停止：

```text
execution_status=paused
paused_stage=layer1
human_review_items=9
planning_status=no_planning_output
first_zero_stage=PlanningProgram
artifact_files=0
```

本次结果的含义是：LLM、Source Index、结构化运行时和 L1 worker 都已工作；没有
通过质量门的观察没有进入 `L1Snapshot`，所以没有错误地启动 L2/L3。该会话也没有
作为任何后续业务输入。当前剩余工作应从 HUMAN 记录中的具体 `dimension_key`、
`source_digest`、`source_index_ref`、`input_digest` 和隔离路径修复 provider 产出，
而不是调整阈值、拼接历史会话或用旧报告补齐。

为避免恢复能力只在 L1 存在，当前实现新增集中式
`backend/app/workflow/recovery/`：L1/L2/L3 的提供方失败都使用同一个有限重试决策，
并沿用当前 producer 的输入摘要；重试信号仍由 workflow 消费，业务模块不选择其他
维度、不改写上游 artifact。

### 2026-08-28 当前 session `explore_kgenrich_28748410` 运行与探索接线复核

在清理旧测试和旧生成目录后，又启动了完全独立的当前输入 session
`explore_kgenrich_28748410`。它从金田村当前输入重新创建 session、重新构建
35,511 triples 的 Session KG，并完成了真实的 L1/L2 调用：

```text
L1: 12/12 dimensions complete
L1Snapshot: stored and passed fact/source provenance validation
L2: 4/4 dimensions complete
L2Strategy: stored, schema=L2Strategy v3
L2 Gate (historical run): EXPLORE (5 actionable requests; each has a RecoveryPointer)
```

这次运行随后暴露出 workflow 与 Evidence facade 的真实接线错误：workflow 从
`modules/evidence/application.py` 导入了未公开的私有 digest 名称，导致 EXPLORE
没有调用 Evidence Runtime，而是直接进入了有限重派发。该运行在继续消耗重复的
L2 provider 调用前被停止；它的中断状态没有作为下一次业务输入。当前已将 digest
提升为 Evidence Runtime 的正式公开接口，并保留单一入口：

```text
workflow -> modules.evidence.application -> infrastructure.evidence_runtime.facade
```

随后使用该 session 已落库的当前 `L1Snapshot/L2Strategy` 做了一次受限生产运行时
调用，验证 `retrieve_evidence_for_gate_sync` 能真实返回 2 个结果，并查询
`local_text/report/kg/bundle/artifact` 五类来源。覆盖结论为 `source_exhausted`，
未解决项和 `evidence_gap_loop` 的 bounded query trace 均被保留；没有把缺口转换成
事实、候选、几何或策略字段。该调用只验证当前 session 的运行时接线，不把旧会话
或历史结果作为业务输入。

因此当前可确认的是：L1Snapshot 与 L2Strategy 已经能够真实产出并持久化；L2
EXPLORE 已经具备按 `producer_dimension`、`source_input_refs`、`required_fact`
回到具体输入的路径；但该 session 在接线修复前没有继续进入 L3，不能宣称完整链路
已经完成。下一次全链路验收必须确认 Evidence Runtime 返回的证据被目标 producer
消费后，L2 gate 是否收敛或继续生成同一具体事项的 HUMAN recovery pointer。

### 2026-08-28 L2 EXPLORE 无闭合证据时的路由修正

对当前 `explore_kgenrich_28748410` 的 5 个 pending request 逐项检查了
`L1Snapshot.fact_records`。当前快照有 87 条 typed fact，但没有“第三产业市场
潜力/投资回报”“分年龄段常住人口”“人口发展预测”“林地土壤坡度海拔适宜性”或
“农用地分等定级”的可验证记录。因此这些缺口不能通过改写 prompt、沿用历史会话
或让 LLM 补值来消除。

原路由只比较 Evidence cache digest；只要检索产生了任何新 cache，就可能再次派发
producer，即使每个检索结果仍为 `source_exhausted`。现在
`workflow/conversation/edges.py::_route_explore()` 还要求至少一个返回结果的
`coverage.sufficient` 为真；若没有任何缺口被闭合，则直接进入 `human_review`，
保留原 gate、具体 `RecoveryPointer` 和待补输入，不重复消耗 L2 provider。当前
生产路由探针已进入：

```text
EXPLORE evidence did not close any request for L2 -> HUMAN
```

这不是把失败改成成功，而是把“当前资料不足”准确地固定为可恢复的人审状态。

### 2026-08-28 L3 聚合出口收敛

复核发现 L3 聚合在 claims-only 归一化之后仍自动调用语义修复、分类决定和
单位修复路径，其中语义修复/分类决定可能再次修改已经组装的 `PlanningProgram`。
这不符合 `03_PLANNING_INTENT.md` 对 L3 的边界：LLM 只能输出小批量 rough claim，
复杂参数、项目包、候选、source binding 和 geometry 不能从 LLM 结果直接进入权威
程序。

当前 `l3_aggregate()` 已收敛为：读取当前维度的 `PlanningClaimSet` → 对持久化输入
重复执行复杂字段隔离 → 确定性 claim normalization → 确定性 program assembly →
CAS 写入并 reload → L3 gate。自动 `classification_generator`、`semantic_repair`
和 `flash_unit_repair` 已从主链移除并删除其孤立注册/配置；`classification.py`
仍保留为 workflow 的显式 HUMAN 决策入口。因而 polygon/parcel 分类或复杂结构化
参数未就绪时会进入 pending/HUMAN，而不会被模型二次改写成看似完整的产物。

生产验证结果：`python -B -m compileall -q backend/app scripts/acceptance`、
`git diff --check` 和业务边界探针通过；当前 session 的 `L1Snapshot`（87 条
`fact_records`）与 `L2Strategy` 均按同一 run/branch 成功 reload，L2 source fact
闭集校验通过（24 个引用、无 dangling ref）。L3 尚未因资料缺口伪造非空
`PlanningProgram`，整体状态继续保持 `PARTIAL`。

### 2026-08-28 L1 KG provenance 别名收敛

当前真实会话曾在 L1 聚合出口停止，错误为：

```text
L1 fact provenance is not represented by sources: refs=['kg:cognition']
```

根因不是领域能力缺失，而是 KG 查询层把 `kg:cognition` 作为内部标签返回，
而 L1 的 source catalog 使用当前会话的 `session_kg:<session_id>#cognition`。
两者都指向同一个当前会话 KG，但在 Evidence Runtime 出口没有完成绑定，导致
L1 的 provenance gate 正确地拒绝提交整个 `L1Snapshot`。

现在绑定逻辑集中在
`infrastructure/evidence_runtime/provenance.py::canonicalize_fact_provenance()`：

- 只有结果同时包含当前会话的 KG source，才允许把 `kg:*` 别名绑定到该 source；
- 没有对应 KG source 时不补 source、不降级成成功，仍交给 L1 provenance gate 拒绝；
- 绑定发生在统一 Evidence Runtime 出口，L1 不再识别 retriever 内部别名；
- 绑定后的 fact 仍保留 KG 的 `inferred` 语义，不会变成 observed，也不会产生新的
  数值、空间对象或规划字段。

该修复解决的是“真实 KG 事实已经返回但 L1 因 source catalog 不一致而无法提交”
的产物级故障；它不会替当前会话缺失的市场潜力、年龄结构、人口预测、林地适宜性
或农用地等级数据，因此这些 L2 缺口仍必须按具体 `RecoveryPointer` 进入补充资料或
HUMAN 审核。

### 2026-08-28 活动子图 artifact 投影修复

当前会话的 root checkpoint 在 `cognitive` 子图运行期间仍可能保留旧的
`artifact_refs`，而活动子图已经提交了本次 run/branch 的 `l1_snapshot`、
`l2_strategy` 和对应 gates。API 若只读取 root snapshot，就会把“活动子图已有
产物”显示为“没有产出”。

`PlanningRuntimeService.aget_state_values()` 现在只读遍历当前 checkpoint 的
活动子图任务，并将其中通过 `ArtifactRef` 校验的 refs 合并到控制投影。该逻辑：

- 不调用历史 checkpoint，不从旧会话补业务输入；
- 不改写 root checkpoint，也不改变 workflow 路由；
- 只合并当前活动子图可验证的 immutable artifact refs；
- 保持 `phase/status` 等 workflow 游标由 root checkpoint 决定，避免把子图投影
  误当成阶段推进；
- 让 artifact/status/review API 在聚合提交后立即能看到真实产物。

当前会话实测的 live projection 已返回：

```text
l1_source_index, l1_snapshot, l1_gate, l2_strategy, l2_gate
```

这修复了“产物已写入当前活动分支但 API 显示为空”的运行时可用性问题。旧的
持久化 gate 仍记录当时的 EXPLORE 结果；按当前 gate 语义对同一当前 session
重新加载的 `L2Strategy` 做只读重评估，结果为 `passed=true`、reason
`passed_with_unresolved_evidence`，15 个真实 gap 仍全部保留，不能被当作已满足。

### 2026-08-28 业务契约目录收敛

复核发现 `contracts/artifacts/` 同时承载 artifact identity 和
VALIDATE/RECONCILE/DELIVER 的业务 payload，导致契约 owner 与目标文件树不一致。
现已完成生产路径迁移：

- `ExecutionStaging` 归入 `contracts/execute/`；
- `ValidationReport`、`ValidationCertificate` 归入 `contracts/validation/`；
- `DeferralLedger`、`DeliveryManifest`、`FinalManifest`、空间交付引用归入
  `contracts/delivery/`；
- `contracts/artifacts/` 仅保留 `ArtifactRef`、通用元数据、provenance 和共享
  artifact 辅助契约。

所有生产导入、contract registry model path、最终链导入探针和
`business_stage_boundary_probe.py` 均已按新 owner 验证；旧契约 import 路径没有
兼容转发，避免继续保留第二套目录语义。

### 2026-08-28 证据维度 runtime 归属收敛

维度证据查询和追查辅助已从 LLM 适配目录移入
`infrastructure/evidence_runtime/dimension_runtime.py`，`infrastructure/llm/`
不再拥有维度检索入口。L1/L2/L3 仍通过 `modules/evidence` 声明和消费证据投影；
该 runtime 只处理 provider 适配、证据查询、bounded projection、SSE/报告审计交接，
不会把 provider 文本直接升级为业务事实。旧路径已删除并完成全仓生产引用扫描。

### 2026-08-28 L3 claims provider 边界调用修复

复核 L3 真实调用链时发现，`modules/l3/reasoning.py` 会把当前 Evidence
Runtime 的 `allowed_evidence_refs` 传给集中式 `PlanningClaimGenerator`，但该
provider adapter 的公开方法签名遗漏了这个边界参数，导致请求在 LLM 调用前以
`TypeError` 终止，表现为 L3 没有产出。

现在 `PlanningClaimGenerator.generate_claims()` 接收该参数，并保持其职责为
provider wire-shape 适配；Evidence 引用仍由 L3 业务层根据本次 Evidence Runtime
目录做闭集校验，参数不会被展开成动态 schema，也不会放宽对 source fact、候选、
复杂参数或 geometry 的限制。L3 provider 的实际字段仍只有有限的 rough claims、
引用和 grounding requirement；复杂字段继续由确定性业务编译和后续 GROUND 负责。

### 2026-08-28 Evidence Runtime 当前输入检索执行修复

复核发现 Evidence Runtime 的 `local_text_retriever` 只读取进程内
`PlanningContext` 缓存。冷启动、恢复运行或跨进程调用时缓存为空，检索器会把
“缓存为空”错误地当成“当前输入没有原文”，导致 Evidence 查询有执行轨迹但没有
原文产出。

现已修复为：

- 缓存为空时通过 `context_hydration.prepare_evidence_context()` 装载当前 session
  的 canonical `PlanningContext`；只读取当前 session 的 Bundle 输入文档，不读取
  历史会话；
- 原文按有界、带重叠窗口的片段检索，避免长段落和表格内容只保留开头；每条证据
  保留 source key、content digest、原文 span、locator，并标记为 `needs_review`；
- `dimension_key` 只表示业务请求 owner，不再作为当前原文的硬分区。所有维度都可
  通过 local-text 访问当前输入；`gap_resolution`、project-wide 请求还会选择匹配的
  跨维度 L1 typed fact；
- 词法匹配只负责 grep 式候选召回，不使用正则抽取数值，不把不同表达强行改写成
  业务字段，也不制造缺失值。需要填充结构化字段时，仍由业务模块发起受限 LLM
  抽取，并用返回的 evidence provenance 做 item-level 校验。

使用当前 session `explore_kgenrich_28748410` 做生产探针验证：从冷缓存执行
`public_service` 维度的“人口发展趋势预测”查询，实际返回 12 条当前输入原文，
其中包含“户籍人口 1403 人、常住人口约 500 人”的 source span；没有调用测试框架，
也没有生成虚拟结构化事实。

同时修正了 Evidence requirement 的语义边界：`entity_scope` 不再单独把 claim
编成 `spatial`，因此“常住人口”“年龄结构”等缺口不会因为调用方带有
`facilities` scope 而错误要求 geometry。当前探针的 route 为
`local_text → report → artifact`，状态为 `partial`，未满足的“年龄结构”仍保持
unresolved；空间查询仍保留 `local_text → report → kg → bundle → artifact` 路由。

### 2026-08-28 L2 EXPLORE 部分证据恢复路径修复

L2 gate 的 Evidence 探针确认，当前资料能够返回人口、产业、土壤和土地面积等
部分原文，但不能凭这些片段直接宣称“年龄结构”“市场回报”“坡度海拔”或“农用地
分等定级”已满足。原有 `_route_explore` 只有在某个结果 `coverage.sufficient` 时
才会重新派发维度，因此 partial 但有真实 source span 的结果会直接落到 HUMAN，
不能交给 producer 的受限 LLM 做二次分类。

现在路由规则为：

- 没有任何 `EvidenceFact` 的检索结果，进入 HUMAN；
- 有真实 `EvidenceFact` 但 coverage 为 partial，按 gate 的目标层重新派发 producer，
  让该层 LLM 仅基于当前 EvidencePacket 判断可确认项和仍需保留的 gap；
- worker 由 `layer_num` 明确选择（L2→`l2_worker`、L3→`l3_worker`），不再使用可能
  过期的 root `state.phase`；
- 重试次数仍受原有 gate budget 限制，无法由当前资料确认的缺口不会被清除或填造。

### 2026-08-28 Evidence gap 不再阻断后续阶段

此前 L1/L2/L3 gate 将所有 `warning/error` evidence gap 统一路由为
`EXPLORE`，导致当前资料无法解决的缺口反复重派 producer，并阻止后续阶段
消费已经可用的部分 artifact。现已收敛为：

- 可用的部分 snapshot、decision 或 program 继续生成并持久化；
- `evidence_gaps`、`evidence_requests`、`pending_requests` 和
  `RecoveryPointer` 原样保留，明确说明具体事项、缺失要求和源输入；
- 普通证据缺口使用 `passed_with_unresolved_evidence` 作为 gate reason，允许
  下一阶段继续消费；
- 空产出、事实/策略矛盾、非法 lineage、分类决策缺失以及空间结构不变量仍然
  阻断，因为这些不是普通资料缺口，而是无法安全生成权威 artifact 的结构性问题。

L3 的 claims-only 结果同样按此规则处理：没有 typed intervention 不再被误判为
失败。只要 claims 本身有合法 lineage，就以 `passed_with_pending_claims` 进入
TARGET_PROJECTION，由后者生成不可执行的 pending grounding item；复杂参数和
geometry 仍不会由 LLM 补写。

TARGET_PROJECTION 对这类结果也不再把“没有 executable typed intent”误判为
空成功或 HUMAN 阻断：存在具体 `pending_grounding_specs` 或
`pending_grounding_requests` 时，Gate 使用 `passed_with_pending_grounding`
交给 GROUND；真正没有任何 intent/pending work 的空投影仍然失败。

GROUND 对 unresolved/pending grounding 采用相同的可推进语义：保留每个 target
的未解析原因和当前输入引用，以 `passed_with_unresolved_grounding` 交给 SELECT。
这只表示 typed `GroundedPlanningProblem` 已形成，不表示 target、candidate 或
geometry 可执行；SELECT 仍必须生成无方案诊断、目标级 deferred 或人工审批请求。

SELECT 对“没有可解 GroundedPlanningProblem”的结果新增明确终点：保留 target
级恢复/延期信息并进入 `diagnostic_only`，不等待不存在的 ScenarioSet，也不绕过
审批进入 EXECUTE；只有存在可执行方案时，缺少审批才进入 HUMAN。

这样“无法解决”会成为可追踪的 partial/pending/deferred 结果，而不是伪造
满足或让 workflow 无期限停留在原维度。

### 2026-08-28 KG/GIS 异构属性与 GROUND 上下文收敛

当前金田村复核发现，`roads_current` 的 131 条线有真实 BSM/几何但没有道路名称，
`water_bodies` 的 44 条有效水体候选主要带有分类属性而没有“金田河/石窟河”命名几何。
如果只按 canonical name 查询，L1 的道路/水体地点会错误地得到零候选，GROUND 无法进行
后续推理。当前修复为：

1. `infrastructure/evidence_runtime/source_semantic_runtime.py` 从 GIS
   `properties`、`_raw`、模型字段和 KG RDF literal predicate/value 统一投影业务属性；
   只排除 geometry、坐标、BSM、source identity、layer/CRS 等元数据，不维护村庄专属
   实体字段白名单。新实体类型可进入当前快照闭集，已知类型只增加可选 layer/geometry
   约束。
2. 源语义分类、GROUND 候选选择、L1→GROUND 批量选择、GROUND 目标优先级和 L1 observe
   页均通过 `Context Runtime.build_bounded_table()` 生成有界结构化表格；JSON 只用于
   digest/持久化，不作为业务上下文直接传给 LLM。没有名称且只有来源元数据/纯数值的
   道路行仍写入 unresolved，但不消耗 provider 调用。
3. `EvidenceGraph` 在名称缺失时按显式 `road`/`water` 角色召回当前源候选；对 L1
   提供的“东西向”等线走向语义，runtime 从真实线几何做 15 度容差的方向过滤。过滤后
   仍是 candidate set，不会选择首条、最长条或任意水面；候选身份、几何和 provenance
   仍由 Bundle/KG 提供，闭集 LLM 只能选择或 abstain。

当前金田村非测试探针结果：道路角色域 131 条，东西向几何候选 26 条；水体角色域 44
条。两者均保持 `ambiguous`，说明上下文已经进入 GROUND，但当前源仍不足以证明唯一的
`122乡道`、`金田河`或`石窟河`。下一步必须消费候选分页、加入 KG/水系关系约束并记录每轮
“新证据使哪些候选可解析”，不能把该域误标为 exact。

同时，生产阶段不再从 `get_session_step_reports()` 回读旧步骤来构造 LLM 输入、恢复
L1 语义输出或补写 L1Snapshot。gazetteer 也不再自动读取 `data/gazetteer/*.json`
和 `kg_memory/*_round_*.json`。新的调用只能消费当前冻结上下文、当前状态中的
artifact/CAS checkpoint 和本轮 Evidence Runtime projection；step report/history 仅
作为审计、展示和运行观测面。
这样重新执行同一事项时不会把历史会话的旧结论混入当前 source digest，也不会因为历史
报告存在而跳过当前输入的 L1 observe。

所有直接交给模型的业务数据入口现在统一使用 `Context Runtime.build_bounded_table()`：
L1 source page、L2/L3 依赖投影、Evidence/EXPLORE facts、source semantic rows、GROUND
候选/目标表和 SELECT 场景表均由同一运行时执行行数与字符预算。表格单元格可以承载经过
白名单投影的列表或映射，但不再把 Python `dict` 通过 `str()` 拼成无结构提示文本；JSON
只保留在 digest、artifact、checkpoint 和审计持久化平面。
