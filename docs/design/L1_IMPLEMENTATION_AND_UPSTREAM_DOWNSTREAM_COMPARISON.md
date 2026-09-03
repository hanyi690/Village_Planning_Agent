# L1 实现、上下游边界与设计差距分析

> 状态：CURRENT implementation audit（实现审计，不替代 canonical contract）
> 日期：2026-09-03
> 适用范围：`backend/app/modules/l1`、L1 workflow 编排、L1-GROUND 接口，以及 L2/L3 的真实消费边界。
> 设计依据：`01_CONTRACTS_AND_INVARIANTS.md`、`L1_GROUND_EXECUTABLE_DESIGN.md`、`05_MIGRATION.md`、`architecture/CURRENT_RUNTIME.md`。

这份文档回答四个问题：

1. 当前 L1 到底做了什么，哪些是权威产物，哪些只是展示投影；
2. L1 的上游输入如何进入，哪些 gate、context 和证据约束生效；
3. L1 的下游如何消费，L1-GROUND、L2、L3 分别拥有怎样的边界；
4. 当前代码与设计目标之间，哪些已经闭环，哪些仍是 `PARTIAL`，下一步应该怎样收敛。

## 一、结论先行

当前 L1 已经不是“生成一段现状分析报告”的单一 LLM 调用，而是一条有类型、有来源校验、有检查点、有 CAS artifact 和 gate 的现状观察流水线：

```text
DATA / KG / Evidence
        │  frozen context + upstream gates
        ▼
12 个 L1 维度并行观察
        │  paged structured observation
        ▼
typed observations → source-span validation → quarantine / checkpoint
        │
        ▼
L1 aggregate → merge / contradiction detection / evidence retrieval
        │
        ├── l1_snapshot + l1_gate + review package
        │
        └── independent L1-GROUND
              ├── l1_observations
              ├── l1_bindings
              └── World Model identity projection
```

核心判断如下：

| 结论 | 判断 |
| --- | --- |
| L1 的主职责 | 已基本落实：生产“当前状态事实、地点工作项、关系、缺口和来源链”，不生产规划目标或可执行空间方案。 |
| L1 的事实可靠性 | 已有 typed fact、来源段引用、原文/规范化 quote 校验、冲突检查和不合格行隔离；但独立 source-span validation report 仍未形成最终产品。 |
| L1 的空间边界 | 已明确区分“地点名称工作项”和“已接地实体”；L1 本身不生成 geometry、candidate 或 BSM。 |
| L1-GROUND | 真实调用链已存在，能生成 observation/binding sidecar，并调用 Cognition/World Model identity commit；统一终态 taxonomy、proposal ownership、commit 后 revalidation 仍是目标项。 |
| L2 消费边界 | 代码层面已经要求重载 `l1_snapshot`，并要求 L1 World projection ready；但设计目标要求统一的 `L1FinalProduct / L1ProductManifest + L1BindingSnapshot + WM ref`，当前仍是多引用过渡态。 |
| L3 消费边界 | 已要求 `l1_snapshot`、`l2_strategy` 及 L1/L2 PASS gate，并阻止 geometry、candidate、scenario、approval 等字段；目标仍是由稳定 final view 驱动规划意图。 |
| 总体成熟度 | 与 `05_MIGRATION.md` 一致：L1、L1-GROUND、L2、L3 当前均应标为 `PARTIAL`，不能写成已完成的完整认知闭环。 |

## 二、范围与术语

### 2.1 三个容易混淆的 L1 层次

当前代码中“L1”实际上包含三个不同层次，分析时必须分开：

| 层次 | 主要入口 | 产物 | 是否属于 L1 观察本身 |
| --- | --- | --- | --- |
| 维度观察 | `analyze_dimension()` / `run_l1_dimension_loop()` | 一个维度的 `L1DimensionOutput`、semantic output、display projection、checkpoint | 是 |
| L1 聚合 | `L1Application.run()` / `l1_aggregate()` | `L1Snapshot`、`l1_gate`、review package | 是 |
| L1 地点接地 | `GroundApplication.materialize_l1_locations()` | `l1_observations`、`l1_bindings`、World Model current snapshot/projection | 是 L1 的前置 GROUND，但不是 L1 观察器，也不是规划用途 GROUND |

