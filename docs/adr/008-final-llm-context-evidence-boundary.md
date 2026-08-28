# ADR 008: LLM 上下文与结构化调用边界

> Status: ACCEPTED
> Authority: 本 ADR 规定生产 LLM 调用的上下文与结构化输出边界；检索设计以 `docs/design/04_EVIDENCE.md` 为准，实施状态以 `docs/design/05_MIGRATION.md` 为准。

## 1. 决策

- 生产 LLM 调用必须经过统一的 LLM Manager；调用者提交受控的 prompt projection、结构化 schema 和调用元数据。
- LLM 只负责语义抽取、候选生成、排序/决策、解释和摘要。身份、版本、范围、证据引用、几何、指标、状态、校验和批准结果由确定性代码产生或校验。
- 分析上下文、检索上下文和交付上下文分离。原始报告正文、未筛选依赖和不可追溯的自由文本不得直接进入规划决策上下文。
- 检索输入使用 `EvidenceRequirement`/`EvidenceQueryPlan`，输出使用规范化 `EvidenceResult`/`EvidenceCoverage`；下游只接收其需要的最小投影。
- provider wire schema 只表达一次模型事务的最小语义草稿，不复制内部 domain/admission/GROUND/solver/execute 对象。L1/L2/L3 调用按 observation、abstract decision、rough claim 等单一认知目的拆分。
- 集合输出以 item 为校验、隔离和 repair 原子；一个无效 item 不得使同一批次中已验证 items 失效，也不得默认触发完整维度重生成。
- L3 只产生非可执行 rough claims。claims 后最多生成 intent summary；详细规划报告必须等待 `GroundedPlanningProblem` 与 `ScenarioSet`，正式交付报告还必须绑定 validation/reconciliation lineage。

## 2. 结构化输出边界

模块输出应表达一个稳定的业务边界，而不是复制内部中间态。内部 Pydantic/domain object 可以为后续确定性编译保留丰富字段，但这些字段不自动属于 provider response model。L1 的观察、事实和位置工作项当前仍是兼容实现；目标收敛为语义快照、证据缺口和可追溯引用。任何 LLM 输出都必须经过 envelope/schema 校验、逐项引用校验、逐项确定性归一化和 accepted/rejected accounting 后才能进入下一阶段。

结构化输出保证的是受支持 provider 上的 wire/schema 约束，不证明字段值在领域上正确，也不证明一次调用的职责和失败原子合理。schema retry、item quarantine 与 workflow retry 必须分别声明和审计；统一 manager 不得静默覆盖调用者的显式 retry policy。L3 的权威 PlanningProgram 聚合不允许再由 LLM 二次改写；需要补正时回到具体维度的 claims 输入或显式 HUMAN 决策边界。

## 3. 当前状态

本 ADR 是目标边界，不表示所有调用点已经符合。直接 provider 调用、旧的 L1/L2 缺口形状、冗余 prompt 字段和临时 proposal 生命周期均在迁移中；详见 `docs/design/05_MIGRATION.md` 与 `docs/architecture/CURRENT_RUNTIME.md`。

## 4. 取舍与废止项

本 ADR 不再把 `FactRegistry`、`ProjectCognitionView`、`FactProjection`、旧报告正文双读、`GroundedAnchor` 或 `anchor_cluster` 视为当前公共契约。它们若仍存在，只能作为内部兼容残留，并须由迁移台账跟踪。

## 5. 相关权威文档

- 检索、证据与 grounding：[`../design/04_EVIDENCE.md`](../design/04_EVIDENCE.md)
- 契约与不变量：[`../design/01_CONTRACTS_AND_INVARIANTS.md`](../design/01_CONTRACTS_AND_INVARIANTS.md)
- 运行时事实：[`../architecture/CURRENT_RUNTIME.md`](../architecture/CURRENT_RUNTIME.md)
- 迁移台账：[`../design/05_MIGRATION.md`](../design/05_MIGRATION.md)
