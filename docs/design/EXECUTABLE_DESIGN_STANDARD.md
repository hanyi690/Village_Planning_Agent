# 可执行模块设计标准

> Status: TARGET STANDARD
>
> 本文件规定设计文档必须回答什么；它不声明任何模块已经实现。实现事实只由
> <code>../architecture/CURRENT_RUNTIME.md</code>、代码、可重放 artifact 和测试证明。

## 1. 两层文档，不再混写

每个业务模块必须区分两类文档：

| 层级 | 回答的问题 | 允许包含 | 不允许冒充 |
|---|---|---|---|
| 可执行模块设计 | 模块应该如何运行、失败、恢复和被消费 | 边界、契约、状态机、事务、不变量、算法边界 | 当前实现证据 |
| 成熟度验收卡 | 当前阶段达到哪一级、由什么证据证明 | P0/P1/P2 gate、probe、remaining gap | 第二份模块设计 |

设计中的 <code>TARGET</code> 表示规范目标；验收卡中的已通过项必须指向当前可复现证据。
计划、周报、历史审计和一次性讨论只能作为背景，不得升级为实现状态。

## 2. 成熟度等级

### P0 / Loop Ready

当前认知闭环可真实运行。模块边界、typed artifact、状态/失败表达、持久化引用、恢复路径和
下游消费均闭合；对声明能力之外的输入必须 fail closed 并产生可恢复 gap。P0 不承诺任意输入、
任意 provider 或生产规模。

### P1 / MVP Ready

模块输出可被稳定的下游规划主链消费；版本、增量失效、人工边界和关键业务探针稳定。P1 关注
端到端规划价值，不等于生产级平台完备。

### P2 / Production Ready

覆盖生产输入广度、并发与幂等、安全与权限、性能与容量、可观测性、运维恢复和人工治理。
只有这些维度有量化证据时，才可声明 P2。

成熟度是累积的：P1 必须保持 P0，P2 必须保持 P0/P1。不得用 P2 缺口否定已验证的 P0，
也不得用 P0 链路存在推断 P1/P2 已完成。

## 3. 证据标签

验收卡只使用以下标签：

| 标签 | 含义 |
|---|---|
| <code>IMPLEMENTED</code> | 当前代码中存在对应路径，但未必经过运行探针 |
| <code>RUNTIME_VERIFIED</code> | 有可重复命令、fixture、artifact 或测试证明运行行为 |
| <code>PARTIAL</code> | 一部分契约已实现，关键条件仍缺失 |
| <code>TARGET</code> | 仅为目标设计，不得计为通过 |
| <code>HISTORICAL</code> | 历史证据，只说明当时状态 |

单一复选框不能证明模块完成。每个通过结论至少包含：证据标签、证据位置、复现方式、输入
边界和观察到的结果。

## 4. 模块设计的 16 个必答章节

每个核心模块 owner 必须显式回答以下章节；不适用时也要说明原因：

1. Responsibility：唯一职责和禁止事项。
2. Inputs：typed 输入、版本、快照和准入条件。
3. Outputs：typed 产品、诊断产品和引用关系。
4. Public Facade：唯一公开入口及下游调用方式。
5. State Machine：对象或工作项的状态及合法迁移。
6. Transactions：原子边界、提交点和回滚行为。
7. Invariants：任何路径都不能破坏的规则。
8. Failure Taxonomy：失败、空结果、拒绝、冲突和暂态错误的区别。
9. Gap & Recovery：gap owner、恢复动作、预算和停止条件。
10. Persistence/CAS：artifact key、不可变性、可重载性和幂等。
11. Version & Digest：输入版本、内容 digest、父版本和 stale 判定。
12. Dependency/Invalidation：依赖图、影响范围和增量重算。
13. Deterministic vs LLM Boundary：确定性逻辑、模型允许动作和后验证。
14. Observability/Trace：事件、指标、trace、reason code 和审计链。
15. Acceptance Probe：最小真实业务探针和预期 artifact。
16. Remaining Gaps：相对当前实现的明确差距，链接到唯一迁移账本。

## 5. 验收卡最小结构

每张卡只保留下列信息：

1. 模块设计 owner 链接；
2. 本轮验收的成熟度目标；
3. 该等级的 entry gate、product gate、consumer gate 和 recovery gate；
4. 当前证据表；
5. 未满足项及恢复/迁移指针；
6. 更高等级的 deferred scope。

如果验收暴露设计缺口，先修改设计 owner，再更新验收卡。不得在验收卡中继续堆积另一套
状态机、字段表或实现方案。

## 6. 状态声明规则

- “代码中存在类/字段”只足以标记 <code>IMPLEMENTED</code>。
- “测试通过”只证明测试覆盖的输入边界；必须记录 fixture 或 probe 范围。
- mock、空返回和手工拼接结果不能作为真实业务闭环证据。
- 当前与目标不一致时，在 <code>05_MIGRATION.md</code> 记录，不在设计正文中伪造完成度。
- 同一能力只能有一个设计 owner 和一张成熟度验收卡。