第三层很关键：地点名称可以在规划意图产生以前先作为空间工作项被接地；这不等于 L1 取得了规划目标的 geometry，也不等于 L1 可以替 L2/L3 生成方案。

### 2.2 “观察”“展示”“接地”三种数据不可互换

```text
Observation                 Display projection                 Ground binding
事实行 / typed value         面向审阅的 report_body             mention → entity/scope/relation
source refs / quote          可读表格或章节                         candidate closed set / status
uncertainty / derivation     仅用于显示和 review                     identity / World Model receipt
```

其中 `report_body` 是确定性展示投影，不应被当作新的事实来源。当前 `compile_l1_observation()` 仍会读取结构化报告内容形成 display facts/constraints，因此后续维护必须继续把 `fact_records` 和 `location_mentions` 视为权威入口，避免把展示文本重新当作事实真相。

## 三、L1 上游：输入、冻结和准入

### 3.1 上游依赖顺序

L1 应在同一 `context_version` 下读取：

| 上游 | L1 使用内容 | 当前实现的强制方式 |
| --- | --- | --- |
| DATA | 数据快照、source index、catalog、上传文档和可追溯 source segments | `require_upstream_gates(..., ("data", "kg", "evidence"))`；L1 retrieval 只允许受控 source key 和 catalog rows |
| KG | canonical/inferred facts、实体/关系上下文 | 以 artifact ref 和 evidence context 进入；KG 派生事实不能伪装成原始观察 |
| Evidence | retrieval artifact、source observations、gap ledger、sufficiency/ambiguity 状态 | 聚合阶段按 requirement 重载并验证 parent closure；不足时生成 typed `EvidenceGap` |
| Cognition/WM v0 | 当前世界模型快照及 digest，用于 L1-GROUND identity projection | 在 L1-GROUND materialization 时校验 context/world model digest，并通过 commit port 产生新的 snapshot |
| phases.yaml | 每个维度的允许 fact types、source hints、entity scope | L1 输入 context 和 provider schema 均从 dimension semantic contract 收窄 |

`L1Application.run()` 还会检查：

- request 的 `context_version` 与 snapshot 一致；
- `context_fingerprint` 存在；
- 每个 fact 必须存在 source refs；
- fact 中引用的 source segment 必须能在 artifact 中找到；
- 每个 EvidenceRetrievalArtifact 的 run、branch、descriptor digest、semantic digest、fingerprint 和 parent closure 必须一致；
- location identity requirement 的 mention 必须是 snapshot 顶层已登记的工作项，不能由 evidence artifact 凭空创建；
- sufficient identity resolution 必须有唯一 world entity candidate，否则必须留下 typed gap。

### 3.2 L1 的 12 个并行维度

`backend/app/config/phases.yaml` 中 L1 的 `id` 是 `layer1`，执行模式为 parallel，实际包含 12 个维度：

| 维度 | 主要观察倾向 | depends_on |
| --- | --- | --- |
| `location` | spatial entity、spatial relation、scoped metric、document observation | 无 |
| `socio_economic` | metric、entity、demand、constraint、opportunity、document observation | 无 |
| `villager_wishes` | demand、entity、constraint、opportunity、document observation | 无 |
| `superior_planning` | metric、constraint、entity、relation、document observation | 无 |
| `natural_environment` | entity、constraint、risk、metric、relation、document observation | 无 |
| `land_use` | entity、metric、constraint、relation、document observation | 无 |
| `traffic` | entity、relation、metric、constraint、risk、document observation | 无 |
| `public_services` | entity、demand、metric、constraint、relation、document observation | 无 |
| `infrastructure` | entity、demand、relation、metric、constraint、risk、document observation | 无 |
| `ecological_green` | entity、relation、metric、constraint、risk、document observation | 无 |
| `architecture` | entity、relation、metric、constraint、risk、document observation | 无 |
| `historical_culture` | entity、relation、constraint、metric、document observation | 无 |

12 个 L1 维度均没有同层 `depends_on`，因此 router 可以一次性为所有未完成维度建立 `Send` worker。L2/L3 的维度依赖规则则不同，不能据此推断 L1 后续层也可以并行。

### 3.3 source page 与 context digest

维度观察不是把全部资料一次性塞给模型：

