# 05 TARGET_PROJECTION 与 GROUND

## 1. TARGET_PROJECTION

输入 `PlanningProgram`，输出带有 admitted spatial specs、由粗空间 claim 编译出的 pending grounding specs、`GroundingRequest` 和 pending request 的 `IntentCompilationResult` artifact。它建立 target identity、target family、package、claim lineage、geometry/evidence/relation requirements 和 grounding readiness；pending claim 只登记待处理事项，不等同于已接纳的 typed target。只要存在具体 pending grounding spec/request，TARGET_PROJECTION 就可以将 partial 结果交给 GROUND；真正空投影或结构性 admission error 才阻断。

```text
PlanningProgram → admission → target identity/family
→ requirement compilation → lineage validation → GroundingRequest
```

它不能从 prose 猜 geometry、候选或执行参数，也不执行空间查询。

## 2. GROUND

GROUND 有两个入口，不是单一的 `TARGET_PROJECTION → GROUND` 串行模块：

```text
L1Snapshot.LocationMention
    → GROUND location resolution
    → l1_observations / l1_bindings

PlanningProgram
    → TARGET_PROJECTION → GroundingRequest
    → GROUND planning-target grounding
    → GroundedPlanningProblem
```

第一条入口在 L1 聚合后即可执行。它先通过统一 `EvidenceFacade` 获取带 provenance、coverage 和候选分页的 `EvidencePacket`，再由 GROUND 处理地点身份、scope、关系、候选检索、迭代和闭集语义判别；结果作为第二条入口的空间上下文复用。第二条入口才负责将 L3 规划意图接地为规划候选。两条入口都只使用当前 `SessionDataSnapshot`、Bundle、KG、GIS 和当前 Evidence，不读取历史会话。

GROUND 输入 `GroundingRequest`、L1Snapshot、EvidencePacket、SpatialWorkspace，输出 `GroundedPlanningProblem`。pending claim 可以进入受当前 L1 snapshot 和已解析绑定约束的候选/证据解析，但仍保留 pending 状态；GROUND 不能替 L3/LLM 生成复杂 intervention parameters，也不能将自然语言线索直接升级为可执行目标。存在 unresolved/pending grounding 时，GROUND 仍可用 `passed_with_unresolved_grounding` 将 typed problem 交给 SELECT；这不等于候选或 geometry 已通过验证，SELECT 必须继续失败闭合并产出诊断/延迟结果。

L1 provider 可以在 observation 内输出受限的 `spatial_mentions` 工作项，保留来源明确的地点名称、角色、scope、关系和 source ids。它们只是 GROUND 的检索输入，不是身份、BSM、候选或几何；GROUND 必须重新从当前 Bundle/KG/GIS 证据解析并确定性校验，无法唯一解析时保留具体 target 的 unresolved/ambiguous 结果。

```text
resolve references → classify resolved/unresolved
→ build context from resolved objects
→ related evidence/spatial retrieval with complete pagination
→ bounded closed-set LLM resolution proposal
→ deterministic spatial verify
→ use resolved objects to assist unresolved references
→ retrieve a target-scoped supplemental evidence wave
→ rebuild candidates and ask the LLM again within budget
→ candidates/constraints → problem
```

L1 location resolution 和规划 target grounding 都遵循同一循环：已解决对象可提供邻近、拓扑、道路、地址和范围上下文；LLM 只能返回闭集中的 candidate ref，以及 selected/ambiguous/abstain 状态，最终 geometry 必须经过空间确定性校验。补充检索由 GROUND 根据缺口和固定 EvidenceFacade 需求执行，不由 LLM 生成 provider 查询。没有候选时必须保留具体 mention/target/claim 的 unresolved 记录和 source input 缺口，不能只返回空问题。

每一轮只重查仍未闭合的 mention/target，而不是重新查询整个阶段。补充证据会与当前候选、关系、来源文段合并，然后重新执行闭集 LLM 判断；因此新解析结果、L1 binding、KG relation、Bundle/GIS feature 或来源文段能够使原本 unresolved/ambiguous 的定位重新进入可解析路径。循环受 `GROUND_MAX_RECOVERY_ROUNDS` 限制，候选/关系/来源包不变时提前停止。LLM 只能在本轮实际召回的来源候选中选择或弃权，不能产生 ID、BSM、坐标、WKT、几何或规划参数。

每轮结果还记录 target/mention 的前后状态、`became_resolvable_*` 转移、候选集 digest、LLM 的 selected/ambiguous/abstain 决策及 input digest。这样“新证据让哪个定位变得可解析”不是日志推测，而是当前 artifact 中可恢复的状态变化；LLM 的理由只作为审计信息，权威状态仍由候选闭集、当前 Bundle/GIS 几何和确定性空间约束共同确认。

## 3. 输出与验收

`GroundedPlanningProblem` 必须包含 targets、candidates、geometry、relations、constraints、evidence refs、snapshot refs、unresolved、deferred 和 fingerprint。每个 target 必须有接地状态；无数据和无候选必须区分；SELECT 只能消费该闭集。

## 4. 目标目录与迁移出口

```text
backend/app/modules/target_projection/
├── application.py
├── admission.py
├── target_identity.py
├── requirement_compilation.py
└── lineage.py

backend/app/modules/ground/
├── application.py
├── reference_resolution.py
├── iterative_resolution.py
├── resolved_context.py
├── evidence_binding.py
├── candidate_builder.py
├── constraint_check.py
└── problem_builder.py
```

当前 TARGET_PROJECTION 与 GROUND 业务实现分别集中在 `modules/target_projection/`、`modules/ground/`；底层解析保留在 `spatial/grounding/`。迁移出口是 `L1Snapshot → GROUND location resolution` 和 `PlanningProgram → GroundingRequest → GroundedPlanningProblem` 均可真实执行；已解决对象能辅助未解决定位，pending claim 的缺口可回指 `planning_program`/`target_projection`/`grounding_result` 及当前 L1 snapshot，SELECT 不调用 GROUND 内部函数。