1. `retrieval.py` 为可用输入建立稳定 source index 和 segment id；
2. `context.py` 以固定页大小 `6200` 字符生成可恢复页面；
3. input context 记录允许 fact types、source projection、page count、segment id digest 和最多 32 条输入 gap；
4. 恢复时 cursor 必须匹配当前 input digest，旧 cursor 不能在新输入上继续写入；
5. 每个 page 都有独立 structured call 和 checkpoint，page 失败不会抹掉已经验证的前页结果。

这使 L1 具备了基本的 bounded/resumable 特征，也使“输入变化以后能否局部重算”有了可用的 page/dimension 边界；不过完整的 dependency/subgraph digest 和跨 artifact invalidation 仍未完成。

## 四、L1 维度观察实现

### 4.1 调用链

```text
layer_router._ready_dispatch()
    → l1_worker_node()
        → analyze_dimension()
            → run_l1_dimension_loop()
                → build_l1_input_context()
                → build_l1_observation_output_model()
                → run_structured()  # per page
                → normalize_provider_output()
                → _validate_observation_sources()
                → checkpoint / dimension product
```

`layer_router._ready_dispatch()` 按 `phases.yaml` 过滤已完成维度和依赖项；L1 维度没有相互依赖，因此首轮可并发。`layer_aggregate_node` 等所有维度完成后才调用聚合器，避免把单一维度的中间产物直接当作 L1 全局快照。

### 4.2 LLM 的允许与禁止

Provider wire model 为每页最多 16 条 observations、最多 8 条 diagnostics；随后代码依据当前维度 contract 构造更窄的内部模型。系统约束的重点是：

允许：

- 提议 typed observation；
- 提供事实类别、值、单位、counting basis、粗粒度 scope；
- 提供来源 segment、source ref 和原文 quote；
- 标记 confirmed、uncertain、conflict、source_exhausted 等状态；
- 提供显式地点名称和关系锚点，作为后续 GROUND 工作项。

禁止：

- 创造 source ref、source span 或不存在的原文；
- 直接给出坐标、geometry、BSM、candidate、execution 或规划方案；
- 把抽象主题（如“公共服务水平”）当成空间实体；
- 通过 report prose 的正则挖掘地点；
- 在没有证据时用模型常识补齐事实；
- 生成一个“看起来完整”的空快照。

### 4.3 规范化和 quarantine

`observation_draft.py` 先接收稳定 provider schema，再将其转换为内部的 8 类 typed fact union：

`spatial_entity`、`spatial_relation`、`scoped_metric`、`demand`、`constraint`、`risk`、`opportunity`、`document_observation`。

每条记录经过以下检查：

1. 是否是当前维度允许的 fact type；
2. 事实字段是否满足该类型的必填条件；
3. source segment 是否存在；
4. quote 是否能在来源中按规范化规则匹配；
5. quote 是否跨越相邻 segment（该情况允许，但必须可复核）；
6. spatial label 是否是来源中的 literal、是否具有空间语义；
7. location 是否应保留为工作项而非直接解析成 entity。

不能通过的行进入 quarantine，并记录 payload digest、error path 和原始 payload 摘要；它们不会混入 authoritative fact_records。页面失败则保留前页结果并写入 `l1_observe_page_failed` diagnostic。

### 4.4 报告不是第二次 LLM 推理

当前 `run_l1_dimension_loop()` 完成观察后，如果没有 display report，就由 `_deterministic_report_body()` 根据已验证 observations 生成表格型 report body。也就是说当前实现没有一个“先观察、再让 LLM 重写完整报告”的第二次自由文本 pass。

这降低了报告与结构化事实不一致的风险，但仍有一个命名风险：artifact 中的 `display/report` 字段容易让调用者误以为它是 L1 的真相来源。后续 API 和文档应明确 `semantic observations/fact_records` 是权威，display 只能用于审阅和导出。

## 五、L1 聚合与权威产物

### 5.1 聚合顺序

```text
12 个 l1_dimension__* artifact
          │
          ▼
load_layer_dimension_products()
          │
          ▼
compile_dimension_report()
          │
          ▼
merge_l1_snapshots()
  ├── display dedup
  ├── typed fact dedup by fact_id
  ├── location dedup by normalized name / role / dimension / source
  ├── source dedup
  └── comparable numeric contradiction detection
          │
          ▼
Evidence requirements + retrieval artifacts + gap ledger
          │
          ▼
evaluate_l1_gate()
          │
          ├── store l1_snapshot
          ├── store l1_gate
          └── build review package / audit step report
```

### 5.2 `L1Snapshot` 的语义组成

当前 snapshot 至少承载以下几类信息：

| 类别 | 含义 | 是否可直接作为规划目标 |
| --- | --- | --- |
| `fact_records` / `L1Fact` | 有来源、有类型、有值或陈述、有 inference level 的事实 | 否，只能作为 L2 输入证据 |
| `location_mentions` | 来源中明确出现的地点/空间表达，是待接地 work item | 否，不能当作 canonical entity |
| `relations` / relation anchors | 方向、相对位置或关系陈述 | 否，关系两端仍需独立接地 |
| `sources` / provenance | source refs、segment/span、artifact lineage | 是可信度和复核依据，不是规划对象 |
| `evidence_gaps` | 缺来源、歧义、不充分、失败、人审等可恢复或不可恢复问题 | 否，必须保留其不确定性 |
| `issues` / diagnostics | contradiction、semantic admission、dimension incomplete 等质量问题 | 否，用于 gate/recovery |
| `evidence_requirements` | 后续 Evidence/GROUND 可执行的请求 | 否，不是目标或候选 |
| `display facts/constraints` | 审阅和报告导出用的展示投影 | 否，不应重新成为事实权威 |

其中 KG canonical fact 和 Bundle/GIS derived fact 会被标记为 `inferred` 或 `derived`，不能因为进入 L1 snapshot 就改写成 source observation。

### 5.3 事实冲突处理

聚合器对可比较的 typed numeric facts 依据 dimension、subject scope、comparable identity、unit、counting basis 分组；同组出现不同值时产生 `fact_contradiction` error，不做平均、不静默覆盖。L1 gate 会将该类错误路由到 `L1` rework。

这是设计文档中“conflict group + supersedes”目标的前置实现；目前已有 contradiction detection，但还没有完整的冲突组 artifact、supersedes 链和增量重建协议。

### 5.4 Evidence 在 L1 中的位置

L1 聚合不是只拼接各维度的结果。它会为 location identity 等 requirement 调用 Evidence runtime：

- 每个 requirement 通过 cognition round 记录 retrieval；
- 候选数量有上限（当前 location identity candidate limit 为 8）；
- 只有 packet sufficient/resolved、唯一 world entity candidate、且有 candidate ref 才能视为 sufficient；
- 不足会生成带 candidate total、ambiguity、stop reason、recovery action 的 typed gap；
- location identity 的 retrieval 结果仍作为 candidate/evidence，最终 identity binding 由独立 L1-GROUND 完成；
- 非 identity 的本地 DATA/KG 充分证据可以提升为 authoritative fact record，但仍保留来源和 lineage。

因此，Evidence 是“来源采集和充分性判断”，L1 是“事实接纳和快照聚合”，GROUND 是“地点身份/范围/关系接地”，三者职责不能合并。

## 六、L1 Gate 与 workflow 编排

### 6.1 当前 gate 判定

`evaluate_l1_gate(snapshot)` 是纯函数，不做 I/O。主要路径：

| 条件 | 当前 route | 解释 |
| --- | --- | --- |
| dimension product incomplete | `HUMAN` | 维度产品未形成完整 typed artifact |
| 空 snapshot（无 facts、constraints、sources） | `HUMAN` | 禁止空壳成功 |
| `fact_contradiction` 或空间语义准入 error | `L1` | 回到 L1 语义修复 |
| source-feature 定量事实缺 source snapshot/feature ids | `EXPLORE` | 先补 lineage |
| gap 明确要求人工或不可恢复 | `HUMAN` | 不自动猜测 |
| 有 source/gap 可恢复问题 | `EXPLORE` | bounded evidence recovery，再重跑受影响维度 |
| 有非空事实、无 error、无 actionable gap | `PASS` | 进入下一阶段 |

这里有一个需要维护者注意的代码/文档不一致：`gate.py` 顶部 docstring 仍写着“PASS 可携带 unresolved evidence 的 usable partial snapshot”，但当前实现对 warning/error 级 actionable gaps 直接返回 `EXPLORE`，并明确注释“L2 不能把 partial snapshot 当成完整观察产品”。运行行为应以函数实现和测试为准，docstring 应后续修订。

### 6.2 EXPLORE 的恢复范围

workflow 的 explore route 使用 bounded retry（当前最大 retry count 为 2），执行一次受控证据检索；只有 digest 发生变化并且补到了事实，才重新运行相关维度。若能识别具体 pending dimension，则只重跑该维度，否则回退到当前层配置的维度集合。

这实现了“gap 不等于全流程失败”的基本恢复语义，但与设计目标的“changed evidence 只影响受影响 rows”相比，目前更接近 dimension-level recovery，还没有完整 row-level dependency invalidation。

### 6.3 L1 聚合节点的真实顺序

`layer_aggregate_node()` 在 layer 1 完成后执行：

1. 若 context 尚未冻结，先运行 idempotent bootstrap；
2. 调用 `run_l1()`，让 L1Application 生成并重载 snapshot/gate；
3. 根据 gate 更新 explore retry；
4. 立即调用 `GroundApplication.materialize_l1_locations()`；
5. 把 identity sidecar 和 World Model transition refs 合并回 state；
6. 清空 `layer_just_completed`，交回后续 gate/phase routing。

因此“L1 聚合完成”在当前 workflow 中不是最后一步；L1 identity materialization 紧随其后。这是当前实现的重要事实，也解释了为什么 L2 在运行前会检查 L1 World projection transition 是否 `ready`。

## 七、L1-GROUND：L1 的第一个下游，也是独立的边界

### 7.1 输入输出

L1-GROUND 的输入是 `L1Snapshot.location_mentions` 和对应 Evidence/context；它不是 `TARGET_PROJECTION`，因为此时尚未有规划 intent。输出包含：

- `l1_observations`：地点观察 sidecar；
- `l1_bindings`：mention 到 entity/scope/relation 的 binding sidecar；
- `l1_world_projection` 和 `world_model_current_snapshot`；
- 更新后的 `l1_gate`/transition refs；
- 对 ambiguous/unresolved 等状态的 gap schedule。

当前实现明确先 reload snapshot 并校验 artifact context，再构造/重载 cognition ports 和 World Model context；如果 commit 后的 child context/version/digest 不一致则 fail closed。

### 7.2 已实现的关键保护

- LLM 只能在 deterministic candidate closed set 上提出 identity proposal；
- canonical id 不能由 LLM 自己创造；
- exact、feature-set、inferred-scope、ambiguous、unresolved 等状态会保留在 binding；
- relation 的方向和 anchor role 独立保存；
- fuzzy phrase、relative location 和 zero-candidate 会保留语义/gap，不被强制提升为空间实体；
- binding snapshot 记录 observation ref、parent digest、source WM snapshot ref/digest 和 status counts；
- World Model commit 使用 identity commit envelope/result，并生成新的 current snapshot。

### 7.3 与目标设计的差距

设计目标要求更清晰的事务边界：

```text
GROUND candidate retrieval
    → closed-set proposal
    → proposal validation / decision artifact
    → Cognition transaction writes WM v1
    → post-commit binding revalidation
    → publish final binding / L1 manifest
```

当前代码已有这条调用链的大部分骨架，但 proposal validation/decision ownership 仍更多地位于 orchestration 内；统一终态 taxonomy、commit 后 revalidation、merge/split/rebase 引发的 binding invalidation 尚未成为完整的独立 contract。

## 八、L1 下游对比：L2、L3 和规划 GROUND

### 8.1 L2 当前实现 vs 目标设计

| 项目 | 当前代码 | 目标设计 |
| --- | --- | --- |
| 输入 | `l1_snapshot` canonical artifact ref，外加已通过的 data/kg/evidence/l1 gates | `L1FinalProduct`、`L1BindingSnapshot`、current WM ref/digest、task/config/Evidence |
| 运行前检查 | 重载 snapshot；验证 L1 transition status 为 `ready`；检查 context version | 对 observation、binding、WM digest 做统一 final-view gate |
| 输出 | `l2_strategy` + `l2_gate` + review id | `L2DecisionSet` / `L2Strategy`，完整保留 fact/evidence/conflict/uncertainty/gap lineage |
| 禁止内容 | 代码递归拒绝 candidate、geometry、scenario、execution、planned state；拒绝 goal/target-like metrics | 同样禁止，把规划意图与可执行空间对象严格分离 |
| 当前风险 | L2 入口仍以 `l1_snapshot` 命名和传递，final manifest/binding/WM 是 transition 中的额外状态，不是单一产品句柄 | 由轻量 `L1ProductManifest` 封装最终可消费视图，L2 不再依赖多处拼装 |

结论：L2 的防越界校验已经很强，但产品形态尚未收敛。不能只看到 `l1_snapshot` 已重载就宣称“L2 已经消费 L1 final view”；从目标设计角度看还缺 manifest 和统一 finalization contract。

### 8.2 L3 当前实现 vs 目标设计

当前 `L3Application`：

- 要求 `l1_snapshot` 和 `l2_strategy` canonical refs；
- 要求 data/kg/evidence/l1/l2 upstream gates；
- 要求 persisted L2 gate PASS；
- 重载并校验 L1/L2 context version；
- 递归拒绝 entity/geometry/candidate/BSM/scenario/approval/参数化空间对象等字段；
- 校验 target rows、interventions、spatial requirement rows、candidate request refs 和 L2 refs 闭包。

这说明 L3 目前主要承担“从 L2 形成受控 planning intent”的边界验证。它仍不应生成具体地块、geometry 或 candidate；这些属于 Target Projection / Planning GROUND 之后的规划空间管线。

### 8.3 两类 GROUND 必须保持分开

```text
L1Snapshot.location_mentions
    → L1-GROUND
    → present-world identity / scope / relation binding

PlanningProgram / admitted planning intent
    → TARGET_PROJECTION
    → planning GroundingRequest
    → Planning GROUND
    → purpose-specific representation / geometry / candidate domain
```

把两条链合并会造成两个严重问题：一是地点名称在 L1 阶段被误当成规划目标，二是 L1 的 present-world identity resolution 被迫生成规划用途 geometry。当前代码和设计文档都要求它们分开。

## 九、当前实现与设计文档的差距矩阵

| 能力 | 当前实现证据 | 目标设计要求 | 状态 / 风险 |
| --- | --- | --- | --- |
| typed L1 facts | `L1SourceEvidence`、8 类 fact union、`L1Fact` stable id | observation rows 成为唯一事实入口 | `PARTIAL`：实现已在用，但旧 display/prose projection 仍存在 |
| source-span validation | segment、quote、相邻 segment 校验 | 独立 validation report：valid/source missing/segment missing/literal mismatch/offset mismatch/cross-source/role | `PARTIAL`：校验逻辑有，最终 report/contract 不完整 |
| location mention | explicit structured fields 进入 work item | mention 与 entity 分离，禁止名字即实体 | 基本完成，仍需统一 finalization |
| relation grounding | relation anchor/方向保留，端点独立接地 | relation binding 有独立终态和 revalidation | `PARTIAL` |
| aggregation conflict | comparable numeric contradiction 触发 L1 rework | conflict group、supersedes、无平均覆盖 | `PARTIAL` |
| L1 product | `l1_snapshot`、`l1_gate`、sidecars、WM refs 分散存在 | `L1ProductManifest` 封装 final view | 关键差距，影响 L2/L3 依赖表达 |
| evidence gap | typed gap、recovery pointer、bounded explore | gap/failure/HUMAN 三类语义稳定且可重放 | 基本具备，provider coverage/lease 仍不完整 |
| L1-GROUND terminal | exact/feature-set/inferred/ambiguous/unresolved 已兼容 | 统一 terminal taxonomy + proposal/decision artifact | `PARTIAL` |
| World Model 写入权 | 当前 orchestration 调用 `WorldModelCommitPort`，V2 store 原子提交 | GROUND 只产 proposal，Cognition transaction 是 writer | 需要进一步拆 ownership |
| commit 后校验 | commit result digest/version 有校验 | binding revalidation 后才发布 final | 尚未完整闭环 |
| invalidation | global digest 和部分 parent refs | dependency/subgraph digest，局部重算 | 当前偏 conservative，无法宣称 row-level 增量 |
| L2 final-view gate | L2 检查 L1 transition ready | final product + binding + WM 统一门禁 | `PARTIAL` |
| L3 boundary | L1/L2 refs、gate、字段拒绝、闭包校验 | 稳定 final view 形成非空 planning intent | 骨架具备，仍依赖上游产品收敛 |
| acceptance benchmark | 有单元/契约测试，部分 probe | 标注集上的 grounding precision、candidate recall、语义质量门 | 尚未成为 release gate |

## 十、最值得优先处理的风险

### P0：先统一 L1 final product，再继续扩大 L2 消费

当前 L2 的入口已经阻止 partial World projection，但输入句柄仍是 `l1_snapshot`，而最终可消费语义分散在：snapshot、l1 gate、l1 observations、l1 bindings、world model current snapshot 和 transition refs。

建议先定义并持久化轻量 `L1ProductManifest`，至少包含：

- `context_version/fingerprint`；
- `l1_snapshot` ref；
- `l1_observations` ref；
- `l1_bindings` ref；
- current WM snapshot ref/digest；
- final L1 gate ref；
- evidence/gap digest；
- parent/dependency digest；
- finalization status 和 generation。

然后让 L2 只从 manifest 解析 final view，并把现有 transition 校验降为 manifest 的内部一致性检查。

### P1：把 GROUND proposal、Cognition commit、post-commit revalidation 拆成明确的 contract

现在调用链已经真实存在，继续把所有责任放在 `GroundApplication.materialize_l1_locations()` 会让它同时承担 retrieval、reasoning、sidecar persistence、World Model commit、gate 和 finalization。下一步应把：

1. candidate retrieval；
2. closed-set proposal；
3. proposal validation/decision；
4. Cognition atomic commit；
5. binding revalidation；

拆成可独立测试和重放的 artifact/port 边界。

### P1：修正文档与 gate 实际行为

`gate.py` 顶部仍描述“允许 unresolved evidence 的 PASS”，实现却对 actionable gaps 返回 `EXPLORE`。这会误导调用方和验收人员。建议以当前 fail-closed 代码为准，修改 docstring 和 canonical contract 的 gate matrix，并补一个专门断言 partial gap 不得进入 L2 的测试。

### P1：淘汰旧 acceptance probe 的假设

`business_stage_boundary_probe.py --help` 当前不会显示帮助，而是直接执行 probe；执行过程中在 `stage="L1"` 的 spatial requirement 上失败，原因是 probe 仍断言每个 requirement 的 `source_families` 必须包含 `bundle`。当前 Evidence requirement 使用的是中立 source family（如 `artifact`、`data`、`kg`、`report`），与这个旧 probe 假设不一致。

这不是 L1 runtime 本身的失败，而是验收脚本与当前 source-family contract 漂移。应先更新 probe 的 contract 断言，再把它纳入稳定验收入口；不要为了让旧 probe 通过而把 `bundle` 硬塞回统一 source-family 语义。

### P2：把全局 digest 收敛为 dependency/subgraph digest

当前大量 artifact 记录 global World Model digest。这样安全但偏保守：一个小范围 identity 变化可能让无关 L1/L2 artifact 看起来 stale。应先补 dependency/subgraph digest 和 invalidation reason，再开放局部重算；在此之前保持 conservative invalidity 是正确的安全取向。

## 十一、验证结果

### 11.1 已通过

以下检查在当前工作树执行通过：

```text
python -m compileall -q backend/app
  通过

python -m pytest tests/test_llm_table_protocol.py -q
  16 passed in 4.98s

python -m pytest tests/test_cognition_round_contract.py tests/test_evidence_acquisition_contracts.py -q
  14 passed in 0.79s

python -m pytest tests/test_data_p1_p2_docs.py tests/test_data_boundary_contracts.py -q
  8 passed in 1.08s
```

`test_llm_table_protocol.py` 对 L1 尤其有代表性，覆盖了抽象主题隔离、物理地点保留为 work item、L1 后独立 GROUND、identity requirement 分组、关系方向、模糊地点、相对位置 gap 和 retry gate 等边界。

### 11.2 未能作为全量绿灯的检查

执行 `python -m pytest -q` 时，pytest collection 被仓库内参考项目测试阻断，结果不是 L1 逻辑失败：

- `docs/references/DRL-urban-planning/misc/osmnx_test.py` 缺少 `osmnx`；
- `docs/references/geopandas-ai/.../test_public.py` 缺少 `dependency_injector`；
- `tests/test_data_change_set_boundary.py` 导入 `tests.test_data_dependency_invalidation` 失败。

因此不能把全量命令标记为通过，也不能把 collection failure 归因于 L1。应使用项目正式 pytest 配置排除参考项目，或补齐测试包边界后再做全量验收。

`l1_facade_probe.py --help` 和 `l1_l2_facade_probe.py --help` 可以正常显示 usage；它们需要真实 `--session-id` 才能验证完整 runtime facade。本次审计没有凭空创建 session，因此未把 facade probe 结果冒充为端到端通过。

## 十二、建议的收敛顺序

建议按以下顺序推进，不要先扩充更多维度或更多 provider：

1. **冻结产品语义**：定义 `L1ProductManifest`，明确 snapshot、binding、WM current snapshot 和 gate 的 parent/digest 关系。
2. **统一 finalization**：让 L1-GROUND 完成后由单一 finalizer 重新校验 context、binding、WM digest，再发布 manifest。
3. **重构 L2 入口**：L2 只接收 manifest 解析出的 final view；保留禁止 executable fields 的现有保护。
4. **拆 GROUND ownership**：把 proposal、decision、Cognition transaction、revalidation 从大 orchestration 中抽出。
5. **补 conflict/invalidation artifact**：补 conflict group/supersedes 和 dependency/subgraph digest。
6. **修订 acceptance**：更新 `business_stage_boundary_probe.py` 的 source-family 假设，增加 final manifest、partial gap、post-commit revalidation 和局部 invalidation 的契约测试。
7. **再做全链路 benchmark**：以真实标注集登记 source-span、地点接地、candidate recall、ambiguity 和 relation accuracy 质量门。

## 十三、推荐阅读路径

想快速理解实现，建议按这个顺序阅读：

1. `backend/app/modules/l1/README.md`：L1 ownership 和禁止项；
2. `backend/app/modules/l1/application.py`：公共 facade、输入身份和 reload 校验；
3. `backend/app/modules/l1/context.py`：分页观察、source validation、checkpoint；
4. `backend/app/modules/l1/observation_draft.py`：typed provider/internal contract；
5. `backend/app/modules/l1/aggregation.py`：聚合、Evidence、CAS parent closure；
6. `backend/app/modules/l1/gate.py`：当前 gate 的真实 route；
7. `backend/app/workflow/layers/layer_aggregate_node.py`：L1 聚合后如何进入 L1-GROUND；
8. `backend/app/modules/ground/application.py` 的 `materialize_l1_locations()`：identity sidecar 和 WM commit；
9. `backend/app/modules/l2/application.py`、`backend/app/modules/l3/application.py`：下游消费与边界拒绝；
10. `docs/design/01_CONTRACTS_AND_INVARIANTS.md` 与 `docs/design/05_MIGRATION.md`：目标语义和正式差距账本。

## 十四、证据索引

### 当前实现

- [L1 module README](../../backend/app/modules/l1/README.md)
- [L1 application facade](../../backend/app/modules/l1/application.py)
- [L1 context and observation loop](../../backend/app/modules/l1/context.py)
- [L1 observation contracts](../../backend/app/modules/l1/observation_draft.py)
- [L1 aggregation](../../backend/app/modules/l1/aggregation.py)
- [L1 gate](../../backend/app/modules/l1/gate.py)
- [Layer aggregate workflow](../../backend/app/workflow/layers/layer_aggregate_node.py)
- [Layer router](../../backend/app/workflow/layers/layer_router.py)
- [L1-GROUND application](../../backend/app/modules/ground/application.py)
- [L2 application](../../backend/app/modules/l2/application.py)
- [L3 application](../../backend/app/modules/l3/application.py)
- [L1 dimension configuration](../../backend/app/config/phases.yaml)

### 目标设计和迁移账本

- [L1 contracts and invariants](01_CONTRACTS_AND_INVARIANTS.md)
- [L1-GROUND executable design](L1_GROUND_EXECUTABLE_DESIGN.md)
- [Planning cognition](02_PLANNING_COGNITION.md)
- [Current runtime](../architecture/CURRENT_RUNTIME.md)
- [Migration ledger](05_MIGRATION.md)
- [L1 acceptance](acceptance/04_l1_acceptance.md)
- [L1-GROUND acceptance](acceptance/05_l1_ground_acceptance.md)
